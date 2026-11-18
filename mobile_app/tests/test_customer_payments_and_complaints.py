"""Session ownership on payment reads and complaint creation."""

import unittest
from unittest.mock import patch

import frappe

from mobile_app import api, billing, customer_sessions


class TestCustomerPaymentsAndComplaints(unittest.TestCase):
    def test_payment_routes_keep_the_session_owner_during_paging_and_search(self):
        with patch.object(billing, "current_customer", return_value="customer-a"), \
                patch.object(frappe, "get_all", return_value=[]) as query:
            for route in (api.get_customer_payments, api.get_payments_by_customer_code):
                for search, limit, offset in ((None, 5, 10), ("PAY", 20, 0)):
                    with self.subTest(route=route, search=search):
                        result = frappe.call(route, code="code-b", limit="5", offset="10", search_text=search)
                        self.assertEqual(result, {"payments": [], "is_search": bool(search)})
                        self.assertEqual(query.call_args.args, ("Payment Entry",))
                        filters = {"party_type": "Customer", "party": "customer-a", "docstatus": 1}
                        if search:
                            filters["name"] = ["like", "%PAY%"]
                        self.assertEqual(query.call_args.kwargs["filters"], filters)
                        self.assertEqual(query.call_args.kwargs["limit"], limit)
                        self.assertEqual(query.call_args.kwargs["start"], offset)

    def test_missing_session_prevents_payment_reads_and_complaint_writes(self):
        with patch.object(frappe, "get_request_header", return_value=""), \
                patch.object(frappe, "get_all") as query, patch.object(frappe, "get_doc") as create:
            self.assertEqual(frappe.call(api.get_payments_by_customer_code, code="code-a"),
                             {"error": "Invalid session"})
            self.assertEqual(frappe.call(api.create_customer_complaint, client="customer-a", description="Hello"),
                             {"error": "Invalid session"})
            query.assert_not_called()
            create.assert_not_called()

    def test_complaint_is_attributed_to_session_on_each_supported_doctype(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy), \
                    patch.object(customer_sessions, "current_customer", return_value="customer-a"), \
                    patch.object(frappe.db, "exists", return_value=legacy), \
                    patch.object(frappe.db, "get_single_value", return_value="configured-company"), \
                    patch.object(frappe, "get_doc") as create:
                create.return_value.name = "COMPLAINT"
                result = frappe.call(api.create_customer_complaint, client="customer-b", company="another-company",
                                     description="Test description", date_reception="2026-01-02", reference="REF")
                self.assertEqual(result, {"message": "Success", "id": "COMPLAINT"})
                fields = create.call_args.args[0]
                if legacy:
                    self.assertEqual(fields, {"doctype": "reclamtion client", "client": "customer-a",
                                              "date_reception": "2026-01-02", "documents_reference": "REF",
                                              "desciption_reclamation": "Test description"})
                else:
                    self.assertEqual(fields, {"doctype": "Customer Complaint", "customer": "customer-a",
                                              "source_type": "Client", "company": "configured-company",
                                              "receipt_date": "2026-01-02", "reference_documents": "REF",
                                              "complaint_description": "Test description"})
                create.return_value.insert.assert_called_once_with(ignore_permissions=True)

    def test_incomplete_complaint_returns_an_error_before_insert(self):
        with patch.object(customer_sessions, "current_customer", return_value="customer-a"), \
                patch.object(frappe.db, "exists", return_value=False), \
                patch.object(frappe.db, "get_single_value", return_value=None), \
                patch.object(frappe, "get_doc") as create:
            self.assertIn("error", api.create_customer_complaint(description=" "))
            self.assertIn("error", api.create_customer_complaint(description="Test description"))
            create.assert_not_called()
