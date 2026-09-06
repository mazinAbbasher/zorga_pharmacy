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

    def test_purchase_via_view_updates_supplier_balance(self):
        # Regression: the create view saves the purchase once with total_amount=0
        # and again with the real total. The supplier balance must reflect the
        # real total (what we now owe them), not stay at zero.
        self.assertEqual(self.supplier.balance, Decimal("0.00"))
        r = self._post([
            {"drug": self.fifo.id, "batch_number": "", "quantity": 20,
             "purchase_price": "2", "selling_price": "3", "expiry_date": ""},
        ])
        self.assertEqual(r.status_code, 302)
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.balance, Decimal("40.00"))  # 20 * 2

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


class PurchaseSearchTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", role="ADMIN", password="pw12345")
        self.client = Client()
        self.client.login(username="admin", password="pw12345")
        cat = Category.objects.create(name="Meds")
        self.acme = Supplier.objects.create(name="Acme Pharma")
        self.globex = Supplier.objects.create(name="Globex Supplies")
        self.drug = Drug.objects.create(trade_name="Amoxil", category=cat, dispensing_strategy="FIFO")
        self.p1 = Purchase.objects.create(supplier=self.acme, invoice_number="INV-100", received_by=self.admin)
        self.p2 = Purchase.objects.create(supplier=self.globex, invoice_number="INV-200", received_by=self.admin)

    def test_search_by_invoice_number(self):
        r = self.client.get("/purchases/", {"q": "INV-100"})
        self.assertContains(r, "INV-100")
        self.assertNotContains(r, "INV-200")

    def test_search_by_supplier_name(self):
        r = self.client.get("/purchases/", {"q": "Globex"})
        self.assertContains(r, "INV-200")
        self.assertNotContains(r, "INV-100")

    def test_no_query_returns_all(self):
        r = self.client.get("/purchases/")
        self.assertContains(r, "INV-100")
        self.assertContains(r, "INV-200")

    def test_htmx_request_returns_partial(self):
        r = self.client.get("/purchases/", {"q": "INV-100"}, HTTP_HX_REQUEST="true")
        self.assertContains(r, "INV-100")
        self.assertNotContains(r, "INV-200")
        # The partial doesn't extend base.html.
        self.assertNotContains(r, "<html")


class PurchaseEditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="admin", role="ADMIN", password="pw12345")
        self.client = Client()
        self.client.login(username="admin", password="pw12345")
        self.cat = Category.objects.create(name="Meds")
        self.supplier = Supplier.objects.create(name="Acme Pharma")
        self.other_supplier = Supplier.objects.create(name="Globex Supplies")
        self.fifo = Drug.objects.create(trade_name="Cotton", category=self.cat, dispensing_strategy="FIFO")

        self.purchase = Purchase.objects.create(
            supplier=self.supplier, invoice_number="INV-1",
            received_by=self.admin, total_amount=Decimal("20.00"),
        )
        self.item = PurchaseItem.objects.create(
            purchase=self.purchase, drug=self.fifo, batch_number="",
            quantity=10, purchase_price=Decimal("2"), selling_price=Decimal("3"),
            expiry_date=None,
        )
        self.batch = Batch.objects.create(
            drug=self.fifo, batch_number="", purchase_price=Decimal("2"),
            selling_price=Decimal("3"), quantity=10, expiry_date=None,
        )

    def _edit_post(self, lines, initial_forms=1, **header_overrides):
        header = {
            "supplier": self.supplier.id,
            "invoice_number": "INV-1",
            "purchase_date": date.today().isoformat(),
            "items-INITIAL_FORMS": str(initial_forms),
            "items-MIN_NUM_FORMS": "0",
            "items-MAX_NUM_FORMS": "1000",
            "items-TOTAL_FORMS": str(len(lines)),
        }
        header.update(header_overrides)
        data = dict(header)
        for i, line in enumerate(lines):
            for k, v in line.items():
                data[f"items-{i}-{k}"] = v
        return self.client.post(f"/purchases/{self.purchase.id}/edit/", data)

    def _existing_line(self, **overrides):
        line = {
            "id": self.item.id,
            "drug": self.fifo.id,
            "batch_number": "",
            "quantity": self.item.quantity,
            "purchase_price": str(self.item.purchase_price),
            "selling_price": str(self.item.selling_price),
            "expiry_date": "",
        }
        line.update(overrides)
        return line

    def test_get_edit_form_prefills_data(self):
        r = self.client.get(f"/purchases/{self.purchase.id}/edit/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "INV-1")

    def test_header_only_edit_does_not_touch_stock(self):
        r = self._edit_post([self._existing_line()], invoice_number="INV-1-FIXED")
        self.assertEqual(r.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.invoice_number, "INV-1-FIXED")
        self.fifo.refresh_from_db()
        self.assertEqual(self.fifo.total_quantity, 10)  # unchanged

    def test_increase_quantity_updates_stock_and_total(self):
        r = self._edit_post([self._existing_line(quantity=15)])
        self.assertEqual(r.status_code, 302)
        self.fifo.refresh_from_db()
        self.assertEqual(self.fifo.total_quantity, 15)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.total_amount, Decimal("30.00"))  # 15 * 2

    def test_decrease_quantity_updates_stock_and_total(self):
        r = self._edit_post([self._existing_line(quantity=4)])
        self.assertEqual(r.status_code, 302)
        self.fifo.refresh_from_db()
        self.assertEqual(self.fifo.total_quantity, 4)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.total_amount, Decimal("8.00"))  # 4 * 2

    def test_supplier_change_recalculates_both_balances(self):
        self.supplier.refresh_from_db()
        self.assertEqual(self.supplier.balance, Decimal("20.00"))
        r = self._edit_post([self._existing_line()], supplier=self.other_supplier.id)
        self.assertEqual(r.status_code, 302)
        self.supplier.refresh_from_db()
        self.other_supplier.refresh_from_db()
        self.assertEqual(self.supplier.balance, Decimal("0.00"))
        self.assertEqual(self.other_supplier.balance, Decimal("20.00"))

    def test_removing_a_line_reverses_stock(self):
        # A second line so the purchase still has one item left after the delete
        # (removing the only line is rejected, same rule as the create form).
        second_drug = Drug.objects.create(trade_name="Panadol", category=self.cat, dispensing_strategy="FIFO")
        second_item = PurchaseItem.objects.create(
            purchase=self.purchase, drug=second_drug, batch_number="",
            quantity=5, purchase_price=Decimal("1"), selling_price=Decimal("2"),
        )
        r = self._edit_post([
            self._existing_line(DELETE="on"),
            {"id": second_item.id, "drug": second_drug.id, "batch_number": "",
             "quantity": 5, "purchase_price": "1", "selling_price": "2", "expiry_date": ""},
        ], initial_forms=2)
        self.assertEqual(r.status_code, 302)
        self.fifo.refresh_from_db()
        self.assertEqual(self.fifo.total_quantity, 0)
        self.assertFalse(PurchaseItem.objects.filter(pk=self.item.id).exists())

    def test_cannot_remove_the_only_line(self):
        r = self._edit_post([self._existing_line(DELETE="on")])
        self.assertEqual(r.status_code, 200)  # rejected, re-rendered with an error
        self.assertTrue(PurchaseItem.objects.filter(pk=self.item.id).exists())
        self.fifo.refresh_from_db()
        self.assertEqual(self.fifo.total_quantity, 10)  # untouched

    def test_adding_a_new_line_creates_batch(self):
        second_drug = Drug.objects.create(trade_name="Panadol", category=self.cat, dispensing_strategy="FIFO")
        r = self._edit_post([
            self._existing_line(),
            {"drug": second_drug.id, "batch_number": "", "quantity": 5,
             "purchase_price": "1", "selling_price": "2", "expiry_date": ""},
        ], initial_forms=1)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Batch.objects.filter(drug=second_drug).count(), 1)
        second_drug.refresh_from_db()
        self.assertEqual(second_drug.total_quantity, 5)

    def test_items_locked_after_return(self):
        self.item.returned_quantity = 2
        self.item.save()
        r = self.client.get(f"/purchases/{self.purchase.id}/edit/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "already been returned to the supplier")

        # Posting only header fields (no formset data) still succeeds.
        data = {
            "supplier": self.supplier.id,
            "invoice_number": "INV-1-RENAMED",
            "purchase_date": date.today().isoformat(),
        }
        r = self.client.post(f"/purchases/{self.purchase.id}/edit/", data)
        self.assertEqual(r.status_code, 302)
        self.purchase.refresh_from_db()
        self.assertEqual(self.purchase.invoice_number, "INV-1-RENAMED")
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity, 10)  # untouched
