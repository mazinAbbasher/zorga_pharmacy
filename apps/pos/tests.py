from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, Client

from drugs.models import Drug, Category, Batch
from inventory.models import StockMovement
from pos.models import Sale, SaleItem
from pos.analytics import net_revenue, sales_summary
from users.models import User
from customers.models import Customer


class SaleReturnTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cash", password="pw12345", role="PHARMACIST")
        self.client = Client()
        self.client.login(username="cash", password="pw12345")
        self.cat = Category.objects.create(name="General")
        self.drug = Drug.objects.create(trade_name="Panadol", category=self.cat)
        self.batch = Batch.objects.create(
            drug=self.drug, batch_number="B1", purchase_price=Decimal("5"),
            selling_price=Decimal("10"), quantity=10,
            expiry_date=date.today() + timedelta(days=200),
        )

    def _sale(self, qty=4, customer=None, method="CASH"):
        sale = Sale.objects.create(cashier=self.user, customer=customer,
                                   total_amount=Decimal("10") * qty, payment_method=method)
        SaleItem.objects.create(sale=sale, drug=self.drug, quantity=qty,
                                unit_price=Decimal("10"), unit_cost=Decimal("5"))
        return sale

    def test_partial_return_restores_stock(self):
        self.batch.quantity = 6  # 4 were sold
        self.batch.save()
        sale = self._sale(qty=4)
        r = self.client.post(f"/pos/return/{sale.id}/", {f"return_qty_{sale.items.first().id}": "2"})
        self.assertEqual(r.status_code, 200)
        self.drug.refresh_from_db()
        self.assertEqual(self.drug.total_quantity, 8)  # 6 + 2 returned
        item = sale.items.first(); item.refresh_from_db()
        self.assertEqual(item.returned_quantity, 2)
        sale.refresh_from_db()
        self.assertFalse(sale.is_refunded)
        self.assertTrue(sale.is_partially_refunded)

    def test_full_return_marks_refunded(self):
        sale = self._sale(qty=3)
        self.client.post(f"/pos/return/{sale.id}/", {f"return_qty_{sale.items.first().id}": "3"})
        sale.refresh_from_db()
        self.assertTrue(sale.is_refunded)

    def test_cannot_return_more_than_sold(self):
        sale = self._sale(qty=2)
        self.client.post(f"/pos/return/{sale.id}/", {f"return_qty_{sale.items.first().id}": "99"})
        item = sale.items.first(); item.refresh_from_db()
        self.assertEqual(item.returned_quantity, 2)  # capped at sold qty

    def test_credit_sale_return_reduces_customer_balance(self):
        cust = Customer.objects.create(name="Ali")
        sale = self._sale(qty=4, customer=cust, method="CREDIT")
        cust.refresh_from_db()
        self.assertEqual(cust.outstanding_balance, Decimal("40"))  # 4 * 10
        self.client.post(f"/pos/return/{sale.id}/", {f"return_qty_{sale.items.first().id}": "1"})
        cust.refresh_from_db()
        self.assertEqual(cust.outstanding_balance, Decimal("30"))  # one unit returned


class SalesAnalyticsTests(TestCase):
    """Dashboard/reports figures must be net of discounts and partial returns."""

    def setUp(self):
        self.user = User.objects.create_user(username="an", password="pw12345", role="ADMIN")
        self.cat = Category.objects.create(name="General")
        self.drug = Drug.objects.create(trade_name="Panadol", category=self.cat)
        self.today = date.today()

    def _sale(self, qty=4, discount=Decimal("0"), refunded=False):
        sale = Sale.objects.create(
            cashier=self.user, total_amount=Decimal("10") * qty,
            discount=discount, is_refunded=refunded,
        )
        SaleItem.objects.create(
            sale=sale, drug=self.drug, quantity=qty,
            unit_price=Decimal("10"), unit_cost=Decimal("6"),
        )
        return sale

    def test_net_revenue_subtracts_discount(self):
        self._sale(qty=4, discount=Decimal("5"))  # 40 - 5
        self.assertEqual(net_revenue(self.today, self.today), Decimal("35"))

    def test_net_revenue_excludes_fully_refunded_sales(self):
        self._sale(qty=4)              # 40
        self._sale(qty=2, refunded=True)  # excluded
        self.assertEqual(net_revenue(self.today, self.today), Decimal("40"))

    def test_net_revenue_subtracts_partial_returns(self):
        sale = self._sale(qty=4)  # 40
        item = sale.items.first()
        item.returned_quantity = 1  # 10 returned -> net 30
        item.save()
        self.assertEqual(net_revenue(self.today, self.today), Decimal("30"))

    def test_summary_profit_and_cost_net_of_returns(self):
        sale = self._sale(qty=4)  # rev 40, cost 24
        item = sale.items.first()
        item.returned_quantity = 1  # return 1 unit: -10 rev, -6 cost
        item.save()
        summary = sales_summary(self.today, self.today)
        self.assertEqual(summary['revenue'], Decimal("30"))
        self.assertEqual(summary['cost'], Decimal("18"))   # 3 units * 6
        self.assertEqual(summary['profit'], Decimal("12"))  # 30 - 18

    def test_summary_matches_model_net_profit_with_partial_return(self):
        sale = self._sale(qty=4, discount=Decimal("5"))
        item = sale.items.first()
        item.returned_quantity = 1
        item.save()
        summary = sales_summary(self.today, self.today)
        # The aggregate must agree with the per-sale model property.
        self.assertEqual(summary['profit'], sale.net_profit)


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

    def test_clear_cart_empties_everything(self):
        self.client.post("/pos/add-to-cart/", {"drug_id": self.drug.id})
        self.assertIn(str(self.drug.id), self.client.session["cart"])
        r = self.client.post("/pos/clear-cart/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.session.get("cart", {}), {})

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
