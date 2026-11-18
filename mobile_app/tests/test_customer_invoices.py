"""Invoice visibility through the mobile API, with synthetic business records."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from mobile_app import api, billing


class TestCustomerInvoices(unittest.TestCase):
    def setUp(self):
        session = patch.object(billing, "current_customer", return_value="customer-a")
        self.session = session.start()
        self.addCleanup(session.stop)

    def test_list_and_legacy_route_use_session_customer_and_preserve_filters(self):
        with patch.object(frappe, "get_all", return_value=[]) as query:
            for route in (api.get_customer_invoices, api.get_invoices_by_customer_code):
                with self.subTest(route=route):
                    query.reset_mock()
                    result = frappe.call(route, code="code-b", limit="5", offset="10", status="Paid")
                    self.assertEqual(result, {"sales_invoices": [], "pos_invoices": [], "is_search": False})
                    self.assertEqual([c.args[0] for c in query.call_args_list], ["Sales Invoice", "POS Invoice"])
                    for call in query.call_args_list:
                        filters = {"customer": "customer-a", "status": "Paid"}
                        if call.args[0] == "POS Invoice":
                            filters["docstatus"] = 1
                        self.assertEqual(call.kwargs["filters"], filters)
                        self.assertEqual((call.kwargs["limit"], call.kwargs["start"]), (5, 10))

    def test_missing_session_stops_list_and_detail_before_reading_invoices(self):
        self.session.return_value = None
        with patch.object(frappe, "get_all") as listing, patch.object(frappe, "get_doc") as detail:
            expected = {"error": "Invalid session"}
            self.assertEqual(frappe.call(api.get_invoices_by_customer_code, code="code-a"), expected)
            self.assertEqual(api.get_customer_invoices(), expected)
            self.assertEqual(api.get_single_invoice_details("INV-1"), expected)
            listing.assert_not_called()
            detail.assert_not_called()

    def test_detail_checks_both_invoice_types_and_only_returns_visible_documents(self):
        records = [
            ("Sales Invoice", "SALE", "customer-a", 1),
            ("Sales Invoice", "SHARED", "customer-b", 1),
            ("POS Invoice", "SHARED", "customer-a", 1),
            ("POS Invoice", "FOREIGN-POS", "customer-b", 1),
            ("POS Invoice", "DRAFT-POS", "customer-a", 0),
            ("Sales Invoice", "FOREIGN-SALE", "customer-b", 1),
        ]

        def get_doc(doctype, filters):
            for kind, name, owner, status in records:
                fields = {"name": name, "customer": owner, "docstatus": status}
                if kind == doctype and all(fields[k] == v for k, v in filters.items()):
                    item = SimpleNamespace(item_code=kind, qty=2, rate=5, amount=10)
                    return SimpleNamespace(**fields, posting_date="2026-01-01", grand_total=10,
                                           outstanding_amount=0, status="Paid", items=[item])
            raise frappe.DoesNotExistError()

        with patch.object(frappe, "get_doc", side_effect=get_doc):
            for name, kind in (("SALE", "Sales Invoice"), ("SHARED", "POS Invoice")):
                result = api.get_single_invoice_details(name)
                self.assertEqual(result["invoice"]["name"], name)
                self.assertEqual(result["invoice"]["total_qty"], 2)
                self.assertEqual(result["items"][0]["item_code"], kind)
            for name in ("FOREIGN-SALE", "FOREIGN-POS", "DRAFT-POS", "ABSENT"):
                with self.subTest(name=name):
                    self.assertEqual(api.get_single_invoice_details(name), {"error": "Invoice not found"})

    def test_payment_only_includes_references_to_the_paying_customers_invoices(self):
        def get_all(doctype, filters, **kwargs):
            if doctype == "Customer":
                return [frappe._dict(name="customer-a")]
            if doctype == "Payment Entry":
                self.assertEqual(filters, {"party_type": "Customer", "party": "customer-a", "docstatus": 1})
                return [{"name": "PAY"}]
            if doctype == "Payment Entry Reference":
                return [{"parent": "PAY", "reference_name": name, "allocated_amount": 5}
                        for name in ("OWN", "OTHER")]
            self.assertEqual(doctype, "Sales Invoice")
            self.assertEqual(filters["customer"], "customer-a")
            return [{"name": "OWN", "status": "Paid"}]

        with patch.object(frappe, "get_all", side_effect=get_all):
            result = billing.get_payments_by_customer_code("code-a")
        refs = result["payments"][0]["invoices_payed"]
        self.assertEqual([(r["invoice"], r["allocated_amount"]) for r in refs], [("OWN", 5)])
