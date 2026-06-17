from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    ROLE_CHOICES = (
        ('ADMIN', 'Admin'),
        ('PHARMACIST', 'Pharmacist'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='PHARMACIST')
    phone_number = models.CharField(max_length=15, blank=True, null=True)

    def is_admin(self):
        return self.is_superuser or self.role == 'ADMIN'

    def is_pharmacist(self):
        return not self.is_admin() and self.role == 'PHARMACIST'
