"""Customer code assignment through ERPNext and the mobile API."""

import unittest
from unittest.mock import patch
from uuid import uuid4

import frappe

from mobile_app import customers


class TestCustomerCodes(unittest.TestCase):
    def setUp(self):
        previous_user = frappe.session.user
        frappe.set_user("Administrator")
        self.addCleanup(frappe.set_user, previous_user)
        frappe.db.savepoint("customer_code_test")
        self.addCleanup(frappe.db.rollback, save_point="customer_code_test")
        self.prefix = "test-code-" + uuid4().hex

    def customer(self, suffix, code):
        return frappe.get_doc({
            "doctype": "Customer", "customer_name": self.prefix + suffix,
            "customer_type": "Company", "custom_customer_code": code,
        }).insert(ignore_permissions=True)

    def test_creating_and_editing_customers_refuses_codes_already_assigned(self):
        code = self.prefix + "-a"
        owner = self.customer("A", code)
        other = self.customer("B", self.prefix + "-b")
        with self.assertRaises(frappe.ValidationError):
            self.customer("C", code)
        owner.disabled = 1
        owner.save()
        other.custom_customer_code = " " + code + " "
        with self.assertRaises(frappe.ValidationError):
            other.save()
        other.reload()
        self.assertEqual(other.custom_customer_code, self.prefix + "-b")
        other.custom_customer_code = self.prefix + "-new"
        other.save()
        other.reload()
        self.assertEqual(other.custom_customer_code, self.prefix + "-new")

    def test_preexisting_shared_code_can_be_kept_or_corrected(self):
        code = self.prefix + "-legacy"
        owner = self.customer("A", code)
        other = self.customer("B", self.prefix + "-b")
        # Model historical duplicates only inside this rolled-back test transaction.
        frappe.db.set_value("Customer", other.name, "custom_customer_code", code)
        owner.reload()
        owner.save()
        other.reload()
        other.custom_customer_code = self.prefix + "-replacement"
        other.save()
        with self.assertRaises(frappe.ValidationError):
            self.customer("C", code)
        owner.reload()
        self.assertEqual(owner.custom_customer_code, code)

    def test_multiple_customers_can_be_saved_without_a_code(self):
        for suffix in ("A", "B"):
            customer = self.customer(suffix, "  ")
            customer.reload()
            self.assertFalse(customer.custom_customer_code)

    def test_mobile_rejects_an_existing_code_and_accepts_an_unused_one(self):
        old = self.prefix + "-a"
        taken = self.prefix + "-b"
        owner = self.customer("A", old)
        self.customer("B", taken)
        with patch.object(frappe.db, "commit") as commit, \
                patch.object(customers.customer_sessions, "invalidate_all") as invalidate:
            denied = customers.change_customer_code(old, taken)
            self.assertEqual(denied, {"success": False, "error": customers.CODE_ALREADY_USED})
            owner.reload()
            self.assertEqual(owner.custom_customer_code, old)
            commit.assert_not_called()
            invalidate.assert_not_called()
            result = customers.change_customer_code(old, self.prefix + "-unused")
            self.assertTrue(result["success"])
            invalidate.assert_called_once_with(owner.name)
            owner.reload()
            self.assertEqual(owner.custom_customer_code, self.prefix + "-unused")
