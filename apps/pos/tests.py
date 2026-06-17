from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client

from drugs.models import Drug, Category, Batch
from inventory.models import StockMovement
from pos.models import Sale, SaleItem
from users.models import User


class CheckoutFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="cashier", password="pw12345", role="PHARMACIST"
        )
        self.client = Client()
        self.client.login(username="cashier", password="pw12345")

        self.category = Category.objects.create(name="General")
        self.drug = Drug.objects.create(
            trade_name="Paracetamol", category=self.category, barcode="PARA1"
        )
        self.batch = Batch.objects.create(
            drug=self.drug,
            batch_number="B1",
            purchase_price=Decimal("10.00"),
            selling_price=Decimal("15.00"),
            quantity=20,
            expiry_date=date.today() + timedelta(days=365),
        )

    def _checkout(self, quantity):
        self.client.post("/pos/add-to-cart/", {"drug_id": self.drug.id})
        self.client.post(
            f"/pos/update-cart/{self.drug.id}/", {"quantity": str(quantity)}
        )
        return self.client.post(
            "/pos/checkout/", {"payment_method": "CASH", "discount": "0"}
        )

    def test_checkout_deducts_stock_fifo(self):
        self._checkout(3)
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 17)

    def test_checkout_logs_single_out_movement(self):
        """A sale must log exactly one OUT movement per batch consumed.

        Regression guard: the SaleItem post_save signal used to log a second,
        duplicate movement on top of the one the checkout view records.
        """
        self._checkout(3)
        out_moves = StockMovement.objects.filter(
            drug=self.drug, movement_type="OUT"
        )
        self.assertEqual(out_moves.count(), 1)
        self.assertEqual(sum(m.quantity for m in out_moves), 3)

    def test_refund_restores_stock(self):
        self._checkout(3)
        sale = Sale.objects.get(items__drug=self.drug)
        self.client.post(f"/pos/refund/{sale.id}/")
        self.drug.refresh_from_db()
        sale.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 20)
        self.assertTrue(sale.is_refunded)

    def test_add_to_cart_by_barcode(self):
        self.drug.barcode = "5901234123457"
        self.drug.save()
        r = self.client.post("/pos/add-to-cart/", {"barcode": "5901234123457"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.session["cart"].get(str(self.drug.id), {}).get("quantity"), 1)

    def test_add_to_cart_barcode_is_trimmed_and_case_insensitive(self):
        self.drug.barcode = "AbC123"
        self.drug.save()
        self.client.post("/pos/add-to-cart/", {"barcode": "  abc123  "})
        self.assertIn(str(self.drug.id), self.client.session["cart"])

    def test_add_to_cart_unknown_barcode_is_handled(self):
        r = self.client.post("/pos/add-to-cart/", {"barcode": "does-not-exist"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(str(self.drug.id), self.client.session.get("cart", {}))

    def test_cannot_oversell_beyond_stock(self):
        self.client.post("/pos/add-to-cart/", {"drug_id": self.drug.id})
        self.client.post(
            f"/pos/update-cart/{self.drug.id}/", {"quantity": "999"}
        )
        # cart is capped at available stock (20); checkout should succeed at 20
        self.client.post(
            "/pos/checkout/", {"payment_method": "CASH", "discount": "0"}
        )
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 0)
