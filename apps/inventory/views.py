from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from drugs.models import Drug
from .models import StockMovement
from django.utils import timezone
from datetime import timedelta
from django.db.models import Sum, Q, Count, F

from core.decorators import pharmacist_or_admin

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
