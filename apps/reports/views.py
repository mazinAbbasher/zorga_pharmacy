from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from pos.models import Sale, SaleItem
from pos.analytics import sales_summary, net_revenue
from drugs.models import Drug
from django.db.models import Sum, F, Q, DecimalField, ExpressionWrapper
from django.utils import timezone
from datetime import timedelta
from core.decorators import admin_only, pharmacist_or_admin

@login_required
@admin_only
def index(request):
    today = timezone.now().date()
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    
    if start_date_str:
        try:
            start_date = timezone.datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            start_date = today - timedelta(days=30)
    else:
        start_date = today - timedelta(days=30)
        
    if end_date_str:
        try:
            end_date = timezone.datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            end_date = today
    else:
        end_date = today
    
    # Sales Trend (Daily for last 7 days - NOT linked to filter range, but for dashboard context)
    # Net of discounts and partial returns, fully refunded sales excluded.
    sales_trend = []
    for i in range(7):
        date = today - timedelta(days=i)
        sales_trend.append({'date': date, 'amount': net_revenue(date, date)})

    # Top Selling Drugs (respects date range, excludes refunds, net of returns)
    net_qty = F('quantity') - F('returned_quantity')
    top_selling = SaleItem.objects.filter(
        sale__is_refunded=False,
        sale__timestamp__date__range=[start_date, end_date]
    ).values('drug__trade_name')\
    .annotate(
        total_qty=Sum(net_qty),
        total_revenue=Sum(
            F('unit_price') * net_qty,
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )\
    .filter(total_qty__gt=0)\
    .order_by('-total_qty')[:10]

    # Main Metrics — net of discounts and partial returns (single source of truth).
    summary = sales_summary(start_date, end_date)
    total_revenue = summary['revenue']
    net_profit = summary['profit']
    profit_margin = summary['margin']

    context = {
        'sales_trend': sales_trend,
        'top_selling': top_selling,
        'total_revenue': total_revenue,
        'net_profit': net_profit,
        'profit_margin': profit_margin,
        'today': today,
        'start_date': start_date,
        'end_date': end_date,
    }
    return render(request, 'reports/index.html', context)

@login_required
@admin_only
def dead_stock(request):
    query = request.GET.get('q', '')
    from django.db.models import Q
    three_months_ago = timezone.now() - timedelta(days=90)
    # Drugs not in any SaleItem since three_months_ago
    sold_drug_ids = SaleItem.objects.filter(sale__timestamp__gte=three_months_ago).values_list('drug_id', flat=True).distinct()

    # Get all drugs that have NOT been sold in last 90 days
    dead_drugs = Drug.objects.exclude(id__in=sold_drug_ids)
    
    if query:
        dead_drugs = dead_drugs.filter(
            Q(trade_name__icontains=query) | Q(scientific_name__icontains=query)
        )
        
    return render(request, 'reports/dead_stock.html', {'drugs': dead_drugs, 'query': query})

@login_required
@admin_only
def loss_report(request):
    query = request.GET.get('q', '')
    # Loss can be from expired drugs or manually logged adjustments
    # Let's count drugs that have expired
    from drugs.models import Batch
    from django.db.models import Q
    today = timezone.now().date()
    expired_batches = Batch.objects.filter(expiry_date__lt=today, quantity__gt=0)
    
    if query:
        expired_batches = expired_batches.filter(
            Q(drug__trade_name__icontains=query) | Q(batch_number__icontains=query)
        )
        
    for batch in expired_batches:
        batch.total_loss = batch.quantity * batch.purchase_price
        
    total_loss_value = sum(b.total_loss for b in expired_batches)
    
    return render(request, 'reports/loss_report.html', {
        'expired_batches': expired_batches,
        'total_loss_value': total_loss_value,
        'query': query
    })

@login_required
@admin_only
def stock_valuation(request):
    """Available-stock valuation: every in-stock, non-expired batch with its
    line value (quantity x buy price), plus the grand total of stock on hand.

    Uses the live ``Batch.purchase_price`` (current cost), so the figure matches
    the dashboard's inventory valuation and reflects any buy-price revaluation.
    """
    from drugs.models import Batch
    query = request.GET.get('q', '')
    today = timezone.now().date()
    near_expiry_date = today + timedelta(days=30)

    line_total = ExpressionWrapper(
        F('quantity') * F('purchase_price'),
        output_field=DecimalField(max_digits=16, decimal_places=2),
    )

    # "Available" = on hand (qty > 0) and not expired (FIFO null-expiry counts).
    # Within a drug, nearest expiry first so soon-to-expire stock stands out.
    batches = (
        Batch.objects.filter(Drug._not_expired(today), quantity__gt=0)
        .select_related('drug')
        .annotate(line_total=line_total)
        .order_by('drug__trade_name', 'expiry_date', 'batch_number')
    )
    if query:
        batches = batches.filter(
            Q(drug__trade_name__icontains=query)
            | Q(drug__scientific_name__icontains=query)
            | Q(batch_number__icontains=query)
        )

    totals = batches.aggregate(
        total_value=Sum(line_total),
        total_units=Sum('quantity'),
    )

    return render(request, 'reports/stock_valuation.html', {
        'batches': batches,
        'total_value': totals['total_value'] or 0,
        'total_units': totals['total_units'] or 0,
        'batch_count': batches.count(),
        'query': query,
        'today': today,
        'near_expiry_date': near_expiry_date,
    })
