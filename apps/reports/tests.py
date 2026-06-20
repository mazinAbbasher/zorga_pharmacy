from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from drugs.models import Drug, Category, Batch
from users.models import User


class StockValuationReportTests(TestCase):
    """Available-stock valuation lists in-stock, non-expired batches and totals
    quantity x buy price."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username='admin', role='ADMIN', password='pw')
        self.client.login(username='admin', password='pw')
        self.url = reverse('reports:stock_valuation')

        self.cat = Category.objects.create(name="Meds")
        self.today = timezone.now().date()

        self.drug = Drug.objects.create(trade_name="Panadol", category=self.cat)
        # Available: 50 @ 10 = 500, and 20 @ 12 = 240  -> 740
        Batch.objects.create(
            drug=self.drug, batch_number="B1", quantity=50,
            purchase_price=Decimal('10.00'), selling_price=Decimal('15.00'),
            expiry_date=self.today + timedelta(days=100),
        )
        Batch.objects.create(
            drug=self.drug, batch_number="B2", quantity=20,
            purchase_price=Decimal('12.00'), selling_price=Decimal('18.00'),
            expiry_date=self.today + timedelta(days=200),
        )
        # Excluded: expired, and zero-quantity.
        Batch.objects.create(
            drug=self.drug, batch_number="EXP", quantity=99,
            purchase_price=Decimal('10.00'), selling_price=Decimal('15.00'),
            expiry_date=self.today - timedelta(days=1),
        )
        Batch.objects.create(
            drug=self.drug, batch_number="ZERO", quantity=0,
            purchase_price=Decimal('10.00'), selling_price=Decimal('15.00'),
            expiry_date=self.today + timedelta(days=100),
        )

    def test_totals_count_available_stock_only(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_value'], Decimal('740.00'))
        self.assertEqual(resp.context['total_units'], 70)
        self.assertEqual(resp.context['batch_count'], 2)
        # Per-row line totals are annotated.
        line_totals = sorted(b.line_total for b in resp.context['batches'])
        self.assertEqual(line_totals, [Decimal('240.00'), Decimal('500.00')])
        # Expiry column is present and dated.
        self.assertContains(resp, 'Expiry Date')
        self.assertContains(resp, (self.today + timedelta(days=100)).strftime('%b'))

    def test_matches_dashboard_inventory_valuation(self):
        # The report's grand total equals the sum of Drug.total_inventory_value.
        resp = self.client.get(self.url)
        expected = sum(d.total_inventory_value for d in Drug.objects.all())
        self.assertEqual(resp.context['total_value'], expected)

    def test_search_filters_by_drug_or_batch(self):
        Batch.objects.create(
            drug=Drug.objects.create(trade_name="Amoxil", category=self.cat),
            batch_number="AMX", quantity=5,
            purchase_price=Decimal('3.00'), selling_price=Decimal('6.00'),
            expiry_date=self.today + timedelta(days=100),
        )
        resp = self.client.get(self.url, {'q': 'Amoxil'})
        self.assertEqual(resp.context['batch_count'], 1)
        self.assertEqual(resp.context['total_value'], Decimal('15.00'))

    def test_requires_admin(self):
        self.client.logout()
        pharmacist = User.objects.create_user(username='ph', role='PHARMACIST', password='pw')
        self.client.force_login(pharmacist)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)
