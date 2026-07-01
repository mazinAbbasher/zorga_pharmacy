"""Sales analytics.

Single source of truth for sales revenue/cost/profit so the dashboard and the
reports page always agree. Every figure is *net*: fully refunded sales are
excluded, and the value of partially returned items is subtracted (matching the
``total_amount - discount - refunded_amount`` convention used for customer
balances in ``core.signals``).
"""
from decimal import Decimal

from django.db.models import Sum, F, DecimalField

from .models import Sale, SaleItem

ZERO = Decimal('0.00')
_MONEY = DecimalField(max_digits=14, decimal_places=2)


def _gross_revenue(start_date, end_date):
    """Sum of (total - discount) for non-refunded sales in the range."""
    return Sale.objects.filter(
        is_refunded=False,
        timestamp__date__range=[start_date, end_date],
    ).aggregate(
        total=Sum(F('total_amount') - F('discount'))
    )['total'] or ZERO


def _returns_value(start_date, end_date):
    """Revenue and cost embedded in items returned from non-refunded sales."""
    agg = SaleItem.objects.filter(
        sale__is_refunded=False,
        sale__timestamp__date__range=[start_date, end_date],
    ).aggregate(
        revenue=Sum(F('unit_price') * F('returned_quantity'), output_field=_MONEY),
        cost=Sum(F('unit_cost') * F('returned_quantity'), output_field=_MONEY),
    )
    return agg['revenue'] or ZERO, agg['cost'] or ZERO


def net_revenue(start_date, end_date):
    """Net sales revenue (after discounts and partial returns) for the range."""
    returned_revenue, _ = _returns_value(start_date, end_date)
    return _gross_revenue(start_date, end_date) - returned_revenue


def revenue_by_payment_method(start_date, end_date):
    """Net revenue grouped by payment method for the range.

    Same net convention as :func:`net_revenue` — each method's gross
    (total - discount) minus the value of items returned from its sales — so the
    per-method figures sum to the range's overall net revenue.
    """
    gross = dict(
        Sale.objects.filter(
            is_refunded=False,
            timestamp__date__range=[start_date, end_date],
        )
        .values_list('payment_method')
        .annotate(total=Sum(F('total_amount') - F('discount')))
    )
    returns = dict(
        SaleItem.objects.filter(
            sale__is_refunded=False,
            sale__timestamp__date__range=[start_date, end_date],
        )
        .values_list('sale__payment_method')
        .annotate(total=Sum(F('unit_price') * F('returned_quantity'), output_field=_MONEY))
    )
    return {
        method: (gross.get(method) or ZERO) - (returns.get(method) or ZERO)
        for method in set(gross) | set(returns)
    }


def sales_summary(start_date, end_date):
    """Revenue, cost, profit and margin for non-refunded sales in the range,
    consistently net of discounts and partially returned items."""
    gross_cost = SaleItem.objects.filter(
        sale__is_refunded=False,
        sale__timestamp__date__range=[start_date, end_date],
    ).aggregate(total=Sum('total_cost'))['total'] or ZERO

    returned_revenue, returned_cost = _returns_value(start_date, end_date)

    revenue = _gross_revenue(start_date, end_date) - returned_revenue
    cost = gross_cost - returned_cost
    profit = revenue - cost
    margin = (profit / revenue * 100) if revenue > 0 else ZERO

    return {'revenue': revenue, 'cost': cost, 'profit': profit, 'margin': margin}
