from django.db import models
from decimal import Decimal

class Supplier(models.Model):
    name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=15, blank=True)
    email = models.EmailField(blank=True)
    address = models.TextField(blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # We allow initial save, but subsequent manual balance edits are discouraged
        # though enforcement is better done at view/form level in Django.
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['name']

class SupplierPayment(models.Model):
    PAYMENT_MODES = (
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer'),
        # ('CHEQUE', 'Cheque'),
    )
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(auto_now_add=True)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default='CASH')
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Payment of {self.amount} to {self.supplier.name}"
