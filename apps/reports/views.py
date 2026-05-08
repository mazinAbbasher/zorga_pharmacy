from django.shortcuts import render
from django.contrib.auth.decorators import login_required, user_passes_test
from pos.models import Sale, SaleItem
from drugs.models import Drug
from django.db.models import Sum, F, Count
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
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
    
    # Base queryset for non-refunded sales in the selected range
    sales_in_range = Sale.objects.filter(
        is_refunded=False,
        timestamp__date__range=[start_date, end_date]
    )
    
    # Sales Trend (Daily for last 7 days - NOT linked to filter range, but for dashboard context)
    sales_trend = []
    for i in range(7):
        date = today - timedelta(days=i)
        # Consistently exclude refunds here too
        amount = Sale.objects.filter(timestamp__date=date, is_refunded=False).aggregate(
            total=Sum(F('total_amount') - F('discount'))
        )['total'] or Decimal('0.00')
        sales_trend.append({'date': date, 'amount': amount})
    
    # Top Selling Drugs (Now respects date range and excludes refunds)
    top_selling = SaleItem.objects.filter(
        sale__is_refunded=False,
        sale__timestamp__date__range=[start_date, end_date]
    ).values('drug__trade_name')\
    .annotate(total_qty=Sum('quantity'), total_revenue=Sum('total_price'))\
    .order_by('-total_qty')[:10]
        
    # Main Metrics
    total_revenue = sales_in_range.aggregate(
        total=Sum(F('total_amount') - F('discount'))
    )['total'] or Decimal('0.00')
    
    # Calculate costs from SaleItems linked to non-refunded sales in range
    non_refunded_sales_items = SaleItem.objects.filter(
        sale__is_refunded=False,
        sale__timestamp__date__range=[start_date, end_date]
    )
    total_cost = non_refunded_sales_items.aggregate(total=Sum('total_cost'))['total'] or Decimal('0.00')
    
    net_profit = total_revenue - total_cost
    profit_margin = (net_profit / total_revenue * 100) if total_revenue > 0 else 0

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
    three_months_ago = timezone.now() - timedelta(days=90)
    # Drugs not in any SaleItem since three_months_ago
    sold_drug_ids = SaleItem.objects.filter(sale__timestamp__gte=three_months_ago).values_list('drug_id', flat=True).distinct()
    from django.db.models import Sum, Q
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
