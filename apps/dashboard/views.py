from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from pos.models import Sale
from drugs.models import Drug
from django.db.models import Sum, F
from django.utils import timezone
from datetime import timedelta


@login_required
def index(request):
    today = timezone.now().date()
    start_of_month = today.replace(day=1)
    
    # Stats (Excluding Refunds)
    sales_qs = Sale.objects.filter(is_refunded=False)
    daily_sales = sales_qs.filter(timestamp__date=today).aggregate(
        total=Sum(F('total_amount') - F('discount'))
    )['total'] or 0
    monthly_sales = sales_qs.filter(timestamp__date__gte=start_of_month).aggregate(
        total=Sum(F('total_amount') - F('discount'))
    )['total'] or 0
    
    # Filter drugs where the sum of their batch quantities is <= minimum_stock_alert
    drugs_with_stock = Drug.objects.annotate(total_stock=Sum('batches__quantity'))
    low_stock_count = drugs_with_stock.filter(total_stock__lte=F('minimum_stock_alert')).count()
    
    near_expiry_date = today + timedelta(days=30)
    # Count drugs that have at least one batch expiring soon
    from drugs.models import Batch
    expiring_soon_count = Batch.objects.filter(
        expiry_date__lte=near_expiry_date, 
        expiry_date__gte=today,
        quantity__gt=0
    ).values('drug').distinct().count()
    
    recent_sales = Sale.objects.all().order_by('-timestamp')[:10]
    
    context = {
        'daily_sales': daily_sales,
        'monthly_sales': monthly_sales,
        'low_stock_count': low_stock_count,
        'expiring_soon_count': expiring_soon_count,
        'recent_sales': recent_sales,
    }
    return render(request, 'dashboard/index.html', context)
