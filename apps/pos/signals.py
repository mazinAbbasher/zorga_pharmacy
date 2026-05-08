from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import SaleItem
from inventory.models import StockMovement

@receiver(post_save, sender=SaleItem)
def reduce_inventory(sender, instance, created, **kwargs):
    if created:
        drug = instance.drug
        # Note: quantity is managed via Batches (FIFO)
        # drug.save() is not needed here as no fields on drug are changed
        
        # Create Movement Log
        StockMovement.objects.create(
            drug=drug,
            movement_type='OUT',
            quantity=instance.quantity,
            reference_id=f"SALE-{instance.sale.id}",
            user=instance.sale.cashier,
            notes=f"Sold via POS (Sale #{instance.sale.id})"
        )
