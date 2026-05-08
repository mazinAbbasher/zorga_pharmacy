from django.db import models
from django.core.validators import MinValueValidator
from django.utils import timezone
from decimal import Decimal

class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name_plural = "Categories"

class Drug(models.Model):
    trade_name = models.CharField(max_length=200)
    scientific_name = models.CharField(max_length=200, blank=True)
    manufacturer = models.CharField(max_length=200, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='drugs')
    
    barcode = models.CharField(max_length=100, unique=True, blank=True, null=True)
    
    # Global thresholds
    minimum_stock_alert = models.IntegerField(default=10)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def total_quantity(self):
        today = timezone.now().date()
        return sum(batch.quantity for batch in self.batches.filter(expiry_date__gte=today))

    @property
    def expired_quantity(self):
        today = timezone.now().date()
        return sum(batch.quantity for batch in self.batches.filter(expiry_date__lt=today))

    @property
    def total_inventory_value(self):
        # Value of non-expired stock
        today = timezone.now().date()
        return sum(batch.quantity * batch.purchase_price for batch in self.batches.filter(expiry_date__gte=today))

    @property
    def stock_status(self):
        qty = self.total_quantity
        if qty <= 0:
            return 'OUT_OF_STOCK'
        if qty <= self.minimum_stock_alert:
            return 'LOW_STOCK'
        return 'IN_STOCK'

    @property
    def is_low_stock(self):
        return self.stock_status == 'LOW_STOCK'
    
    @property
    def current_price(self):
        # Returns the price of the oldest active non-expired batch (FIFO)
        today = timezone.now().date()
        active_batch = self.batches.filter(quantity__gt=0, expiry_date__gte=today).order_by('created_at').first()
        return active_batch.selling_price if active_batch else Decimal('0.00')

    @property
    def nearest_expiry_date(self):
        # Returns the nearest expiry date of active non-expired batches
        today = timezone.now().date()
        active_batch = self.batches.filter(quantity__gt=0, expiry_date__gte=today).order_by('expiry_date').first()
        return active_batch.expiry_date if active_batch else None

    def __str__(self):
        return f"{self.trade_name} ({self.scientific_name})"

class Batch(models.Model):
    drug = models.ForeignKey(Drug, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=100)
    
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    expiry_date = models.DateField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Batch {self.batch_number} - {self.drug.trade_name}"

    class Meta:
        verbose_name_plural = "Batches"
        ordering = ['expiry_date']
