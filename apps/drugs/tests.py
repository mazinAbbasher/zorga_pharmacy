from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from .models import Drug, Category, Batch
from .forms import DrugForm
from users.models import User
from decimal import Decimal


class DrugBarcodeFormTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="General")

    def _data(self, **over):
        data = {
            "trade_name": "Item",
            "category": self.category.id,
            "barcode": "",
            "dispensing_strategy": "FEFO",
            "minimum_stock_alert": 10,
        }
        data.update(over)
        return data

    def test_empty_barcode_saved_as_null(self):
        form = DrugForm(data=self._data(trade_name="A", barcode="   "))
        self.assertTrue(form.is_valid(), form.errors)
        drug = form.save()
        self.assertIsNone(drug.barcode)

    def test_two_products_without_barcode_do_not_collide(self):
        for name in ("A", "B"):
            form = DrugForm(data=self._data(trade_name=name, barcode=""))
            self.assertTrue(form.is_valid(), form.errors)
            form.save()
        self.assertEqual(Drug.objects.filter(barcode__isnull=True).count(), 2)

    def test_barcode_is_trimmed(self):
        form = DrugForm(data=self._data(barcode="  ABC-123  "))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().barcode, "ABC-123")

class DrugBuyPriceFormTests(TestCase):
    """Editing a product's buy price revalues active stock only — expired
    batches and (separately) historical invoices are left alone."""

    def setUp(self):
        self.category = Category.objects.create(name="General")
        self.today = timezone.now().date()
        self.drug = Drug.objects.create(
            trade_name="Panadol", category=self.category, dispensing_strategy="FEFO",
        )
        self.active = Batch.objects.create(
            drug=self.drug, batch_number="A", quantity=10,
            purchase_price=Decimal("10"), selling_price=Decimal("15"),
            expiry_date=self.today + timedelta(days=100),
        )
        self.expired = Batch.objects.create(
            drug=self.drug, batch_number="E", quantity=5,
            purchase_price=Decimal("10"), selling_price=Decimal("15"),
            expiry_date=self.today - timedelta(days=1),
        )

    def _data(self, **over):
        data = {
            "trade_name": "Panadol", "category": self.category.id, "barcode": "",
            "dispensing_strategy": "FEFO", "minimum_stock_alert": 10,
        }
        data.update(over)
        return data

    def test_buy_price_cascades_to_active_batches_only(self):
        form = DrugForm(data=self._data(buy_price="12.50"), instance=self.drug)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()

        self.active.refresh_from_db()
        self.expired.refresh_from_db()
        self.assertEqual(self.active.purchase_price, Decimal("12.50"))
        self.assertEqual(self.expired.purchase_price, Decimal("10"))  # untouched
        self.assertEqual(self.drug.current_buy_price, Decimal("12.50"))

    def test_buy_price_cascades_to_fifo_null_expiry_batch(self):
        # FIFO products carry no expiry; they are still "active" and revalue.
        fifo = Drug.objects.create(trade_name="Gauze", category=self.category, dispensing_strategy="FIFO")
        batch = Batch.objects.create(
            drug=fifo, batch_number="", quantity=8,
            purchase_price=Decimal("3"), selling_price=Decimal("5"), expiry_date=None,
        )
        form = DrugForm(
            data=self._data(trade_name="Gauze", dispensing_strategy="FIFO", buy_price="4"),
            instance=fifo,
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        batch.refresh_from_db()
        self.assertEqual(batch.purchase_price, Decimal("4"))

    def test_blank_buy_price_leaves_stock_unchanged(self):
        form = DrugForm(data=self._data(), instance=self.drug)  # no buy_price
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.active.refresh_from_db()
        self.assertEqual(self.active.purchase_price, Decimal("10"))


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


class RestockNeededSelectorTests(TestCase):
    """restock_needed_drugs() must equal the set of drugs where needs_restock is True."""

    def setUp(self):
        from drugs.selectors import restock_needed_drugs
        self.restock_needed_drugs = restock_needed_drugs
        self.cat = Category.objects.create(name="Meds")
        self.today = timezone.now().date()

    def _drug(self, name, qty, *, expired=False, min_alert=10):
        drug = Drug.objects.create(trade_name=name, category=self.cat, minimum_stock_alert=min_alert)
        if qty is not None:
            Batch.objects.create(
                drug=drug, batch_number=name, quantity=qty,
                purchase_price=Decimal("1"), selling_price=Decimal("2"),
                expiry_date=self.today - timedelta(days=1) if expired else self.today + timedelta(days=100),
            )
        return drug

    def test_matches_needs_restock_property(self):
        self._drug("Healthy", 50)        # in stock -> ok
        self._drug("Low", 5)             # low stock -> needs restock
        self._drug("Out", 0)             # out of stock -> needs restock
        self._drug("NoBatch", None)      # no batches -> needs restock
        self._drug("ExpiredOnly", 100, expired=True)  # all expired -> sellable 0 -> needs restock

        qs = self.restock_needed_drugs(self.today)
        expected = {d.id for d in Drug.objects.all() if d.needs_restock}
        self.assertEqual(set(qs.values_list('id', flat=True)), expected)
        self.assertEqual(qs.count(), 4)  # everything except "Healthy"

    def test_expired_stock_does_not_mask_low_stock(self):
        # 3 sellable units + 100 expired: sellable is below threshold -> needs restock,
        # even though the raw batch-quantity sum (103) is well above it.
        drug = self._drug("Mixed", 3)
        Batch.objects.create(
            drug=drug, batch_number="EXP", quantity=100,
            purchase_price=Decimal("1"), selling_price=Decimal("2"),
            expiry_date=self.today - timedelta(days=1),
        )
        self.assertIn(drug.id, set(self.restock_needed_drugs(self.today).values_list('id', flat=True)))
