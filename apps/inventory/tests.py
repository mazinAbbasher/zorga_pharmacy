from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from drugs.models import Drug, Category, Batch
from inventory.models import StockMovement
from inventory.services import adjust_stock, write_off_expired
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


class StockCorrectionServiceTests(TestCase):
    """adjust_stock / write_off_expired must change stock *and* write the matching
    movement, keeping ``sum(signed movements) == raw on-hand``."""

    def setUp(self):
        self.user = User.objects.create_superuser(username='admin', role='ADMIN', password='pw')
        self.cat = Category.objects.create(name='Meds')
        self.drug = Drug.objects.create(trade_name='Amoxil', category=self.cat)
        self.batch = Batch.objects.create(
            drug=self.drug, batch_number='B1', quantity=30,
            purchase_price=Decimal('4.00'), selling_price=Decimal('9.00'),
            expiry_date=timezone.now().date() + timedelta(days=120),
        )

    def _raw_and_ledger(self):
        raw = sum(b.quantity for b in self.drug.batches.all())
        ledger = sum(m.signed_quantity for m in self.drug.movements.all())
        return raw, ledger

    def test_adjust_increase_logs_positive_adjustment(self):
        delta = adjust_stock(self.drug, 35, self.user, 'found stock')
        self.assertEqual(delta, 5)
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 35)
        mv = self.drug.movements.get(movement_type='ADJUSTMENT')
        self.assertEqual(mv.signed_quantity, 5)
        self.assertTrue(mv.increases_stock)

    def test_adjust_decrease_logs_negative_adjustment(self):
        delta = adjust_stock(self.drug, 22, self.user, 'breakage')
        self.assertEqual(delta, -8)
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 22)
        mv = self.drug.movements.get(movement_type='ADJUSTMENT')
        self.assertEqual(mv.signed_quantity, -8)
        self.assertFalse(mv.increases_stock)

    def test_adjust_no_change_writes_no_movement(self):
        self.assertEqual(adjust_stock(self.drug, 30, self.user, 'match'), 0)
        self.assertFalse(self.drug.movements.filter(movement_type='ADJUSTMENT').exists())

    def test_adjust_keeps_ledger_reconciled(self):
        # An opening IN makes the ledger explain the starting stock.
        StockMovement.objects.create(
            drug=self.drug, movement_type='IN', quantity=30, reference_id='SEED', user=self.user,
        )
        adjust_stock(self.drug, 40, self.user, 'up')
        adjust_stock(self.drug, 25, self.user, 'down')
        raw, ledger = self._raw_and_ledger()
        self.assertEqual(raw, ledger)
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 25)

    def test_write_off_expired_zeroes_batches_and_logs(self):
        expired = Batch.objects.create(
            drug=self.drug, batch_number='OLD', quantity=7,
            purchase_price=Decimal('4.00'), selling_price=Decimal('9.00'),
            expiry_date=timezone.now().date() - timedelta(days=3),
        )
        sellable_before = self.drug.total_quantity
        self.assertEqual(write_off_expired(self.drug, self.user), 7)
        expired.refresh_from_db()
        self.assertEqual(expired.quantity, 0)
        mv = self.drug.movements.get(movement_type='EXPIRED')
        self.assertEqual(mv.signed_quantity, -7)
        # Expired units were never sellable, so sellable stock is unchanged.
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, sellable_before)

    def test_write_off_expired_noop_when_nothing_expired(self):
        self.assertEqual(write_off_expired(self.drug, self.user), 0)
        self.assertFalse(self.drug.movements.filter(movement_type='EXPIRED').exists())


class StockMovementsPageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(username='admin', role='ADMIN', password='pw')
        self.client = Client()
        self.client.login(username='admin', password='pw')
        self.cat = Category.objects.create(name='Meds')
        self.drug = Drug.objects.create(trade_name='Brufen', category=self.cat)
        Batch.objects.create(
            drug=self.drug, batch_number='B1', quantity=12,
            purchase_price=Decimal('3.00'), selling_price=Decimal('7.00'),
            expiry_date=timezone.now().date() + timedelta(days=90),
        )
        StockMovement.objects.create(
            drug=self.drug, movement_type='IN', quantity=12, reference_id='PUR-1', user=self.user,
        )

    def test_page_renders_with_running_balance(self):
        resp = self.client.get(reverse('drugs:stock_movements', args=[self.drug.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context['reconciled'])
        self.assertEqual(resp.context['raw_on_hand'], 12)
        # Newest (only) movement's balance-after equals current on-hand.
        self.assertEqual(resp.context['movements'][0].balance_after, 12)

    def test_type_filter_narrows_ledger(self):
        StockMovement.objects.create(
            drug=self.drug, movement_type='OUT', quantity=2, reference_id='SALE-1', user=self.user,
        )
        resp = self.client.get(
            reverse('drugs:stock_movements', args=[self.drug.pk]), {'type': 'OUT'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['total_movements'], 1)
        self.assertEqual(resp.context['movements'][0].movement_type, 'OUT')
