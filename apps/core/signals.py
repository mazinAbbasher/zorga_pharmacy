from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from purchases.models import Purchase
from suppliers.models import Supplier, SupplierPayment
from pos.models import Sale
from customers.models import Customer, CustomerPayment
from decimal import Decimal

@receiver(post_save, sender=Purchase)
def update_supplier_balance_on_purchase(sender, instance, created, **kwargs):
    if created:
        supplier = instance.supplier
        if not isinstance(supplier.balance, Decimal):
            supplier.balance = Decimal(str(supplier.balance))
        supplier.balance += Decimal(str(instance.total_amount))
        supplier.save()

@receiver(post_save, sender=SupplierPayment)
def update_supplier_balance_on_payment(sender, instance, created, **kwargs):
    supplier = instance.supplier
    # Force absolute recalculation for perfect accuracy
    total_purchases = Purchase.objects.filter(supplier=supplier).aggregate(models.Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    total_payments = SupplierPayment.objects.filter(supplier=supplier).aggregate(models.Sum('amount'))['amount__sum'] or Decimal('0.00')
    Supplier.objects.filter(pk=supplier.pk).update(balance=total_purchases - total_payments)

@receiver(models.signals.post_delete, sender=SupplierPayment)
def update_supplier_balance_on_payment_delete(sender, instance, **kwargs):
    supplier = instance.supplier
    total_purchases = Purchase.objects.filter(supplier=supplier).aggregate(models.Sum('total_amount'))['total_amount__sum'] or Decimal('0.00')
    total_payments = SupplierPayment.objects.filter(supplier=supplier).aggregate(models.Sum('amount'))['amount__sum'] or Decimal('0.00')
    Supplier.objects.filter(pk=supplier.pk).update(balance=total_purchases - total_payments)

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
