from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Customer, CustomerPayment
from .forms import CustomerForm, CustomerPaymentForm
from django.contrib import messages
from django.utils import timezone

def _render_customer_list_response(request, success_msg=None):
    if success_msg:
        messages.success(request, success_msg)
    from django.http import HttpResponse
    response = HttpResponse()
    response['HX-Refresh'] = 'true'
    return response

@login_required
def list(request):
    customers = Customer.objects.all().order_by('name')
    if request.headers.get('HX-Request'):
        return render(request, 'customers/partials/customer_list_rows.html', {'customers': customers})
    return render(request, 'customers/index.html', {'customers': customers})

@login_required
def create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                # If called from POS, refresh the dropdown
                if request.GET.get('from_pos'):
                    customers = Customer.objects.all().order_by('name')
                    from django.template.loader import render_to_string
                    options_html = render_to_string('pos/partials/customer_dropdown_options.html', {'customers': customers}, request=request)
                    oob_html = f'<select name="customer_id" id="customer-select" class="block w-full px-5 py-4 bg-slate-50 border border-slate-200 rounded-2xl text-sm font-bold focus:ring-4 focus:ring-accent-500/10 focus:border-accent-600 transition-all appearance-none cursor-pointer" hx-swap-oob="true">{options_html}</select>'
                    from django.http import HttpResponse
                    response = HttpResponse(oob_html)
                    response['HX-Trigger'] = 'closeModal'
                    return response
                return _render_customer_list_response(request, "Customer registered successfully")
            messages.success(request, "Customer added successfully.")
            return redirect('customers:list')
    else:
        form = CustomerForm()
    
    if request.headers.get('HX-Request'):
        return render(request, 'customers/partials/customer_form_modal.html', {
            'form': form, 
            'title': 'New Customer Registration',
            'button_text': 'Register Customer'
        })
    return render(request, 'customers/form.html', {'form': form, 'title': 'Add Customer'})

@login_required
def update(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_customer_list_response(request, "Customer profile updated")
            messages.success(request, "Customer updated successfully.")
            return redirect('customers:list')
    else:
        form = CustomerForm(instance=customer)
    
    if request.headers.get('HX-Request'):
        return render(request, 'customers/partials/customer_form_modal.html', {
            'form': form, 
            'title': 'Edit Customer Profile',
            'button_text': 'Update Profile',
            'customer': customer
        })
    return render(request, 'customers/form.html', {'form': form, 'title': 'Edit Customer'})

from django.db.models import ProtectedError

@login_required
def delete(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        try:
            customer.delete()
        except ProtectedError:
            messages.error(request, "Cannot delete customer: They have associated sales or transactions.")
            if request.headers.get('HX-Request'):
                return _render_customer_list_response(request)
            return redirect('customers:list')
            
        if request.headers.get('HX-Request'):
            return _render_customer_list_response(request, "Customer record removed")
        messages.success(request, "Customer deleted.")
        return redirect('customers:list')
    
    if request.headers.get('HX-Request'):
        return render(request, 'customers/partials/confirm_delete_modal.html', {'customer': customer})
    return render(request, 'customers/confirm_delete.html', {'customer': customer})

@login_required
def record_payment(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    if request.method == 'POST':
        form = CustomerPaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.customer = customer
            payment.save() # Signal handles balance update
            if request.headers.get('HX-Request'):
                return _render_customer_list_response(request, "Payment recorded successfully")
            return redirect('customers:list')
    else:
        form = CustomerPaymentForm()
    
    return render(request, 'customers/partials/payment_form_modal.html', {
        'form': form,
        'customer': customer,
        'title': 'Record Customer Payment'
    })

@login_required
def payment_history(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    from pos.models import Sale
    from inventory.models import StockMovement
    from django.db.models import Max

    pos_sales = Sale.objects.filter(
        customer=customer, payment_method='CREDIT', is_refunded=False
    ).prefetch_related('items')
    payments = CustomerPayment.objects.filter(customer=customer).order_by('-payment_date')

    # Most recent return date per sale, used to date the return-credit entries
    # below (returned_quantity is cumulative, so we show one credit per sale).
    return_refs = {f"RET-SALE-{s.id}": s.id for s in pos_sales}
    return_dates = {}
    if return_refs:
        for mv in (StockMovement.objects
                   .filter(movement_type='RETURN', reference_id__in=return_refs.keys())
                   .values('reference_id').annotate(last=Max('timestamp'))):
            return_dates[return_refs[mv['reference_id']]] = mv['last']

    ledger = []
    for sale in pos_sales:
        ledger.append({
            'type': 'DEBT',
            'date': sale.timestamp,
            'amount': sale.total_amount - sale.discount,
            'reference': f"Sale #{sale.id}",
            'notes': "POS Credit Purchase"
        })
        # Partial returns reduce what the customer owes — record them as credits
        # so the ledger reconciles with the outstanding balance.
        refunded = sale.refunded_amount
        if refunded > 0:
            ledger.append({
                'type': 'RETURN',
                'date': return_dates.get(sale.id, sale.timestamp),
                'amount': refunded,
                'reference': f"Sale #{sale.id}",
                'notes': "Items returned",
            })

    for p in payments:
        # Convert date -> datetime for sorting consistency
        from datetime import datetime, time, timezone as dt_timezone
        payment_dt = timezone.make_aware(datetime.combine(p.payment_date, time.min))
        ledger.append({
            'type': 'CREDIT',
            'date': payment_dt,
            'amount': p.amount,
            'reference': p.reference or p.payment_mode,
            'notes': p.notes,
            'id': p.id
        })
    
    ledger.sort(key=lambda x: x['date'], reverse=True)
    
    return render(request, 'customers/partials/payment_history_modal.html', {
        'customer': customer,
        'ledger': ledger
    })

@login_required
def update_payment(request, pk):
    payment = get_object_or_404(CustomerPayment, pk=pk)
    customer = payment.customer
    if request.method == 'POST':
        form = CustomerPaymentForm(request.POST, instance=payment)
        if form.is_valid():
            form.save() # Signal handles balance recalculation
            if request.headers.get('HX-Request'):
                return _render_customer_list_response(request, "Payment updated successfully")
            return redirect('customers:list')
    else:
        form = CustomerPaymentForm(instance=payment)
    
    return render(request, 'customers/partials/payment_form_modal.html', {
        'form': form,
        'customer': customer,
        'payment': payment,
        'title': 'Edit Customer Payment'
    })

@login_required
def delete_payment(request, pk):
    payment = get_object_or_404(CustomerPayment, pk=pk)
    customer = payment.customer
    if request.method == 'POST':
        payment.delete() # Signal handles balance recalculation
        if request.headers.get('HX-Request'):
            return _render_customer_list_response(request, "Payment deleted")
        return redirect('customers:list')
    
    return render(request, 'customers/partials/confirm_delete_payment_modal.html', {
        'payment': payment,
        'customer': customer
    })

