from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client

from drugs.models import Drug, Category, Batch
from suppliers.models import Supplier
from users.models import User
from purchases.models import Purchase, PurchaseItem


class PurchaseFlowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin", role="ADMIN", password="pw12345"
        )
        self.client = Client()
        self.client.login(username="admin", password="pw12345")

        self.cat = Category.objects.create(name="Meds")
        self.supplier = Supplier.objects.create(name="Acme Pharma")
        self.fefo = Drug.objects.create(trade_name="Amoxil", category=self.cat, dispensing_strategy="FEFO")
        self.fifo = Drug.objects.create(trade_name="Cotton", category=self.cat, dispensing_strategy="FIFO")
        self.exp = (date.today() + timedelta(days=200)).isoformat()

    def _post(self, lines, total_forms=None):
        data = {
            "supplier": self.supplier.id,
            "invoice_number": "INV-1",
            "purchase_date": date.today().isoformat(),
            "items-INITIAL_FORMS": "0",
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-TOTAL_FORMS": str(total_forms if total_forms is not None else len(lines)),
        }
        for i, line in enumerate(lines):
            for k, v in line.items():
                data[f"items-{i}-{k}"] = v
        return self.client.post("/purchases/add/", data)

    def test_multi_line_purchase_creates_batches(self):
        r = self._post([
            {"drug": self.fefo.id, "batch_number": "B1", "quantity": 10,
             "purchase_price": "5", "selling_price": "8", "expiry_date": self.exp},
            {"drug": self.fifo.id, "batch_number": "", "quantity": 20,
             "purchase_price": "2", "selling_price": "3", "expiry_date": ""},
        ])
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Purchase.objects.count(), 1)
        self.assertEqual(PurchaseItem.objects.count(), 2)
        self.assertEqual(Batch.objects.filter(drug=self.fefo).count(), 1)
        self.assertEqual(Batch.objects.filter(drug=self.fifo).count(), 1)
        # grand total = 10*5 + 20*2 = 90
        self.assertEqual(Purchase.objects.first().total_amount, Decimal("90.00"))

    def test_fefo_requires_batch_and_expiry(self):
        r = self._post([
            {"drug": self.fefo.id, "batch_number": "", "quantity": 5,
             "purchase_price": "5", "selling_price": "8", "expiry_date": ""},
        ])
        self.assertEqual(r.status_code, 200)  # re-rendered with errors
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertContains(r, "required for FEFO")

    def test_fifo_ignores_batch_number(self):
        # Even if a batch number is sent for a FIFO item, it is stored blank.
        r = self._post([
            {"drug": self.fifo.id, "batch_number": "SHOULD-IGNORE", "quantity": 7,
             "purchase_price": "2", "selling_price": "3", "expiry_date": ""},
        ])
        self.assertEqual(r.status_code, 302)
        batch = Batch.objects.get(drug=self.fifo)
        self.assertEqual(batch.batch_number, "")
        self.assertIsNone(batch.expiry_date)

    def test_fefo_dispenses_by_expiry_not_received_order(self):
        # Older-received batch with LATER expiry, newer batch with SOONER expiry.
        today = date.today()
        Batch.objects.create(drug=self.fefo, batch_number="OLD",
                             purchase_price=1, selling_price=2, quantity=5,
                             expiry_date=today + timedelta(days=300))
        Batch.objects.create(drug=self.fefo, batch_number="NEW",
                             purchase_price=1, selling_price=2, quantity=5,
                             expiry_date=today + timedelta(days=30))
        first = self.fefo.active_batches().first()
        self.assertEqual(first.batch_number, "NEW")  # nearest expiry first

    def test_fifo_dispenses_by_received_order(self):
        b1 = Batch.objects.create(drug=self.fifo, purchase_price=1, selling_price=2,
                                  quantity=5, expiry_date=None)
        Batch.objects.create(drug=self.fifo, purchase_price=1, selling_price=2,
                             quantity=5, expiry_date=None)
        first = self.fifo.active_batches().first()
        self.assertEqual(first.id, b1.id)  # oldest received first

    def test_no_expiry_counts_as_in_stock(self):
        Batch.objects.create(drug=self.fifo, purchase_price=1, selling_price=2,
                             quantity=15, expiry_date=None)
        self.assertEqual(self.fifo.total_quantity, 15)


class PurchaseReturnTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", role="ADMIN", password="pw12345")
        self.client = Client()
        self.client.login(username="admin", password="pw12345")
        self.cat = Category.objects.create(name="Meds")
        self.supplier = Supplier.objects.create(name="Acme")
        self.drug = Drug.objects.create(trade_name="Amoxil", category=self.cat, dispensing_strategy="FEFO")
        self.exp = date.today() + timedelta(days=200)

        # Record a purchase (signal adds to supplier balance), create the batch.
        self.purchase = Purchase.objects.create(
            supplier=self.supplier, invoice_number="INV-1",
            received_by=self.admin, total_amount=Decimal("100"),
        )
        self.item = PurchaseItem.objects.create(
            purchase=self.purchase, drug=self.drug, batch_number="B1",
            quantity=10, purchase_price=Decimal("10"), selling_price=Decimal("15"),
            expiry_date=self.exp,
        )
        self.batch = Batch.objects.create(
            drug=self.drug, batch_number="B1", purchase_price=Decimal("10"),
            selling_price=Decimal("15"), quantity=10, expiry_date=self.exp,
        )

    def test_partial_purchase_return_reduces_stock(self):
        r = self.client.post(f"/purchases/return/{self.purchase.id}/",
                             {f"return_qty_{self.item.id}": "4"})
        self.assertEqual(r.status_code, 200)
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 6)  # 10 - 4
        self.item.refresh_from_db()
        self.assertEqual(self.item.returned_quantity, 4)

    def test_purchase_return_reduces_supplier_balance(self):
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.balance, Decimal("100"))
        self.client.post(f"/purchases/return/{self.purchase.id}/",
                         {f"return_qty_{self.item.id}": "5"})
        self.supplier.refresh_from_db()
        # net purchase = 100 - (5 * 10) = 50
        self.assertEqual(self.supplier.balance, Decimal("50"))

    def test_cannot_return_more_than_in_stock(self):
        self.batch.quantity = 3  # only 3 left (rest sold)
        self.batch.save()
        self.client.post(f"/purchases/return/{self.purchase.id}/",
                         {f"return_qty_{self.item.id}": "10"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.returned_quantity, 3)  # only what was in stock
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 0)
