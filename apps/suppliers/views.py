from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Supplier, SupplierPayment
from .forms import SupplierForm, SupplierPaymentForm
from django.contrib import messages
from core.decorators import admin_only
from django.http import HttpResponse

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
def payment_history(request, pk):
    supplier = get_object_or_404(Supplier, pk=pk)
    payments = supplier.payments.all().order_by('-payment_date')
    return render(request, 'suppliers/partials/payment_history_modal.html', {
        'supplier': supplier,
        'payments': payments
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





