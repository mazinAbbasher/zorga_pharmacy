from django.test import TestCase, Client
from django.urls import reverse
from users.models import User

class RBACTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_superuser(
            username='admin', 
            email='admin@test.com', 
            password='password123',
            role='ADMIN'
        )
        self.pharmacist_user = User.objects.create_user(
            username='pharmacist', 
            email='pharmacist@test.com', 
            password='password123',
            role='PHARMACIST'
        )

    def test_admin_access_all(self):
        self.client.login(username='admin', password='password123')
        
        # Admin can access users list
        response = self.client.get(reverse('users:list'))
        self.assertEqual(response.status_code, 200)
        
        # Admin can access reports
        response = self.client.get(reverse('reports:index'))
        self.assertEqual(response.status_code, 200)
        
        # Admin can access settings
        response = self.client.get(reverse('settings_app:index'))
        self.assertEqual(response.status_code, 200)

        # Admin can access purchases
        response = self.client.get(reverse('purchases:list'))
        self.assertEqual(response.status_code, 200)

    def test_pharmacist_operational_access(self):
        self.client.login(username='pharmacist', password='password123')
        
        # Pharmacist CAN access POS (unrestricted)
        response = self.client.get(reverse('pos:index'))
        self.assertEqual(response.status_code, 200)
        
        # Pharmacist CAN access transactions (Sales history)
        response = self.client.get(reverse('transactions:list'))
        self.assertEqual(response.status_code, 200)
        
        # Pharmacist CANNOT access reports (Simplified roles: restricted from Reports)
        response = self.client.get(reverse('reports:index'))
        self.assertEqual(response.status_code, 403)
        
        # Pharmacist CANNOT access user management
        response = self.client.get(reverse('users:list'))
        self.assertEqual(response.status_code, 403)

        # Pharmacist CANNOT access purchases
        response = self.client.get(reverse('purchases:list'))
        self.assertEqual(response.status_code, 403)

        # Pharmacist CANNOT access suppliers
        response = self.client.get(reverse('suppliers:list'))
        self.assertEqual(response.status_code, 403)
