from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from drugs.models import Drug, Category, Batch
from purchases.models import Purchase, PurchaseItem
from suppliers.models import Supplier
from users.models import User


class BulkPriceUpdateTests(TestCase):
    """The bulk tool can move either the sale price or the buy (cost) price.

    The defining guarantee: changing the buy price revalues on-hand stock
    (Batch.purchase_price) but never rewrites history — past purchase invoices
    (PurchaseItem) keep what was actually paid.
    """

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='admin', role='ADMIN', password='pw'
        )
        self.client.login(username='admin', password='pw')
        self.url = reverse('inventory:bulk_price')

        self.cat = Category.objects.create(name="Meds")
        self.supplier = Supplier.objects.create(name="Acme")

        self.drug = Drug.objects.create(trade_name="Panadol", category=self.cat)
        self.batch = Batch.objects.create(
            drug=self.drug, batch_number="B1", quantity=50,
            purchase_price=Decimal('10.00'), selling_price=Decimal('15.00'),
            expiry_date=timezone.now().date() + timedelta(days=100),
        )

        # A historical purchase invoice for the same drug — this records what we
        # actually paid and must stay frozen no matter how we revalue stock.
        purchase = Purchase.objects.create(
            supplier=self.supplier, invoice_number="INV-1", received_by=self.admin,
        )
        self.item = PurchaseItem.objects.create(
            purchase=purchase, drug=self.drug, quantity=50,
            purchase_price=Decimal('10.00'), selling_price=Decimal('15.00'),
        )

    def _apply(self, **over):
        data = {
            'action': 'apply', 'target': 'selling', 'direction': 'increase',
            'percentage': '20', 'scope': 'all',
        }
        data.update(over)
        return self.client.post(self.url, data)

    def test_buy_price_update_revalues_stock_only(self):
        resp = self._apply(target='purchase', direction='increase', percentage='20')
        self.assertEqual(resp.status_code, 302)

        self.batch.refresh_from_db()
        self.item.refresh_from_db()

        # Stock cost is revalued (10 -> 12); sale price untouched.
        self.assertEqual(self.batch.purchase_price, Decimal('12.00'))
        self.assertEqual(self.batch.selling_price, Decimal('15.00'))
        # The historical invoice is frozen — still what we actually paid.
        self.assertEqual(self.item.purchase_price, Decimal('10.00'))

    def test_sale_price_update_unaffected_by_target(self):
        resp = self._apply(target='selling', direction='increase', percentage='10')
        self.assertEqual(resp.status_code, 302)

        self.batch.refresh_from_db()
        self.assertEqual(self.batch.selling_price, Decimal('16.50'))  # 15 * 1.10
        self.assertEqual(self.batch.purchase_price, Decimal('10.00'))  # cost untouched

    def test_buy_price_floor_allows_zero_sale_price_does_not(self):
        # A 99% cut rounds the price to 0.00. Buy price may sit at 0; a sale
        # price is floored at 0.01 so stock stays sellable.
        self.batch.purchase_price = Decimal('0.10')
        self.batch.selling_price = Decimal('0.10')
        self.batch.save()

        self._apply(target='purchase', direction='decrease', percentage='99')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.purchase_price, Decimal('0.00'))

        self._apply(target='selling', direction='decrease', percentage='99')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.selling_price, Decimal('0.01'))

    def test_preview_labels_the_chosen_target(self):
        resp = self.client.post(self.url, {
            'action': 'preview', 'target': 'purchase', 'direction': 'increase',
            'percentage': '20', 'scope': 'all',
        }, HTTP_HX_REQUEST='true')
        self.assertContains(resp, 'Buy price')
        # Sample preview shows the cost moving (10 -> 12), not the sale price.
        self.assertEqual(resp.context['target_label'], 'Buy')
        self.assertEqual(resp.context['samples'][0]['new_price'], Decimal('12.00'))
