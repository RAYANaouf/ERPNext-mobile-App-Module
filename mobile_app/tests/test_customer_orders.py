"""Customer order isolation. Uses ephemeral Redis keys and no business records."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import frappe
from werkzeug.wrappers import Response

from mobile_app import customer_sessions as sessions, customers, orders


class TestCustomerOrders(unittest.TestCase):
    def setUp(self):
        self.owner = "mobile-order-test-" + uuid4().hex
        self.code = uuid4().hex
        self.token = sessions.issue(self.owner, self.code)
        self.addCleanup(frappe.cache.delete, sessions._session_key(self.token), sessions._generation_key(self.owner))
        self.header = self._patch(frappe, "get_request_header", return_value=self.token)
        self.lookup = self._patch(frappe.db, "get_value", return_value=self.code)

    def _patch(self, obj, name, **options):
        patcher = patch.object(obj, name, **options)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_only_orders_of_the_session_customer_are_visible(self):
        with patch.object(frappe, "get_all", return_value=[]) as query:
            self.assertEqual(orders.get_customer_orders()["orders"], [])
            self.assertEqual(query.call_args.kwargs["filters"], {"customer": self.owner})
        order = SimpleNamespace(customer=self.owner, name="TEST", grand_total=5, items=[])
        with patch.object(frappe, "get_doc", return_value=order) as read:
            self.assertEqual(orders.get_order_details("TEST")["grand_total"], 5)
            order.customer = "other-customer"
            denied = orders.get_order_details("TEST")
            read.side_effect = frappe.DoesNotExistError()
            self.assertEqual(denied, orders.get_order_details("absent"))
            self.assertNotIn("items", denied)
        self.lookup.assert_called_with("Customer", {"name": self.owner, "disabled": 0}, "custom_customer_code")
        response = Response()
        sessions.protect_response(response)
        self.assertTrue(response.cache_control.no_store)

    def test_creation_uses_session_owner_even_if_body_names_another_customer(self):
        with patch.object(orders, "frappe") as db_api:
            db_api.request = None
            db_api.form_dict = {"customer_code": "other-code", "customer": "other", "items": [{"item_code": "TEST"}]}
            db_api.db.get_value.return_value = 1
            doc = Mock()
            doc.name = "ORDER-TEST"
            db_api.get_doc.return_value = doc
            self.assertEqual(orders.create_sales_order()["order_id"], doc.name)
            self.assertEqual(db_api.get_doc.call_args.args[0]["customer"], self.owner)
            doc.submit.assert_called_once()

    def test_missing_expired_and_logged_out_sessions_are_refused(self):
        for token in ("", self.code):
            self.header.return_value = token
            self.assertEqual(orders.get_customer_orders(), {"error": "Invalid session"})
        self.header.return_value = self.token
        ttl = frappe.cache.ttl(sessions._session_key(self.token))
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, sessions.SESSION_SECONDS)
        sessions.logout_customer()
        self.assertEqual(orders.get_order_details("TEST"), {"error": "Invalid session"})
        token = sessions.issue(self.owner, self.code)
        self.addCleanup(frappe.cache.delete, sessions._session_key(token))
        frappe.cache.expire(sessions._session_key(token), 0)
        self.header.return_value = token
        self.assertEqual(orders.create_sales_order(), {"error": "Invalid session"})

    def test_disabled_account_and_changed_code_invalidate_session(self):
        self.lookup.return_value = None
        self.assertIsNone(sessions.current_customer())
        self.lookup.return_value = "new-code"
        self.assertIsNone(sessions.current_customer())
        sessions.invalidate_all(self.owner)
        self.lookup.return_value = self.code
        self.assertIsNone(sessions.current_customer())

    def test_login_requires_one_exact_personal_code(self):
        row = frappe._dict(name=self.owner, custom_customer_code=self.code)
        with patch.object(frappe, "get_all", return_value=[row]) as query:
            self.assertIs(customers._profile_for_code(self.code), row)
            self.assertIsNone(customers._profile_for_code(self.code + "x"))
            self.assertIsNone(customers._profile_for_code([]))
            query.return_value = [row, row]
            self.assertIsNone(customers._profile_for_code(self.code))
