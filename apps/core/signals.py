from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from purchases.models import Purchase
from suppliers.models import Supplier, SupplierPayment
from pos.models import Sale
from customers.models import Customer, CustomerPayment
from decimal import Decimal

def recalculate_supplier_balance(supplier):
    """Set a supplier's balance to what we owe them: net purchases minus payments.

    ``net_amount`` (not raw ``total_amount``) is used so supplier returns are
    reflected. This is the single source of truth for supplier balance, called
    whenever a purchase, return, or payment changes.
    """
    total_purchases = sum(
        (p.net_amount for p in Purchase.objects.filter(supplier=supplier).prefetch_related('items')),
        Decimal('0.00'),
    )
    total_payments = SupplierPayment.objects.filter(supplier=supplier).aggregate(
        models.Sum('amount'))['amount__sum'] or Decimal('0.00')
    Supplier.objects.filter(pk=supplier.pk).update(balance=total_purchases - total_payments)

@receiver(post_save, sender=Purchase)
@receiver(models.signals.post_delete, sender=Purchase)
def update_supplier_balance_on_purchase(sender, instance, **kwargs):
    # Recalculate on every save (not just creation): the create view saves a
    # purchase once with total_amount=0, then again with the real total once its
    # items exist. An incremental "if created" update would miss that real total.
    recalculate_supplier_balance(instance.supplier)

@receiver(post_save, sender=SupplierPayment)
@receiver(models.signals.post_delete, sender=SupplierPayment)
def update_supplier_balance_on_payment(sender, instance, **kwargs):
    recalculate_supplier_balance(instance.supplier)

@receiver(post_save, sender=CustomerPayment)
@receiver(models.signals.post_delete, sender=CustomerPayment)
@receiver(post_save, sender=Sale)
@receiver(models.signals.post_delete, sender=Sale)
def update_customer_balance_on_financial_event(sender, instance, **kwargs):
    customer = instance.customer
    if not customer: return
    
    # Absolute recalculation of debt: for each non-refunded credit sale the
    # customer owes (total - discount - value of any returned items).
    credit_sales = Sale.objects.filter(
        customer=customer,
        payment_method='CREDIT',
        is_refunded=False,
    ).prefetch_related('items')

    total_owed = sum(
        (s.total_amount - s.discount - s.refunded_amount for s in credit_sales),
        Decimal('0.00'),
    )

    total_payments = CustomerPayment.objects.filter(
        customer=customer
    ).aggregate(models.Sum('amount'))['amount__sum'] or Decimal('0.00')

    # Direct DB update to prevent interference from stale model instances
    Customer.objects.filter(pk=customer.pk).update(
        outstanding_balance=total_owed - total_payments
    )
