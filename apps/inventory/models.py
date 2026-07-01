from django.db import models
from drugs.models import Drug
from django.conf import settings

class StockMovement(models.Model):
    MOVEMENT_TYPES = (
        ('IN', 'Stock In (Purchase)'),
        ('OUT', 'Stock Out (Sale)'),
        ('RETURN', 'Return'),
        ('ADJUSTMENT', 'Adjustment'),
        ('EXPIRED', 'Expired / Loss'),
    )
    
    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.IntegerField()
    reference_id = models.CharField(max_length=100, blank=True, null=True) # Sale ID or Purchase ID
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.drug.trade_name} - {self.movement_type} - {self.quantity}"

    # `quantity` is always stored as a positive magnitude. The direction of the
    # stock change is derived from the movement type. RETURN is bidirectional:
    # a customer return (REF-/RET-SALE-) restores stock, while a supplier return
    # (RET-PUR-) removes it, so it's classified by its reference id.
    _STOCK_IN_TYPES = {'IN'}
    _STOCK_OUT_TYPES = {'OUT', 'EXPIRED'}

    @property
    def increases_stock(self):
        if self.movement_type in self._STOCK_IN_TYPES:
            return True
        if self.movement_type in self._STOCK_OUT_TYPES:
            return False
        if self.movement_type == 'RETURN':
            return not (self.reference_id or '').startswith('RET-PUR-')
        # ADJUSTMENT / anything else: fall back to the stored quantity's sign.
        return self.quantity >= 0

    @property
    def signed_quantity(self):
        """Quantity signed by direction: positive adds stock, negative removes."""
        magnitude = abs(self.quantity)
        return magnitude if self.increases_stock else -magnitude

    class Meta:
        ordering = ['-timestamp']
