from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from .models import Drug, Category, Batch
from users.models import User
from decimal import Decimal

class InventoryTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username='admin', role='ADMIN', password='password123')
        self.client.login(username='admin', password='password123')
        
        self.cat_med = Category.objects.create(name="Medicine")
        
        # Drug 1: Healthy stock
        self.drug_ok = Drug.objects.create(
            trade_name="Panadol", 
            scientific_name="Paracetamol", 
            category=self.cat_med,
            minimum_stock_alert=10
        )
        Batch.objects.create(
            drug=self.drug_ok, batch_number="B1", 
            quantity=50, purchase_price=10.00, selling_price=15.00,
            expiry_date=timezone.now().date() + timedelta(days=100)
        )
        
        # Drug 2: Low stock
        self.drug_low = Drug.objects.create(
            trade_name="Amoxil", 
            scientific_name="Amoxicillin", 
            category=self.cat_med,
            minimum_stock_alert=20
        )
        Batch.objects.create(
            drug=self.drug_low, batch_number="B2", 
            quantity=5, purchase_price=20.00, selling_price=30.00,
            expiry_date=timezone.now().date() + timedelta(days=120)
        )
        
        # Drug 3: Expired batch
        self.drug_exp = Drug.objects.create(
            trade_name="Voltaren",
            category=self.cat_med
        )
        Batch.objects.create(
            drug=self.drug_exp, batch_number="B3", 
            quantity=100, purchase_price=5.00, selling_price=10.00,
            expiry_date=timezone.now().date() - timedelta(days=5)
        )

    def test_drug_properties(self):
        # Panadol: 50 units, not expired
        self.assertEqual(self.drug_ok.total_quantity, 50)
        self.assertEqual(self.drug_ok.stock_status, 'IN_STOCK')
        self.assertEqual(float(self.drug_ok.total_inventory_value), 500.00)
        
        # Amoxil: 5 units, threshold 20 -> Low Stock
        self.assertEqual(self.drug_low.stock_status, 'LOW_STOCK')
        
        # Voltaren: 100 units but all expired -> 0 total_quantity
        self.assertEqual(self.drug_exp.total_quantity, 0)
        self.assertEqual(self.drug_exp.expired_quantity, 100)
        self.assertEqual(self.drug_exp.stock_status, 'OUT_OF_STOCK')

    def test_filtering_views(self):
        url = reverse('drugs:list')
        
        # Filter by Low Stock
        response = self.client.get(url, {'status': 'low'})
        self.assertContains(response, "Amoxil")
        self.assertNotContains(response, "Panadol")
        
        # Filter by Out of Stock (Expired counts as out of stock)
        response = self.client.get(url, {'status': 'out'})
        self.assertContains(response, "Voltaren")
        
        # Filter by Expiry Soon (None of these expire within 90 days except maybe Panadol if I set it closer)
        # B1 is 100 days away. Let's create one 30 days away.
        drug_soon = Drug.objects.create(trade_name="SoonExp")
        Batch.objects.create(
            drug=drug_soon, batch_number="B_SOON", 
            quantity=10, purchase_price=1.00, selling_price=2.00,
            expiry_date=timezone.now().date() + timedelta(days=30)
        )
        
        response = self.client.get(url, {'expiry': 'soon'})
        self.assertContains(response, "SoonExp")
        self.assertNotContains(response, "Panadol")
