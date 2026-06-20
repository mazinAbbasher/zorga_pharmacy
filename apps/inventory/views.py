from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import (
    F, Value, DecimalField, ExpressionWrapper,
)
from django.db.models.functions import Round, Greatest
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from drugs.models import Drug, Batch
from drugs.selectors import restock_needed_drugs, expiring_soon_count
from .models import StockMovement
from .forms import BulkPriceUpdateForm

from core.decorators import pharmacist_or_admin, admin_only

@login_required
@pharmacist_or_admin
def index(request):
    today = timezone.now().date()
    near_expiry_date = today + timedelta(days=30)

    # Shared selectors keep these counts identical to the dashboard and to the
    # per-row RESTOCK / expiry badges (non-expired stock only).
    low_stock_count = restock_needed_drugs(today).count()
    expiring_soon_count_value = expiring_soon_count(days=30, today=today)

    drugs = Drug.objects.all().order_by('trade_name')

    context = {
        'drugs': drugs,
        'low_stock_count': low_stock_count,
        'expiring_soon_count': expiring_soon_count_value,
        'today': today,
        'near_expiry_date': near_expiry_date,
    }
    return render(request, 'inventory/index.html', context)

@login_required
def movement_logs(request):
    logs = StockMovement.objects.all().order_by('-timestamp')[:100]
    return render(request, 'inventory/logs.html', {'logs': logs})


# ---------------------------------------------------------------------------
# Bulk price update
# ---------------------------------------------------------------------------

def _preview_context(form):
    """Summary of what an apply would do: counts + a small sample preview."""
    batches = form.get_batches()
    batch_count = batches.count()
    product_count = batches.values('drug').distinct().count()
    factor = form.factor
    price_field = form.price_field
    floor = form.price_floor

    samples = []
    for batch in batches.select_related('drug').order_by('drug__trade_name')[:8]:
        old_price = getattr(batch, price_field)
        new_price = (old_price * factor).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        if new_price < floor:
            new_price = floor
        samples.append({
            'name': batch.drug.trade_name,
            'batch': batch.batch_number,
            'old_price': old_price,
            'new_price': new_price,
        })

    return {
        'form': form,
        'batch_count': batch_count,
        'product_count': product_count,
        'percentage': form.cleaned_data['percentage'],
        'direction': form.cleaned_data['direction'],
        'target': form.cleaned_data.get('target', 'selling'),
        'target_label': form.target_label,
        'samples': samples,
        'extra_count': max(batch_count - len(samples), 0),
        'has_results': batch_count > 0,
        'show_preview': True,
    }


@login_required
@admin_only
def bulk_price_update(request):
    """Page to bulk-increase/decrease sale prices.

    GET renders the form. POST with action=preview returns a confirmation
    panel (HTMX) showing how many products are affected. POST with
    action=apply performs a single efficient UPDATE and redirects (PRG).
    """
    if request.method == 'POST':
        form = BulkPriceUpdateForm(request.POST)
        action = request.POST.get('action')

        if not form.is_valid():
            if request.headers.get('HX-Request') and action == 'preview':
                return render(
                    request, 'inventory/partials/bulk_price_preview.html',
                    {'form': form, 'invalid': True},
                )
            return render(request, 'inventory/bulk_price_update.html', {'form': form})

        if action == 'apply':
            factor = form.factor
            price_field = form.price_field
            floor = form.price_floor
            batches = form.get_batches()
            product_count = batches.values('drug').distinct().count()

            # One database-side UPDATE for the whole set — no per-row loop.
            # Round to 2 dp and never let a price fall below its floor.
            new_price = Round(
                ExpressionWrapper(
                    F(price_field) * Value(factor),
                    output_field=DecimalField(max_digits=14, decimal_places=4),
                ),
                2,
            )
            with transaction.atomic():
                updated = batches.update(
                    **{price_field: Greatest(new_price, Value(floor))},
                    updated_at=timezone.now(),
                )

            verb = 'increased' if form.cleaned_data['direction'] == 'increase' else 'decreased'
            pct = f"{form.cleaned_data['percentage']:.2f}".rstrip('0').rstrip('.')
            messages.success(
                request,
                f"{form.target_label} prices {verb} by {pct}% — "
                f"updated {updated} price record(s) across {product_count} product(s).",
            )
            return redirect('inventory:bulk_price')

        # action == 'preview'
        context = _preview_context(form)
        if request.headers.get('HX-Request'):
            return render(request, 'inventory/partials/bulk_price_preview.html', context)
        return render(request, 'inventory/bulk_price_update.html', context)

    # Preselect Sale/Buy from ?target= so the inventory page can deep-link
    # straight to the buy-price view.
    target = request.GET.get('target')
    initial = {'target': target} if target in ('selling', 'purchase') else None
    form = BulkPriceUpdateForm(initial=initial)
    return render(request, 'inventory/bulk_price_update.html', {'form': form})
