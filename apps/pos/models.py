from django.db import models
from django.conf import settings
from drugs.models import Drug
from django.utils import timezone

class Sale(models.Model):
    PAYMENT_METHODS = (
        ('CASH', 'Cash'),
        ('BANK_TRANSFER', 'Bank Transfer'),
        ('CARD', 'Card'),
        ('CREDIT', 'Customer Credit'),
    )
    
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
    def net_profit(self):
        if self.is_refunded:
            return Decimal('0.00')
        item_profit = sum(item.total_price - item.total_cost for item in self.items.all())
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

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.unit_price
        self.total_cost = self.quantity * self.unit_cost
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.drug.trade_name} x {self.quantity}"
