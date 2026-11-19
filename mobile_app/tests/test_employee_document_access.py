"""Read permissions on individual stock entries and material requests."""

import unittest
from unittest.mock import Mock, patch

import frappe

from mobile_app import api, material_requests, stock


class TestEmployeeDocumentAccess(unittest.TestCase):
    routes = (
        (stock, api.get_stock_entry_details_by_name, "Stock Entry", "stockEntry"),
        (material_requests, api.get_material_request_detail, "Material Request", "material_request"),
    )

    def test_document_permission_controls_read_for_each_detail_route(self):
        for module, route, doctype, key in self.routes:
            with self.subTest(doctype=doctype), \
                    patch.object(module, "authenticate_employee", return_value="employee"), \
                    patch.object(frappe, "get_doc") as load:
                doc = load.return_value
                doc.name = "TEST-001"
                doc.docstatus = 0
                doc.items = []
                doc.get.return_value = []
                result = route(token="sid", name=doc.name)
                load.assert_called_once_with(doctype, doc.name)
                doc.check_permission.assert_called_once_with("read")
                self.assertEqual(result[key]["name"], doc.name)
                self.assertEqual(result["items"], [])

                denied_doc = Mock()
                denied_doc.docstatus = 2
                denied_doc.check_permission.side_effect = frappe.PermissionError
                load.return_value = denied_doc
                denied = route(token="sid", name="TEST-002")
                denied_doc.check_permission.assert_called_once_with("read")
                self.assertEqual(denied["error"], "Access denied")
                self.assertNotIn(key, denied)
                self.assertNotIn("items", denied)

    def test_invalid_session_and_missing_documents_preserve_errors(self):
        for module, route, doctype, key in self.routes:
            with self.subTest(doctype=doctype), patch.object(module, "authenticate_employee") as auth, \
                    patch.object(frappe, "get_doc", side_effect=frappe.DoesNotExistError) as load:
                auth.return_value = None
                self.assertEqual(route(token="", name="TEST")["error"], "Invalid session")
                load.assert_not_called()
                auth.return_value = "employee"
                self.assertEqual(route(token="sid", name="TEST")["error"], f"{doctype} not found")
