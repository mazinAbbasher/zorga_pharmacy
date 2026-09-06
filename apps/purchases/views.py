from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Purchase, PurchaseItem
from .forms import PurchaseForm, PurchaseItemFormSet
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.template.defaultfilters import floatformat
from decimal import Decimal

from core.decorators import admin_only
from inventory.models import StockMovement

@login_required
@admin_only
def list(request):
    query = request.GET.get('q', '')
    purchases = Purchase.objects.all().order_by('-created_at')
    if query:
        # Search by invoice, supplier, or by any drug contained in the
        # purchase (trade or scientific name). The item join can match a
        # purchase more than once, so distinct() collapses the duplicates.
        purchases = purchases.filter(
            Q(invoice_number__icontains=query) |
            Q(supplier__name__icontains=query) |
            Q(items__drug__trade_name__icontains=query) |
            Q(items__drug__scientific_name__icontains=query)
        ).distinct()

    if request.headers.get('HX-Request'):
        return render(request, 'purchases/partials/purchase_rows.html', {'purchases': purchases})

    return render(request, 'purchases/index.html', {'purchases': purchases, 'query': query})


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
        from core.signals import recalculate_supplier_balance
        recalculate_supplier_balance(purchase.supplier)

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
        'is_edit': False,
    })


@login_required
@admin_only
@transaction.atomic
def edit(request, pk):
    """Edit a purchase's header (always) and product lines (only if nothing
    on it has been returned yet).

    Line items are locked once any item has a recorded return because there's
    no reliable link from a PurchaseItem back to the exact Batch it created —
    editing quantities on top of a return could silently corrupt stock. When
    editing is allowed, changed/removed lines reverse their stock contribution
    with the same safe, capped helper the supplier-return flow uses
    (``_reduce_stock``), then a fresh batch is created for the new quantity,
    mirroring how ``create`` always creates a new batch per line.
    """
    purchase = get_object_or_404(Purchase, pk=pk)
    can_edit_items = not purchase.items.filter(returned_quantity__gt=0).exists()
    # Snapshot pre-edit item state now, before the formset (constructed below)
    # mutates its own in-memory copies of these rows.
    original_items = {item.pk: item for item in purchase.items.all()}
    old_supplier_id = purchase.supplier_id

    if request.method == 'POST':
        p_form = PurchaseForm(request.POST, instance=purchase)
        formset = PurchaseItemFormSet(request.POST, instance=purchase, prefix='items') if can_edit_items else None

        items_ok = True
        if formset is not None:
            if formset.is_valid():
                remaining = [
                    f for f in formset
                    if f.cleaned_data and not f.cleaned_data.get('DELETE')
                ]
                if not remaining:
                    items_ok = False
                    messages.error(request, "A purchase must keep at least one product line.")
            else:
                items_ok = False

        if p_form.is_valid() and items_ok:
            purchase = p_form.save()
            notices = []

            if formset is not None:
                from drugs.models import Batch
                # Populates new_objects / changed_objects / deleted_objects
                # without touching the DB yet.
                formset.save(commit=False)

                for obj in formset.deleted_objects:
                    removed = _reduce_stock(obj.drug, obj.returnable_quantity, obj.batch_number, obj.expiry_date)
                    if removed:
                        StockMovement.objects.create(
                            drug=obj.drug, movement_type='ADJUSTMENT', quantity=-removed,
                            reference_id=f"PUR-{purchase.id}", user=request.user,
                            notes=f"Line removed while editing purchase (Invoice #{purchase.invoice_number})",
                        )
                    if removed < obj.returnable_quantity:
                        notices.append(
                            f"{obj.drug.trade_name}: only {removed} of {obj.returnable_quantity} unit(s) were "
                            "still in stock, so only that much could be removed."
                        )
                    obj.delete()

                for obj, _changed_fields in formset.changed_objects:
                    original = original_items[obj.pk]
                    removed = _reduce_stock(
                        original.drug, original.returnable_quantity,
                        original.batch_number, original.expiry_date,
                    )
                    if removed:
                        StockMovement.objects.create(
                            drug=original.drug, movement_type='ADJUSTMENT', quantity=-removed,
                            reference_id=f"PUR-{purchase.id}", user=request.user,
                            notes=f"Line edited (Invoice #{purchase.invoice_number})",
                        )
                    if removed < original.returnable_quantity:
                        notices.append(
                            f"{original.drug.trade_name}: only {removed} of {original.returnable_quantity} "
                            "original unit(s) were still in stock, so the adjustment reflects that."
                        )
                    obj.save()
                    Batch.objects.create(
                        drug=obj.drug, batch_number=obj.batch_number,
                        purchase_price=obj.purchase_price, selling_price=obj.selling_price,
                        quantity=obj.quantity, expiry_date=obj.expiry_date,
                    )
                    StockMovement.objects.create(
                        drug=obj.drug, movement_type='ADJUSTMENT', quantity=obj.quantity,
                        reference_id=f"PUR-{purchase.id}", user=request.user,
                        notes=f"Line edited (Invoice #{purchase.invoice_number})",
                    )

                for obj in formset.new_objects:
                    obj.save()  # created=True -> signal logs the IN movement
                    Batch.objects.create(
                        drug=obj.drug, batch_number=obj.batch_number,
                        purchase_price=obj.purchase_price, selling_price=obj.selling_price,
                        quantity=obj.quantity, expiry_date=obj.expiry_date,
                    )

                purchase.total_amount = sum(
                    (item.total_price for item in purchase.items.all()), Decimal('0.00')
                )
                purchase.save()

            if old_supplier_id != purchase.supplier_id:
                from suppliers.models import Supplier
                from core.signals import recalculate_supplier_balance
                recalculate_supplier_balance(Supplier.objects.get(pk=old_supplier_id))

            for notice in notices:
                messages.warning(request, notice)
            messages.success(request, "Purchase updated.")
            return redirect('purchases:list')
    else:
        p_form = PurchaseForm(instance=purchase)
        formset = PurchaseItemFormSet(instance=purchase, prefix='items') if can_edit_items else None

    from drugs.models import Drug
    drug_strategies = {
        str(pk): strat for pk, strat in Drug.objects.values_list('id', 'dispensing_strategy')
    }

    return render(request, 'purchases/form.html', {
        'p_form': p_form,
        'formset': formset,
        'purchase': purchase,
        'drug_strategies': drug_strategies,
        'title': 'Edit Purchase',
        'is_edit': True,
        'can_edit_items': can_edit_items,
    })
