from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Purchase, PurchaseItem
from .forms import PurchaseForm, PurchaseItemFormSet
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
        formset = PurchaseItemFormSet(request.POST, prefix='items')

        if p_form.is_valid() and formset.is_valid():
            items = [
                f for f in formset
                if f.cleaned_data and not f.cleaned_data.get('DELETE')
            ]
            if not items:
                messages.error(request, "Add at least one product line to the purchase.")
            else:
                with transaction.atomic():
                    purchase = p_form.save(commit=False)
                    purchase.received_by = request.user
                    purchase.total_amount = Decimal('0.00')
                    purchase.save()

                    from drugs.models import Batch
                    total = Decimal('0.00')
                    for f in items:
                        item = f.save(commit=False)
                        item.purchase = purchase
                        # Batch number handling is enforced in the form:
                        # FEFO -> required, FIFO -> always blank.
                        item.save()  # computes total_price + logs IN movement

                        Batch.objects.create(
                            drug=item.drug,
                            batch_number=item.batch_number,
                            purchase_price=item.purchase_price,
                            selling_price=item.selling_price,
                            quantity=item.quantity,
                            expiry_date=item.expiry_date,
                        )
                        total += item.total_price

                    purchase.total_amount = total
                    purchase.save()

                messages.success(
                    request,
                    f"Purchase recorded: {len(items)} item(s), stock updated.",
                )
                return redirect('purchases:list')
    else:
        p_form = PurchaseForm(initial={'received_by': request.user})
        formset = PurchaseItemFormSet(prefix='items')

    from drugs.models import Drug
    drug_strategies = {
        str(pk): strat for pk, strat in Drug.objects.values_list('id', 'dispensing_strategy')
    }

    return render(request, 'purchases/form.html', {
        'p_form': p_form,
        'formset': formset,
        'drug_strategies': drug_strategies,
        'title': 'New Purchase',
    })
