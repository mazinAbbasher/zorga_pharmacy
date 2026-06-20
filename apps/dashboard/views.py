from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from pos.models import Sale
from pos.analytics import net_revenue
from drugs.selectors import restock_needed_drugs, expiring_soon_count
from django.utils import timezone


@login_required
def index(request):
    today = timezone.now().date()
    start_of_month = today.replace(day=1)

    # Sales, net of discounts and any (partial) returns. Fully refunded sales
    # are excluded by net_revenue.
    daily_sales = net_revenue(today, today)
    monthly_sales = net_revenue(start_of_month, today)

    # Inventory alerts (shared selectors keep these identical to the inventory page).
    low_stock_count = restock_needed_drugs(today).count()
    expiring_soon_count_value = expiring_soon_count(days=30, today=today)

    recent_sales = Sale.objects.all().order_by('-timestamp')[:10]

    context = {
        'daily_sales': daily_sales,
        'monthly_sales': monthly_sales,
        'low_stock_count': low_stock_count,
        'expiring_soon_count': expiring_soon_count_value,
        'recent_sales': recent_sales,
        'today': today,
    }
    return render(request, 'dashboard/index.html', context)
