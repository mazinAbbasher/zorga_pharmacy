from django.db import models
from django.conf import settings
from drugs.models import Drug
from django.utils import timezone
from decimal import Decimal

class Sale(models.Model):
    # Only two payment methods are offered at checkout (see ACTIVE_PAYMENT_METHODS).
    # 'CARD' and 'CREDIT' are retired: they can no longer be selected for new
    # sales, but remain in the choices so get_payment_method_display() still
    # renders any historical rows that used them with a readable label.
    PAYMENT_METHODS = (
        ('CASH', 'Cash'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('CARD', 'Card'),
        ('CREDIT', 'Customer Credit'),
    )

    # The single source of truth for the methods a cashier may pick.
    ACTIVE_PAYMENT_METHODS = ('CASH', 'BANK_TRANSFER')

    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    customer = models.ForeignKey('customers.Customer', on_delete=models.SET_NULL, null=True, blank=True, related_name='sales')
    timestamp = models.DateTimeField(default=timezone.now)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='CASH')
    is_refunded = models.BooleanField(default=False)
    refund_timestamp = models.DateTimeField(null=True, blank=True)

    @property
    def final_amount(self):
        # Compatibility property for templates
        return self.total_amount - self.discount

    @property
    def refunded_amount(self):
        """Gross value of items returned from this sale."""
        return sum(
            (item.unit_price * item.returned_quantity for item in self.items.all()),
            Decimal('0.00'),
        )

    @property
    def is_partially_refunded(self):
        return not self.is_refunded and self.refunded_amount > 0

    @property
    def net_amount(self):
        """Amount the sale is still worth after returns (before discount)."""
        return self.total_amount - self.refunded_amount

    @property
    def net_profit(self):
        if self.is_refunded:
            return Decimal('0.00')
        # Profit only on the quantity that wasn't returned.
        item_profit = sum(
            ((item.quantity - item.returned_quantity) * (item.unit_price - item.unit_cost)
             for item in self.items.all()),
            Decimal('0.00'),
        )
        return item_profit - self.discount

    def __str__(self):
        return f"Sale #{self.id} - {self.timestamp.strftime('%Y-%m-%d %H:%M')}"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='items')
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT)
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2) # Selling Price
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) # Purchase Price at time of sale
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    returned_quantity = models.PositiveIntegerField(default=0)

    @property
    def returnable_quantity(self):
        return max(self.quantity - self.returned_quantity, 0)

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.unit_price
        self.total_cost = self.quantity * self.unit_cost
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.drug.trade_name} x {self.quantity}"
