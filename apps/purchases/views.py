from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Purchase, PurchaseItem
from .forms import PurchaseForm, PurchaseItemFormSet
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.template.defaultfilters import floatformat
from decimal import Decimal

from core.decorators import admin_only
from inventory.models import StockMovement

@login_required
@admin_only
def list(request):
    purchases = Purchase.objects.all().order_by('-created_at')
    return render(request, 'purchases/index.html', {'purchases': purchases})


def _reduce_stock(drug, qty, batch_number='', expiry_date=None):
    """Remove up to ``qty`` units from a drug's batches; never goes negative.

    Prefers the batch that this purchase created (matching number + expiry),
    then falls back to the most recently received batches. Returns the number of
    units actually removed (may be less than requested if stock was already sold).
    """
    remaining = qty
    # NB: this module defines a view named ``list`` which shadows the builtin,
    # so build sequences with comprehensions/unpacking instead of ``list()``.
    matched = [b for b in drug.batches.filter(
        batch_number=batch_number, expiry_date=expiry_date, quantity__gt=0
    ).order_by('-created_at')]
    matched_pks = {b.pk for b in matched}
    others = [b for b in drug.batches.filter(quantity__gt=0).order_by('-created_at')
              if b.pk not in matched_pks]
    for batch in [*matched, *others]:
        if remaining <= 0:
            break
        take = min(batch.quantity, remaining)
        batch.quantity -= take
        batch.save()
        remaining -= take
    return qty - remaining


@login_required
@admin_only
@transaction.atomic
def return_purchase(request, pk):
    """Return some (or all) items of a purchase to the supplier; removes stock."""
    purchase = get_object_or_404(Purchase, pk=pk)

    if request.method == 'POST':
        returned_count = 0
        returned_value = Decimal('0.00')
        for item in purchase.items.all():
            try:
                qty = int(request.POST.get(f'return_qty_{item.id}', 0) or 0)
            except (ValueError, TypeError):
                qty = 0
            qty = max(0, min(qty, item.returnable_quantity))
            if qty == 0:
                continue

            removed = _reduce_stock(item.drug, qty, item.batch_number, item.expiry_date)
            if removed == 0:
                continue  # nothing left in stock to return

            item.returned_quantity += removed
            item.save()
            returned_value += item.purchase_price * removed
            returned_count += removed

            StockMovement.objects.create(
                drug=item.drug, movement_type='RETURN', quantity=removed,
                reference_id=f"RET-PUR-{purchase.id}", user=request.user,
                notes=f"Returned to supplier (Purchase {purchase.invoice_number})",
            )

        if returned_count == 0:
            messages.error(request, "Select at least one item quantity to return (and ensure it's still in stock).")
            return render(request, 'purchases/partials/purchase_return_modal.html', {'purchase': purchase})

        # Recalculate supplier balance net of returns.
        supplier = purchase.supplier
        total_purchases = sum(
            (p.net_amount for p in Purchase.objects.filter(supplier=supplier).prefetch_related('items')),
            Decimal('0.00'),
        )
        from suppliers.models import Supplier, SupplierPayment
        total_payments = SupplierPayment.objects.filter(supplier=supplier).aggregate(
            Sum('amount'))['amount__sum'] or Decimal('0.00')
        Supplier.objects.filter(pk=supplier.pk).update(balance=total_purchases - total_payments)

        messages.success(
            request,
            f"Returned {returned_count} item(s) to supplier (SDG {floatformat(returned_value, 0)}).",
        )
        response = render(request, 'transactions/partials/purchase_detail_modal.html',
                          {'purchase': purchase, 'return_done': True})
        response['HX-Trigger'] = 'refreshTransactions'
        return response

    return render(request, 'purchases/partials/purchase_return_modal.html', {'purchase': purchase})

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
