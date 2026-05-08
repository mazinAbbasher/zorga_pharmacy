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

    class Meta:
        ordering = ['-timestamp']
