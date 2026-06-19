from django.db import models
from django.conf import settings
from drugs.models import Drug
from suppliers.models import Supplier
from django.utils import timezone
from decimal import Decimal

class Purchase(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchases')
    invoice_number = models.CharField(max_length=100)
    purchase_date = models.DateField(default=timezone.now)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Purchase {self.invoice_number} - {self.supplier.name}"

    @property
    def returned_amount(self):
        """Value of items returned to the supplier from this purchase."""
        return sum(
            (item.purchase_price * item.returned_quantity for item in self.items.all()),
            Decimal('0.00'),
        )

    @property
    def net_amount(self):
        return self.total_amount - self.returned_amount

    @property
    def is_fully_returned(self):
        items = list(self.items.all())
        return bool(items) and all(i.returnable_quantity == 0 for i in items)

class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='items')
    drug = models.ForeignKey(Drug, on_delete=models.PROTECT)
    batch_number = models.CharField(max_length=100, blank=True, default='')
    quantity = models.IntegerField()
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2)
    expiry_date = models.DateField(null=True, blank=True)
    total_price = models.DecimalField(max_digits=12, decimal_places=2)
    returned_quantity = models.PositiveIntegerField(default=0)

    @property
    def returnable_quantity(self):
        return max(self.quantity - self.returned_quantity, 0)

    def save(self, *args, **kwargs):
        self.total_price = self.quantity * self.purchase_price
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.drug.trade_name} x {self.quantity}"
