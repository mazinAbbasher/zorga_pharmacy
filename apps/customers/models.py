from django.db import models
from decimal import Decimal

class Customer(models.Model):
    name = models.CharField(max_length=200)
    phone_number = models.CharField(max_length=15, blank=True)
    outstanding_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    address = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class CustomerPayment(models.Model):
    PAYMENT_MODES = (
        ('CASH', 'Cash'),
        ('BANK', 'Bank Transfer'),
        ('SDG_WALLET', 'SDG Wallet'),
    )
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField(auto_now_add=True)
    payment_mode = models.CharField(max_length=10, choices=PAYMENT_MODES, default='CASH')
    reference = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"Payment of {self.amount} from {self.customer.name}"
        
class CustomerInvoice(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='invoices')
    sale_id = models.IntegerField() # Linked to POS Sale ID
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invoice for {self.customer.name} - ${self.amount}"
