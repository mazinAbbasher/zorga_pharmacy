from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Supplier, SupplierPayment
from .forms import SupplierForm, SupplierPaymentForm
from django.contrib import messages
from core.decorators import admin_only
from django.http import HttpResponse
from django.db.models import Max
from decimal import Decimal
from datetime import datetime
from inventory.models import StockMovement

def _parse_date(value):
    """Parse a ``YYYY-MM-DD`` query-string date, returning None if absent/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def _render_supplier_list_response(request, success_msg=None):
    if success_msg:
        messages.success(request, success_msg)
    response = HttpResponse()
    response['HX-Refresh'] = 'true'
    return response

@login_required
@admin_only
def list(request):
    suppliers = Supplier.objects.all().order_by('name')
    if request.headers.get('HX-Request'):
        return render(request, 'suppliers/partials/supplier_list_rows.html', {'suppliers': suppliers})
    return render(request, 'suppliers/index.html', {'suppliers': suppliers})

@login_required
@admin_only
def create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_supplier_list_response(request, "Supplier created successfully")
            messages.success(request, "Supplier added successfully.")
            return redirect('suppliers:list')
    else:
        form = SupplierForm()
    
    if request.headers.get('HX-Request'):
        return render(request, 'suppliers/partials/supplier_form_modal.html', {
            'form': form, 
            'title': 'Register New Supplier',
            'button_text': 'Create Supplier'
        })
    return render(request, 'suppliers/form.html', {'form': form, 'title': 'Add Supplier'})

@login_required
@admin_only
def update(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierForm(request.POST, instance=supplier)
        if form.is_valid():
            form.save()
            if request.headers.get('HX-Request'):
                return _render_supplier_list_response(request, "Supplier updated successfully")
            messages.success(request, "Supplier updated successfully.")
            return redirect('suppliers:list')
    else:
        form = SupplierForm(instance=supplier)
    
    if request.headers.get('HX-Request'):
        return render(request, 'suppliers/partials/supplier_form_modal.html', {
            'form': form, 
            'title': 'Edit Supplier Profile',
            'button_text': 'Update Supplier',
            'supplier': supplier
        })
    return render(request, 'suppliers/form.html', {'form': form, 'title': 'Edit Supplier'})

from django.db.models import ProtectedError

@login_required
@admin_only
def delete(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        try:
            supplier.delete()
        except ProtectedError:
            messages.error(request, "Cannot delete supplier: They have associated purchases or transactions.")
            if request.headers.get('HX-Request'):
                return _render_supplier_list_response(request)
            return redirect('suppliers:list')
            
        if request.headers.get('HX-Request'):
            return _render_supplier_list_response(request, "Supplier deleted successfully")
        messages.success(request, "Supplier deleted.")
        return redirect('suppliers:list')
    
    if request.headers.get('HX-Request'):
        return render(request, 'suppliers/partials/confirm_delete_modal.html', {'supplier': supplier})
    return render(request, 'suppliers/confirm_delete.html', {'supplier': supplier})

@login_required
@admin_only
def record_payment(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.supplier = supplier
            payment.save()  # Signal handles balance update
            if request.headers.get('HX-Request'):
                return _render_supplier_list_response(request, "Payment recorded successfully")
            return redirect('suppliers:list')
    else:
        form = SupplierPaymentForm()
    
    return render(request, 'suppliers/partials/payment_form_modal.html', {
        'form': form,
        'supplier': supplier,
        'title': 'Record Supplier Payment'
    })

@login_required
@admin_only
def statement(request, pk):
    """Full supplier Statement of Account: a chronological accounting ledger of
    every purchase (debit/charge), return and payment (credit) with a running
    payable balance, plus a totals footer.

    Debit/credit follow the standard statement-of-account convention:
        Debit  = charges  = purchase invoices        (increase what we owe)
        Credit = payments = supplier payments + returns/credit notes
    The running balance therefore reconciles exactly with
    ``recalculate_supplier_balance``:
        balance = Σ debit − Σ credit
                = Σ purchase.total_amount − Σ returned_amount − Σ payments
                = Σ purchase.net_amount − Σ payments = supplier.balance
    """
    supplier = get_object_or_404(Supplier, pk=pk)
    # NB: this module defines a view named ``list``, shadowing the builtin, so
    # materialise querysets with comprehensions rather than ``list(...)``.
    purchases = [p for p in supplier.purchases.all().prefetch_related('items')]
    payments = [pay for pay in supplier.payments.all()]

    # When each purchase's items were last returned to the supplier, so returns
    # land at the right point on the timeline rather than the invoice date.
    return_dates = {}
    ret_refs = [f"RET-PUR-{p.id}" for p in purchases]
    if ret_refs:
        return_dates = dict(
            StockMovement.objects.filter(reference_id__in=ret_refs)
            .values_list('reference_id').annotate(last=Max('timestamp'))
        )

    # Totals are computed per selected period further down, so the loops here
    # only build the (all-time) ledger entries.
    entries = []

    for p in purchases:
        items = p.items.all()
        n_products = len(items)
        n_units = sum((it.quantity for it in items), 0)
        entries.append({
            'sort': (p.purchase_date, 0, p.id),
            'date': p.purchase_date,
            'kind': 'purchase',
            'type_label': 'Purchase',
            'ref': f'Invoice #{p.invoice_number}',
            'detail': f'{n_products} product{"" if n_products == 1 else "s"} · '
                      f'{n_units} unit{"" if n_units == 1 else "s"}',
            'debit': p.total_amount,
            'credit': None,
            'delta': p.total_amount,
        })
        returned = p.returned_amount
        if returned > 0:
            last_return = return_dates.get(f"RET-PUR-{p.id}")
            r_date = last_return.date() if last_return else p.purchase_date
            entries.append({
                'sort': (r_date, 1, p.id),
                'date': r_date,
                'kind': 'return',
                'type_label': 'Credit Note',
                'ref': f'Return · Invoice #{p.invoice_number}',
                'detail': 'Items returned to supplier',
                'debit': None,
                'credit': returned,
                'delta': -returned,
            })

    for pay in payments:
        entries.append({
            'sort': (pay.payment_date, 2, pay.id),
            'date': pay.payment_date,
            'kind': 'payment',
            'type_label': 'Payment',
            'ref': pay.get_payment_mode_display() + (f' · {pay.reference}' if pay.reference else ''),
            'detail': pay.notes,
            'debit': None,
            'credit': pay.amount,
            'delta': -pay.amount,
            'payment': pay,                   # enables inline edit/delete
        })

    # Chronological (oldest -> newest) so the running balance builds up to the
    # current outstanding at the bottom, the way a statement of account reads.
    entries.sort(key=lambda e: e['sort'])
    running = Decimal('0.00')
    for e in entries:
        running += e['delta']
        e['balance'] = running

    # Optional From–To filter. Anything dated before ``start_date`` is rolled up
    # into an "opening balance" carried forward, so the running balance stays
    # coherent inside a narrowed period (proper statement-of-account behaviour).
    start_date = _parse_date(request.GET.get('start_date'))
    end_date = _parse_date(request.GET.get('end_date'))

    opening_balance = Decimal('0.00')
    rows = []
    for e in entries:
        if start_date and e['date'] < start_date:
            opening_balance = e['balance']
            continue
        if end_date and e['date'] > end_date:
            continue
        rows.append(e)

    # Totals scoped to what's actually shown (the selected period).
    period_debit = sum((e['debit'] for e in rows if e['debit']), Decimal('0.00'))
    period_returned = sum((e['credit'] for e in rows if e['kind'] == 'return'), Decimal('0.00'))
    period_paid = sum((e['credit'] for e in rows if e['kind'] == 'payment'), Decimal('0.00'))
    period_credit = period_returned + period_paid
    closing_balance = rows[-1]['balance'] if rows else opening_balance

    return render(request, 'suppliers/statement.html', {
        'supplier': supplier,
        'entries': rows,
        'invoice_count': len(purchases),        # all-time profile stat
        'total_transactions': len(entries),     # all-time profile stat
        'total_debit': period_debit,            # Σ charges in period
        'total_credit': period_credit,          # Σ payments + returns in period
        'total_paid': period_paid,
        'total_returned': period_returned,
        'net_purchased': period_debit - period_returned,
        'opening_balance': opening_balance,
        'closing_balance': closing_balance,
        'show_opening': bool(start_date),       # explicit period start => carry-forward row
        'start_date': start_date,
        'end_date': end_date,
        'has_filter': bool(start_date or end_date),
    })

@login_required
@admin_only
def update_payment(request, pk):
    payment = get_object_or_404(SupplierPayment, pk=pk)
    supplier = payment.supplier
    if request.method == 'POST':
        form = SupplierPaymentForm(request.POST, instance=payment)
        if form.is_valid():
            form.save()  # Signal handles balance sync
            if request.headers.get('HX-Request'):
                return _render_supplier_list_response(request, "Payment updated successfully")
            return redirect('suppliers:list')
    else:
        form = SupplierPaymentForm(instance=payment)
    
    return render(request, 'suppliers/partials/payment_form_modal.html', {
        'form': form,
        'supplier': supplier,
        'payment': payment,
        'title': 'Edit Supplier Payment'
    })

@login_required
@admin_only
def delete_payment(request, pk):
    payment = get_object_or_404(SupplierPayment, pk=pk)
    supplier = payment.supplier
    if request.method == 'POST':
        payment.delete()  # Signal handles balance sync
        if request.headers.get('HX-Request'):
            return _render_supplier_list_response(request, "Payment removed")
        return redirect('suppliers:list')
    
    return render(request, 'suppliers/partials/confirm_delete_payment_modal.html', {
        'payment': payment,
        'supplier': supplier
    })





