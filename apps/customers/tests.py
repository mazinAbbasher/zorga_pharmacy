from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from users.models import User
from customers.models import Customer, CustomerPayment
from drugs.models import Drug, Category
from pos.models import Sale, SaleItem


class PaymentHistoryLedgerTests(TestCase):
    """The credit ledger must reconcile with the customer's outstanding balance,
    including when items have been partially returned."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin", role="ADMIN", password="pw12345"
        )
        self.client = Client()
        self.client.login(username="admin", password="pw12345")
        self.cat = Category.objects.create(name="General")
        self.drug = Drug.objects.create(trade_name="Panadol", category=self.cat)
        self.customer = Customer.objects.create(name="Ali")

    def _credit_sale(self, qty=4, discount=Decimal("0")):
        sale = Sale.objects.create(
            cashier=self.admin, customer=self.customer, payment_method="CREDIT",
            total_amount=Decimal("10") * qty, discount=discount,
        )
        SaleItem.objects.create(
            sale=sale, drug=self.drug, quantity=qty,
            unit_price=Decimal("10"), unit_cost=Decimal("6"),
        )
        return sale

    def _ledger(self):
        resp = self.client.get(reverse("customers:payment_history", args=[self.customer.id]))
        return resp.context["ledger"]

    def _net(self, ledger):
        debt = sum(e["amount"] for e in ledger if e["type"] == "DEBT")
        credit = sum(e["amount"] for e in ledger if e["type"] in ("RETURN", "CREDIT"))
        return debt - credit

    def test_ledger_reconciles_with_balance_after_partial_return(self):
        sale = self._credit_sale(qty=4)  # owes 40
        item = sale.items.first()
        item.returned_quantity = 1  # return one unit (worth 10)
        item.save()
        sale.save()  # triggers customer-balance recalculation
        CustomerPayment.objects.create(customer=self.customer, amount=Decimal("5"))

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.outstanding_balance, Decimal("25"))  # 40 - 10 - 5

        ledger = self._ledger()
        self.assertEqual(self._net(ledger), self.customer.outstanding_balance)
        # The return is shown as its own credit line.
        self.assertEqual(sum(1 for e in ledger if e["type"] == "RETURN"), 1)

    def test_ledger_reconciles_without_returns(self):
        self._credit_sale(qty=3)  # owes 30
        CustomerPayment.objects.create(customer=self.customer, amount=Decimal("10"))

        self.customer.refresh_from_db()
        ledger = self._ledger()
        self.assertEqual(self._net(ledger), self.customer.outstanding_balance)
        self.assertEqual(sum(1 for e in ledger if e["type"] == "RETURN"), 0)
