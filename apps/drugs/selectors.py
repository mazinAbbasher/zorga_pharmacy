"""Shared inventory queries.

Single source of truth for "low stock" and "expiring soon" so the dashboard
and inventory pages always report the same numbers (and those numbers match
the per-row badges, which use the model properties).
"""
from datetime import timedelta

from django.db.models import Sum, F, Q, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from .models import Drug, Batch


def restock_needed_drugs(today=None):
    """Drugs that need restocking: sellable (non-expired) stock at or below the
    alert threshold. Includes out-of-stock items (zero / all-expired stock).

    Mirrors ``Drug.needs_restock`` exactly, so ``restock_needed_drugs().count()``
    equals the number of RESTOCK / OUT OF STOCK rows shown on the inventory page.
    """
    today = today or timezone.now().date()
    not_expired = Q(batches__expiry_date__gte=today) | Q(batches__expiry_date__isnull=True)
    return (
        Drug.objects.annotate(
            sellable_stock=Coalesce(Sum('batches__quantity', filter=not_expired), Value(0))
        )
        .filter(sellable_stock__lte=F('minimum_stock_alert'))
    )


def expiring_soon_batches(days=30, today=None):
    """Batches with stock that expire within ``days`` (and aren't already expired)."""
    today = today or timezone.now().date()
    return Batch.objects.filter(
        expiry_date__gte=today,
        expiry_date__lte=today + timedelta(days=days),
        quantity__gt=0,
    )


def expiring_soon_count(days=30, today=None):
    """Number of distinct drugs with at least one batch expiring soon."""
    return expiring_soon_batches(days=days, today=today).values('drug').distinct().count()
