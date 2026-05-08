from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import PurchaseItem
from inventory.models import StockMovement

@receiver(post_save, sender=PurchaseItem)
def increase_inventory(sender, instance, created, **kwargs):
    if created:
        drug = instance.drug
        # Note: quantity is managed via Batches (FIFO) and properties.
        # Master stock updates are not directly required on the Drug model.
        drug.save()
        
        # Create Movement Log
        StockMovement.objects.create(
            drug=drug,
            movement_type='IN',
            quantity=instance.quantity,
            reference_id=f"PUR-{instance.purchase.id}",
            user=instance.purchase.received_by,
            notes=f"Purchase from {instance.purchase.supplier.name} (Invoice #{instance.purchase.invoice_number})"
        )
