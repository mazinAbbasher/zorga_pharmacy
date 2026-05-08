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
        return self.role == 'ADMIN'

    def is_pharmacist(self):
        return self.role == 'PHARMACIST'
