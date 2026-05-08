from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Purchase, PurchaseItem
from .forms import PurchaseForm, PurchaseItemForm
from django.contrib import messages
from django.db import transaction
from decimal import Decimal

from core.decorators import admin_only

@login_required
@admin_only
def list(request):
    purchases = Purchase.objects.all().order_by('-created_at')
    return render(request, 'purchases/index.html', {'purchases': purchases})

@login_required
@admin_only
def create(request):
    if request.method == 'POST':
        p_form = PurchaseForm(request.POST)
        pi_form = PurchaseItemForm(request.POST)
        
        if p_form.is_valid() and pi_form.is_valid():
            with transaction.atomic():
                purchase = p_form.save(commit=False)
                purchase.received_by = request.user
                
                # Pre-calculate total amount so signal picks it up on first save
                qty = pi_form.cleaned_data.get('quantity', 0)
                buy_price = pi_form.cleaned_data.get('purchase_price', 0)
                purchase.total_amount = Decimal(str(qty)) * Decimal(str(buy_price))
                purchase.save()
                
                item = pi_form.save(commit=False)
                item.purchase = purchase
                item.save()

                # Create Batch record
                from drugs.models import Batch
                Batch.objects.create(
                    drug=item.drug,
                    batch_number=item.batch_number,
                    purchase_price=item.purchase_price,
                    selling_price=item.selling_price,
                    quantity=item.quantity,
                    expiry_date=item.expiry_date
                )
                
            messages.success(request, "Purchase recorded and stock updated.")
            return redirect('purchases:list')
    else:
        p_form = PurchaseForm(initial={'received_by': request.user})
        pi_form = PurchaseItemForm()
        
    return render(request, 'purchases/form.html', {
        'p_form': p_form,
        'pi_form': pi_form,
        'title': 'New Purchase'
    })
