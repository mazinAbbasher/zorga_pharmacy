from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import (
    Sum, Q, Count, F, Value, DecimalField, ExpressionWrapper,
)
from django.db.models.functions import Round, Greatest
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from drugs.models import Drug, Batch
from .models import StockMovement
from .forms import BulkPriceUpdateForm

from core.decorators import pharmacist_or_admin, admin_only

@login_required
@pharmacist_or_admin
def index(request):
    today = timezone.now().date()
    near_expiry_date = today + timedelta(days=30)

    # Batch-aware low stock
    drugs_with_stock = Drug.objects.annotate(total_stock=Sum('batches__quantity'))
    low_stock_count = drugs_with_stock.filter(total_stock__lte=F('minimum_stock_alert')).count()

    # Batch-aware expiring soon
    from drugs.models import Batch
    expiring_soon_count = Batch.objects.filter(
        expiry_date__lte=near_expiry_date,
        expiry_date__gte=today,
        quantity__gt=0
    ).values('drug').distinct().count()

    drugs = Drug.objects.all().order_by('trade_name')

    context = {
        'drugs': drugs,
        'low_stock_count': low_stock_count,
        'expiring_soon_count': expiring_soon_count,
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

    samples = []
    for batch in batches.select_related('drug').order_by('drug__trade_name')[:8]:
        new_price = (batch.selling_price * factor).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP
        )
        if new_price < Decimal('0.01'):
            new_price = Decimal('0.01')
        samples.append({
            'name': batch.drug.trade_name,
            'batch': batch.batch_number,
            'old_price': batch.selling_price,
            'new_price': new_price,
        })

    return {
        'form': form,
        'batch_count': batch_count,
        'product_count': product_count,
        'percentage': form.cleaned_data['percentage'],
        'direction': form.cleaned_data['direction'],
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
            batches = form.get_batches()
            product_count = batches.values('drug').distinct().count()

            # One database-side UPDATE for the whole set — no per-row loop.
            # Round to 2 dp and never let a price fall below the 0.01 floor.
            new_price = Round(
                ExpressionWrapper(
                    F('selling_price') * Value(factor),
                    output_field=DecimalField(max_digits=14, decimal_places=4),
                ),
                2,
            )
            with transaction.atomic():
                updated = batches.update(
                    selling_price=Greatest(new_price, Value(Decimal('0.01'))),
                    updated_at=timezone.now(),
                )

            verb = 'increased' if form.cleaned_data['direction'] == 'increase' else 'decreased'
            messages.success(
                request,
                f"Prices {verb} by {form.cleaned_data['percentage']:g}% — "
                f"updated {updated} price record(s) across {product_count} product(s).",
            )
            return redirect('inventory:bulk_price')

        # action == 'preview'
        context = _preview_context(form)
        if request.headers.get('HX-Request'):
            return render(request, 'inventory/partials/bulk_price_preview.html', context)
        return render(request, 'inventory/bulk_price_update.html', context)

    form = BulkPriceUpdateForm()
    return render(request, 'inventory/bulk_price_update.html', {'form': form})
