"""Mobile audience, pricing and employee item permissions with synthetic records."""

import unittest
from unittest.mock import patch

import frappe

from mobile_app import api, catalog, communications


class TestCustomerCatalogCommunications(unittest.TestCase):
    def test_guest_and_code_only_calls_do_not_read_customer_data(self):
        routes = (
            api.get_customer_notifications, api.get_notification_by_customer_code,
            api.get_customer_announcements, api.get_announcements_by_customer_code,
            api.get_customer_items, api.get_items_by_customer_code, api.search_customer_items,
        )
        with patch.object(frappe, "get_request_header", return_value=""), \
                patch.object(frappe, "get_all") as records:
            for route in routes:
                with self.subTest(route=route):
                    result = frappe.call(route, customer_code="old-code", code="old-code", search_text="TEST")
                    self.assertEqual(result, {"error": "Invalid session"})
            records.assert_not_called()

    def test_personal_notifications_are_filtered_by_the_session(self):
        with patch.object(communications, "current_customer", return_value="A"), \
                patch.object(frappe, "get_all", return_value=[{"title": "Test"}]) as records:
            result = frappe.call(api.get_notification_by_customer_code, code="B")
            self.assertEqual(result, {"notification": [{"title": "Test"}]})
            self.assertEqual(records.call_args.kwargs["filters"], {"customer": "A", "docstatus": 1})

    def test_announcement_exclusions_and_visibility_precede_pagination(self):
        names = ["only-B", "both", "public", "only-A", "banned-B"]
        announcements = [frappe._dict(name=name, title=name) for name in names]
        audience = [frappe._dict(parent=name, parentfield=field, customer=customer)
                    for name, field, customer in (("only-B", "allowed", "B"), ("both", "allowed", "A"),
                                                  ("both", "banned", "A"), ("only-A", "allowed", "A"),
                                                  ("banned-B", "banned", "B"))]
        with patch.object(communications, "current_customer", return_value="A"), \
                patch.object(frappe, "get_all", side_effect=[announcements, audience]) as records:
            page = frappe.call(api.get_announcements_by_customer_code, code="B", limit=2, offset=1)
            self.assertEqual(page["total_count"], 3)
            self.assertEqual([a["id"] for a in page["announcements"]], ["only-A", "banned-B"])
            today = frappe.utils.today()
            self.assertEqual(records.call_args_list[0].kwargs["filters"],
                             [["docstatus", "=", 1], ["publish_date", "<=", today], ["expiry_date", ">=", today]])
            child_filters = records.call_args_list[1].kwargs["filters"]
            self.assertEqual(child_filters["parenttype"], "Annonce mobile")
            self.assertEqual(child_filters["parent"], ["in", names])

    def test_catalog_and_search_apply_the_same_customer_price_and_public_fallback(self):
        def get_all(doctype, filters, **options):
            if doctype == "Item":
                return [{"item_code": code, "item_name": code} for code in ("X", "Y", "Z")]
            self.assertEqual(doctype, "Item Price")
            prices = {"A-list": {"X": 8}, catalog.PUBLIC_PRICE_LIST: {"X": 15, "Y": 12}}
            self.assertEqual(filters["price_list"], ["in", ["A-list", catalog.PUBLIC_PRICE_LIST]])
            return [{"item_code": code, "price_list": name, "price_list_rate": rate}
                    for name, entries in prices.items() for code, rate in entries.items()]

        with patch.object(catalog, "current_customer", return_value="A"), \
                patch.object(frappe.db, "get_value", return_value="A-list") as lookup, \
                patch.object(frappe, "get_all", side_effect=get_all):
            page = frappe.call(api.get_items_by_customer_code, customer_code="B")
            search = frappe.call(api.search_customer_items, search_text="Lens", customer_code="B")
            self.assertEqual(page["price_list"], "A-list")
            self.assertEqual([item["rate"] for item in page["items"]], [8, 12, 0])
            self.assertEqual([item["standard_rate"] for item in search], [8, 12, 0])
            for call in lookup.call_args_list:
                self.assertEqual(call.args, ("Customer", "A", "default_price_list"))

    def test_employee_search_requires_a_valid_employee_and_uses_erp_permissions(self):
        with patch.object(catalog, "authenticate_employee") as auth, \
                patch.object(frappe, "get_cached_value", return_value=1) as enabled, \
                patch.object(frappe, "get_list", return_value=[{"item_code": "X", "item_name": "Lens"}]) as items, \
                patch.object(frappe, "get_all") as unrestricted:
            for user in (None, "Guest"):
                auth.return_value = user
                self.assertEqual(api.search_items(search_text="Lens", token="sid"), {"error": "Invalid session"})
            auth.return_value = "employee"
            enabled.return_value = 0
            self.assertEqual(api.search_employee_items(search_text="Lens", token="sid"), {"error": "Invalid session"})
            items.assert_not_called()
            enabled.return_value = 1
            self.assertEqual(api.search_employee_items(search_text="Lens", token="sid"), items.return_value)
            self.assertEqual(items.call_args.args, ("Item",))
            self.assertEqual(items.call_args.kwargs["fields"], ["item_code", "item_name"])
            items.side_effect = frappe.PermissionError
            self.assertEqual(api.search_employee_items(search_text="Lens", token="sid"), {"error": "Access denied"})
            unrestricted.assert_not_called()
