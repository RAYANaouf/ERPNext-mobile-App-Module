"""Task API integration tests. All writes are rolled back, including test users."""
import unittest
from unittest.mock import patch
import frappe
from frappe.utils import add_days, today
from mobile_app import api
from mobile_app import employee_tasks as tasks


class TestEmployeeTasks(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.savepoint("employee_task_test")
        self.previous_test_flag = frappe.flags.in_test
        frappe.flags.in_test = True
        self.prefix = "mobile-task-test-" + frappe.generate_hash(length=8)
        self.author = self._user("author", ["Projects User"])
        self.colleague = self._user("colleague", ["Projects User"])
        self.reader = self._user("reader", [])
        self.auth = patch.object(api, "authenticate_employee", self._authenticate)
        self.notify = patch("frappe.desk.form.assign_to.notify_assignment")
        self.auth.start()
        self.notify.start()

    def tearDown(self):
        self.notify.stop()
        self.auth.stop()
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point="employee_task_test")
        frappe.flags.in_test = self.previous_test_flag

    def _user(self, suffix, roles):
        name = f"{self.prefix}-{suffix}@example.invalid"
        frappe.get_doc({"doctype": "User", "email": name, "first_name": suffix,
                        "enabled": 1, "send_welcome_email": 0,
                        "roles": [{"role": role} for role in roles]}).insert(ignore_permissions=True)
        return name

    def _authenticate(self, token):
        if token not in (self.author, self.colleague, self.reader):
            return None
        frappe.set_user(token)
        return token

    def _create(self, **values):
        response = tasks.create_task(token=self.author, subject=self.prefix,
                                     assignees=[self.author, self.colleague], **values)
        self.assertNotIn("error", response, response)
        return response["task"]

    def test_multiple_assignees_urgent_and_progress(self):
        task = self._create(priority="Urgent")
        self.assertEqual(task["priority"], "Urgent")
        self.assertEqual({u["name"] for u in task["assignees"]}, {self.author, self.colleague})
        result = tasks.update_task(token=self.author, name=task["name"],
                                   modified=task["modified"], status="Working", progress=35)
        self.assertNotIn("error", result, result)
        self.assertEqual(result["task"]["status"], "Working")
        self.assertEqual(result["task"]["progress"], 35)

    def test_completion_preserves_history_for_each_assignee(self):
        task = self._create()
        result = tasks.update_task(token=self.author, name=task["name"], status="Completed")
        self.assertNotIn("error", result, result)
        self.assertEqual(result["task"]["progress"], 100)
        self.assertEqual(result["task"]["assignees"], [])
        self.assertEqual(len(result["task"]["previous_assignees"]), 2)
        for user in (self.author, self.colleague):
            listed = tasks.get_tasks(token=user, scope="mine", status="Completed", search_text=self.prefix)
            self.assertEqual([r["name"] for r in listed["tasks"]], [task["name"]])
        reopened = tasks.update_task(token=self.author, name=task["name"], status="Open")
        self.assertNotIn("error", reopened, reopened)
        self.assertEqual(reopened["task"]["assignees"], [])

    def test_totals_and_overdue_filter_before_pagination(self):
        for priority in ("Low", "High", "Urgent"):
            self._create(priority=priority, exp_end_date=add_days(today(), -1))
        listed = tasks.get_tasks(token=self.author, scope="accessible", status="All",
                                 search_text=self.prefix, limit=1)
        self.assertNotIn("error", listed, listed)
        self.assertEqual(len(listed["tasks"]), 1)
        self.assertEqual(listed["summary"]["total_items"], 3)
        self.assertEqual(listed["summary"]["overdue_count"], 3)
        self.assertTrue(listed["has_more"])
        overdue = tasks.get_tasks(token=self.author, scope="mine", status="Overdue", search_text=self.prefix)
        self.assertEqual(len(overdue["tasks"]), 3)
        empty = tasks.get_tasks(token=self.author, status="Completed", search_text=self.prefix)
        self.assertEqual(empty["summary"]["total_items"], 0)

    def test_denied_list_detail_create_and_update(self):
        task = self._create()
        for response in (
            tasks.get_tasks(token=self.reader),
            tasks.get_task(token=self.reader, name=task["name"]),
            tasks.create_task(token=self.reader, subject=self.prefix),
            tasks.update_task(token=self.reader, name=task["name"], status="Completed"),
        ):
            self.assertEqual(response.get("error"), "Access denied", response)

    def test_native_read_only_share_cannot_update(self):
        task = self._create()
        frappe.set_user("Administrator")
        frappe.share.add("Task", task["name"], self.reader, read=1, write=0)
        detail = tasks.get_task(token=self.reader, name=task["name"])
        self.assertNotIn("error", detail, detail)
        self.assertFalse(detail["task"]["can_write"])
        self.assertEqual(detail["task"]["allowed_statuses"], [])
        native_rows = frappe.get_list("Task", filters={"name": task["name"]}, fields=["name"])
        listed = tasks.get_tasks(token=self.reader, scope="accessible", status="All", search_text=self.prefix)
        self.assertNotIn("error", listed, listed)
        self.assertEqual({r["name"] for r in listed["tasks"]}, {r.name for r in native_rows})
        denied = tasks.update_task(token=self.reader, name=task["name"], status="Completed")
        self.assertEqual(denied.get("error"), "Access denied")

    def test_assignment_failure_rolls_back_task(self):
        response = tasks.create_task(token=self.author, subject=self.prefix,
                                     assignees=["missing-task-user@example.invalid"])
        self.assertIn("error", response)
        self.assertFalse(frappe.db.exists("Task", {"subject": self.prefix}))

    def test_stale_update_and_invalid_progress_preserve_task(self):
        task = self._create()
        stale = tasks.update_task(token=self.author, name=task["name"], modified="old", subject="overwritten")
        self.assertIn("error", stale)
        invalid = tasks.update_task(token=self.author, name=task["name"], progress=101)
        self.assertIn("error", invalid)
        self.assertEqual(frappe.db.get_value("Task", task["name"], "subject"), self.prefix)

    def test_task_options_and_invalid_session(self):
        options = tasks.get_task_options(token=self.author)
        self.assertNotIn("error", options, options)
        self.assertIn("Urgent", options["priorities"])
        self.assertIn("Pending Review", options["statuses"])
        self.assertEqual(tasks.get_task_options(token=self.reader).get("error"), "Access denied")
        self.assertEqual(tasks.get_tasks(token="invalid").get("error"), "Invalid session")

    def test_legacy_todos_remain_separate(self):
        frappe.set_user(self.author)
        todo = frappe.get_doc({"doctype": "ToDo", "description": self.prefix,
                               "allocated_to": self.author, "status": "Open"}).insert()
        listed = tasks.get_tasks(token=self.author, scope="accessible", status="All", search_text=self.prefix)
        self.assertEqual(listed["tasks"], [])
        legacy = tasks.get_my_tasks(token=self.author, status="All", date="all", search_text=self.prefix)
        self.assertIn(todo.name, [r["name"] for r in legacy["tasks"]])

    def test_assignment_replacement_updates_native_metadata(self):
        task = self._create()
        result = tasks.update_task(token=self.author, name=task["name"], assignees=[self.author])
        self.assertNotIn("error", result, result)
        self.assertEqual([u["name"] for u in result["task"]["assignees"]], [self.author])
        import json
        self.assertEqual(json.loads(frappe.db.get_value("Task", task["name"], "_assign")), [self.author])
        self.assertEqual(frappe.db.get_value("ToDo", {
            "reference_type": "Task", "reference_name": task["name"],
            "allocated_to": self.colleague,
        }, "status"), "Cancelled")
        updated = tasks.update_task(token=self.author, name=task["name"],
                                    subject=self.prefix + " updated", priority="Urgent",
                                    assignees=[self.author, self.colleague])
        self.assertNotIn("error", updated, updated)
        assignment = frappe.db.get_value("ToDo", {
            "reference_type": "Task", "reference_name": task["name"],
            "allocated_to": self.colleague, "status": "Open",
        }, ["description", "priority"], as_dict=True)
        self.assertEqual(assignment.description, self.prefix + " updated")
        self.assertEqual(assignment.priority, "High")

    def test_error_after_native_assignment_rolls_back_everything(self):
        from frappe.desk.form import assign_to
        native_add = assign_to.add

        def fail_after_assignment(*args, **kwargs):
            native_add(*args, **kwargs)
            frappe.throw("Simulated failure after assigning")

        with patch.object(assign_to, "add", fail_after_assignment):
            result = tasks.create_task(token=self.author, subject=self.prefix, assignees=[self.colleague])
        self.assertIn("error", result)
        self.assertFalse(frappe.db.exists("Task", {"subject": self.prefix}))
        self.assertFalse(frappe.db.exists("ToDo", {"description": self.prefix}))

    def test_frappe_dispatch_accepts_json_and_exports_new_api(self):
        from frappe.handler import execute_cmd
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        previous_request = getattr(frappe.local, "request", None)
        previous_form = getattr(frappe.local, "form_dict", None)
        payload = {"token": self.author, "subject": self.prefix, "assignees": [self.colleague]}
        try:
            frappe.local.request = Request(EnvironBuilder(method="POST", json=payload).get_environ())
            frappe.local.form_dict = frappe._dict({"cmd": "mobile_app.api.create_task", **payload})
            result = execute_cmd("mobile_app.api.create_task")
            self.assertNotIn("error", result, result)
            self.assertEqual(result["task"]["subject"], self.prefix)
            self.assertEqual(result["task"]["assignees"][0]["name"], self.colleague)
        finally:
            frappe.local.request = previous_request
            frappe.local.form_dict = previous_form

    def test_non_object_json_body_is_still_rejected(self):
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        previous_request = getattr(frappe.local, "request", None)
        try:
            for body in ("[]", "null", "{broken"):
                with self.subTest(body=body):
                    frappe.local.request = Request(EnvironBuilder(
                        method="POST", data=body, content_type="application/json",
                    ).get_environ())
                    result = tasks.create_task(token=self.author, subject=self.prefix)
                    self.assertEqual(result.get("error"), "Expected a JSON object")
                    self.assertFalse(frappe.db.exists("Task", {"subject": self.prefix}))
        finally:
            frappe.local.request = previous_request

    def test_mobile_get_with_json_header_and_no_body(self):
        """The shared Flutter client sends Content-Type JSON even on GET."""
        from frappe.handler import execute_cmd
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request

        task = self._create()
        previous_request = getattr(frappe.local, "request", None)
        previous_form = getattr(frappe.local, "form_dict", None)
        try:
            for method, params, key in (
                ("get_tasks", {"scope": "mine", "search_text": self.prefix}, "tasks"),
                ("get_task", {"name": task["name"]}, "task"),
                ("get_task_options", {"kind": "users"}, "users"),
            ):
                with self.subTest(method=method):
                    command = "mobile_app.api." + method
                    query = {"token": self.author, **params}
                    frappe.local.request = Request(EnvironBuilder(
                        method="GET", query_string=query,
                        headers={"Content-Type": "application/json", "Accept": "application/json"},
                    ).get_environ())
                    frappe.local.form_dict = frappe._dict({"cmd": command, **query})
                    result = execute_cmd(command)
                    self.assertNotIn("error", result, result)
                    self.assertIn(key, result)
        finally:
            frappe.local.request = previous_request
            frappe.local.form_dict = previous_form

