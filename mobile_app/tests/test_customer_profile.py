"""Customer identity and profile fields returned by both public profile routes."""

import unittest
from unittest.mock import patch

import frappe

from mobile_app import api, customer_sessions


class TestCustomerProfile(unittest.TestCase):
    def test_profile_uses_only_the_session_owner_and_excludes_the_personal_code(self):
        for route in (api.get_customer_profile, api.get_client_by_code):
            with self.subTest(route=route), \
                    patch.object(customer_sessions, "current_customer", return_value="customer-a"), \
                    patch.object(frappe.db, "get_value", return_value={"name": "customer-a"}) as query:
                result = frappe.call(route, customer="customer-b", code="other-code")
                self.assertEqual(result, {"customer": {"name": "customer-a"}})
                doctype, filters, fields = query.call_args.args
                self.assertEqual((doctype, filters), ("Customer", {"name": "customer-a", "disabled": 0}))
                self.assertIn("custom_debt", fields)
                self.assertNotIn("custom_customer_code", fields)
                query.return_value = None
                self.assertEqual(route(), {"error": "Invalid session"})

    def test_code_alone_does_not_open_either_profile_route(self):
        with patch.object(frappe, "get_request_header", return_value=""), patch.object(frappe.db, "get_value") as query:
            for route in (api.get_customer_profile, api.get_client_by_code):
                self.assertEqual(frappe.call(route, code="stored-code"), {"error": "Invalid session"})
            query.assert_not_called()
