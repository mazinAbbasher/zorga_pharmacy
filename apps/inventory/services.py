"""Stock-mutation services that keep the movement ledger complete.

Every function here changes on-hand stock (Batch quantities) *and* writes the
matching StockMovement in the same transaction, so the ledger invariant holds:

    sum(signed movements) == sum(all batch quantities, including expired)

These two operations activate the previously-unused ``ADJUSTMENT`` and
``EXPIRED`` movement types. They mirror the proven batch logic already used by
``_restore_stock`` (pos) and ``_reduce_stock`` (purchases) without refactoring
those callers.
"""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from drugs.models import Drug, Batch
from .models import StockMovement


@transaction.atomic
def write_off_expired(drug, user, reason=''):
    """Zero out every expired batch and log a single EXPIRED movement.

    Sellable stock (``Drug.total_quantity``) already excludes expired batches,
    so this doesn't change what's sellable — it records the loss on the ledger
    and clears the dead units. Returns the number of units written off (0 when
    there is nothing expired).
    """
    today = timezone.now().date()
    expired = [b for b in drug.batches.filter(expiry_date__lt=today, quantity__gt=0)]
    total = sum(b.quantity for b in expired)
    if total <= 0:
        return 0

    for batch in expired:
        batch.quantity = 0
        batch.save()

    StockMovement.objects.create(
        drug=drug,
        movement_type='EXPIRED',
        quantity=total,  # magnitude; signed_quantity resolves to negative
        reference_id=f"EXP-{drug.id}-{today:%Y%m%d}",
        user=user,
        notes=reason or f"Expired stock written off ({total} units)",
    )
    return total


@transaction.atomic
def adjust_stock(drug, counted_qty, user, reason):
    """Reconcile a drug's active (non-expired) on-hand stock to ``counted_qty``.

    This is the stock-take / correction path (miscount, breakage, theft, found
    stock). Computes ``delta = counted_qty - current active on-hand`` and:

    * delta > 0 — adds to the newest non-expired batch, or creates one (priced
      from the drug's current buy/sale price) when none exists.
    * delta < 0 — removes from active batches in dispense order (FEFO/FIFO),
      never below zero.

    Logs one ADJUSTMENT movement carrying the *signed* delta, then returns it.
    A no-op (delta == 0, or nothing removable) writes no movement and returns 0.
    """
    current = drug.total_quantity  # active, non-expired (the count staff verify)
    delta = counted_qty - current
    if delta == 0:
        return 0

    today = timezone.now().date()

    if delta > 0:
        batch = (
            drug.batches.filter(Drug._not_expired(today))
            .order_by('-created_at')
            .first()
        )
        if batch:
            batch.quantity += delta
            batch.save()
        else:
            # No live batch to grow — open a fresh, non-perishable one at the
            # product's current prices so the added units are immediately valued.
            Batch.objects.create(
                drug=drug,
                batch_number='',
                quantity=delta,
                purchase_price=drug.current_buy_price or Decimal('0.00'),
                selling_price=drug.current_price or Decimal('0.01'),
                expiry_date=None,
            )
    else:
        remaining = -delta
        for batch in drug.active_batches():
            if remaining <= 0:
                break
            take = min(batch.quantity, remaining)
            batch.quantity -= take
            batch.save()
            remaining -= take
        # Cap the recorded delta at what was actually removable.
        delta = -((-delta) - remaining)
        if delta == 0:
            return 0

    StockMovement.objects.create(
        drug=drug,
        movement_type='ADJUSTMENT',
        quantity=delta,  # signed: positive adds, negative removes
        reference_id=f"ADJ-{drug.id}-{today:%Y%m%d}",
        user=user,
        notes=reason,
    )
    return delta
