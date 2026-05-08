from django.db.models.signals import post_migrate
from django.contrib.auth.models import Group
from django.dispatch import receiver

@receiver(post_migrate)
def create_default_groups(sender, **kwargs):
    """
    Automatically create base security groups after migration.
    """
    if sender.name == 'users':
        roles = ['Admin', 'Pharmacist', 'Cashier']
        for role in roles:
            Group.objects.get_or_create(name=role)
