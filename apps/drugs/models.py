from django.db import models
from django.db.models import Q
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
    DISPENSING_CHOICES = (
        ('FEFO', 'FEFO - First Expiry, First Out'),
        ('FIFO', 'FIFO - First In, First Out'),
    )

    trade_name = models.CharField(max_length=200)
    scientific_name = models.CharField(max_length=200, blank=True)
    manufacturer = models.CharField(max_length=200, blank=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='drugs')

    barcode = models.CharField(max_length=100, unique=True, blank=True, null=True)

    # How stock is consumed when selling: FEFO (nearest expiry first, the safe
    # pharmacy default) or FIFO (oldest received first).
    dispensing_strategy = models.CharField(max_length=4, choices=DISPENSING_CHOICES, default='FEFO')

    # Global thresholds
    minimum_stock_alert = models.IntegerField(default=10)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @staticmethod
    def _not_expired(today):
        # A batch is "active" if it expires today or later, or has no expiry at
        # all (FIFO/non-perishable products may omit the expiry date).
        return Q(expiry_date__gte=today) | Q(expiry_date__isnull=True)

    @property
    def total_quantity(self):
        today = timezone.now().date()
        return sum(b.quantity for b in self.batches.filter(self._not_expired(today)))

    @property
    def expired_quantity(self):
        today = timezone.now().date()
        return sum(b.quantity for b in self.batches.filter(expiry_date__lt=today))

    @property
    def total_inventory_value(self):
        # Value of non-expired stock
        today = timezone.now().date()
        return sum(b.quantity * b.purchase_price for b in self.batches.filter(self._not_expired(today)))

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
    def is_out_of_stock(self):
        return self.stock_status == 'OUT_OF_STOCK'

    @property
    def needs_restock(self):
        # Low *or* out of stock: sellable quantity at or below the alert threshold.
        return self.stock_status != 'IN_STOCK'

    @property
    def dispense_order(self):
        """Batch ordering for selling, based on this product's strategy.

        FEFO -> nearest expiry first; FIFO -> oldest received first. A secondary
        key keeps the order deterministic when the primary key ties.
        """
        if self.dispensing_strategy == 'FIFO':
            return ('created_at', 'expiry_date')
        return ('expiry_date', 'created_at')

    def active_batches(self):
        """Non-expired batches with stock, ordered by the dispensing strategy."""
        today = timezone.now().date()
        return self.batches.filter(
            self._not_expired(today), quantity__gt=0
        ).order_by(*self.dispense_order)

    @property
    def current_price(self):
        # Price of the next batch to be dispensed (per FIFO/FEFO strategy).
        active_batch = self.active_batches().first()
        return active_batch.selling_price if active_batch else Decimal('0.00')

    @property
    def current_buy_price(self):
        # Current buy (purchase) cost used to value on-hand stock. Read from the
        # next batch to be dispensed; a bulk/manual revaluation keeps every
        # active batch in sync, so this acts as the per-product cost. Historical
        # invoices (PurchaseItem) and past sale costs (SaleItem.unit_cost) keep
        # their own frozen values and are unaffected by changing this.
        active_batch = self.active_batches().first()
        return active_batch.purchase_price if active_batch else Decimal('0.00')

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
    batch_number = models.CharField(max_length=100, blank=True, default='')
    
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.00'))])
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    
    quantity = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    # Optional: FIFO (non-batch) products may not track an expiry date.
    expiry_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Batch {self.batch_number} - {self.drug.trade_name}"

    class Meta:
        verbose_name_plural = "Batches"
        ordering = ['expiry_date']
