"""Integration tests: all users, employees, reports and assignments are rolled back."""
import unittest
from unittest.mock import patch
import frappe
from mobile_app import api
from mobile_app import activity_reports as reports


class TestActivityReports(unittest.TestCase):
    def setUp(self):
        frappe.set_user("Administrator")
        frappe.db.savepoint("activity_report_test")
        self.old_test = frappe.flags.in_test
        frappe.flags.in_test = True
        self.prefix = "mobile-report-test-" + frappe.generate_hash(length=8)
        self.author, self.author_employee = self._user("author", ["System Manager", "Projects User"])
        self.reader, self.reader_employee = self._user("reader", ["Employee"])
        self.absent, self.absent_employee = self._user("absent", ["Employee"])
        self.manager, self.manager_employee = self._user("manager", ["Stock Manager", "Projects User"])
        self.tokens = (self.author, self.reader, self.absent, self.manager, "Administrator")
        self.auth = patch.object(api, "authenticate_employee", self._auth)
        self.notify = patch("frappe.desk.form.assign_to.notify_assignment")
        self.auth.start(); self.notify.start()

    def tearDown(self):
        self.notify.stop(); self.auth.stop()
        frappe.set_user("Administrator")
        frappe.db.rollback(save_point="activity_report_test")
        frappe.flags.in_test = self.old_test

    def _user(self, label, roles):
        user = self.prefix + "-" + label + "@example.invalid"
        frappe.get_doc({"doctype":"User", "email":user, "first_name":label,
                        "send_welcome_email":0, "roles":[{"role":r} for r in roles]}).insert(ignore_permissions=True)
        emp = frappe.get_doc({"doctype":"Employee", "first_name":label, "employee_name":label,
                              "user_id":user,"status":"Active", "create_user_permission":0, "date_of_joining":frappe.utils.today(),
                              "company":frappe.db.get_value("Company",{},"name")})
        emp.insert(ignore_permissions=True, ignore_mandatory=True)
        return user, emp.name

    def _auth(self, token):
        if token not in self.tokens:return None
        frappe.set_user(token)
        return token

    def _payload(self, **values):
        return {"title":self.prefix,"doc_type":"Weekly Report","date":frappe.utils.today(),
                "attendance_list":[{"employee":self.author_employee,"present":1},
                                   {"employee":self.reader_employee,"present":1},
                                   {"employee":self.absent_employee,"present":0}],
                "done_list":[{"description":"Done"}],"issue_list":[],"task_list":[],**values}

    def _create(self, **values):
        result = reports.create_activity_report(token=self.author,report=self._payload(**values))
        self.assertNotIn("error", result, result)
        self.assertTrue(result["can_read"])
        return result["report"]

    def _task(self, completed=False):
        frappe.set_user("Administrator")
        doc=frappe.get_doc({"doctype":"Task","subject":self.prefix,"status":"Completed" if completed else "Open"}).insert()
        return doc.name

    def test_weekly_presence_read_and_write_permissions(self):
        report=self._create()
        own=reports.get_activity_report(token=self.reader,name=report["name"])
        self.assertTrue(own["can_read"])
        self.assertFalse(own["can_write"])
        self.assertEqual(reports.get_activity_report(token=self.absent,name=report["name"]).get("error"),"Access denied")
        self.assertEqual(reports.get_activity_report(token=self.manager,name=report["name"]).get("error"),"Access denied")
        for token in (self.reader,self.absent):
            self.assertEqual(reports.create_activity_report(token=token,report=self._payload()).get("error"),"Access denied")
            self.assertEqual(reports.update_activity_report(token=token,name=report["name"],modified=report["modified"],report={"title":"Denied"}).get("error"),"Access denied")

    def test_monthly_native_access(self):
        report=self._create(doc_type="Monthly Report",attendance_list=[])
        self.assertTrue(reports.get_activity_report(token=self.manager,name=report["name"])["can_write"])
        self.assertEqual(reports.get_activity_report(token=self.reader,name=report["name"]).get("error"),"Access denied")

    def test_pagination_totals_and_native_list_match(self):
        for _ in range(3):self._create()
        listed=reports.get_activity_reports(token=self.reader,search_text=self.prefix,limit=1)
        self.assertNotIn("error",listed,listed)
        self.assertEqual(listed["total_items"],3)
        self.assertTrue(listed["has_more"])
        self.assertEqual(len(listed["reports"]),1)
        self.assertEqual(listed["reports"][0]["action_count"],0)
        self.assertFalse(listed["can_create"])
        self.assertEqual(reports.get_activity_reports(token=self.absent,search_text=self.prefix)["total_items"],0)
        frappe.set_user(self.reader)
        native=frappe.get_list("Activity Report",filters={"title":self.prefix},pluck="name",limit_page_length=0)
        self.assertEqual(len(native),listed["total_items"])

    def test_update_can_remove_own_access_without_leaking_document(self):
        report=self._create()
        result=reports.update_activity_report(token=self.author,name=report["name"],modified=report["modified"],
            report={"attendance_list":[{"employee":self.reader_employee,"present":1}]})
        self.assertNotIn("error",result,result)
        self.assertFalse(result["can_read"])
        self.assertIsNone(result["report"])
        self.assertTrue(reports.get_activity_report(token=self.reader,name=report["name"])["can_read"])
        self.assertEqual(reports.get_activity_report(token=self.author,name=report["name"]).get("error"),"Access denied")

    def test_stale_and_foreign_child_updates_are_rejected(self):
        first=self._create(); second=self._create()
        stale=reports.update_activity_report(token=self.author,name=first["name"],modified="old",report={"title":"Lost"})
        self.assertIn("error",stale)
        tampered=reports.update_activity_report(token=self.author,name=first["name"],modified=first["modified"],
            report={"done_list":[{"name":second["done_list"][0]["name"],"description":"Hijacked"}]})
        self.assertIn("error",tampered)
        self.assertEqual(frappe.db.get_value("Activity Report",first["name"],"title"),self.prefix)

    def test_native_assignment_without_duplicates_and_report_action_status_independent(self):
        task=self._task()
        report=self._create(task_list=[{"task_link":task,"description":"Follow up","responsible_employee":self.reader_employee,"status":"Completed"}])
        self.assertEqual(frappe.db.get_value("Task",task,"status"),"Open")
        filters={"reference_type":"Task","reference_name":task,"allocated_to":self.reader,"status":"Open"}
        self.assertEqual(frappe.db.count("ToDo",filters),1)
        result=reports.update_activity_report(token=self.author,name=report["name"],modified=report["modified"],report={"title":self.prefix+" updated"})
        self.assertNotIn("error",result,result)
        self.assertEqual(frappe.db.count("ToDo",filters),1)
        newer=result["report"]
        removed=reports.update_activity_report(token=self.author,name=newer["name"],modified=newer["modified"],report={"task_list":[]})
        self.assertNotIn("error",removed,removed)
        self.assertEqual(frappe.db.count("ToDo",filters),0)

    def test_completed_task_does_not_reopen_assignments(self):
        task=self._task(completed=True)
        self._create(task_list=[{"task_link":task,"description":"Already done","responsible_employee":self.reader_employee}])
        self.assertEqual(frappe.db.count("ToDo",{"reference_type":"Task","reference_name":task,"status":"Open"}),0)

    def test_assignment_failure_rolls_back_report_and_native_assignment(self):
        from iso9001.iso_9001.doctype.activity_report import activity_report as native
        task=self._task(); add=native.add
        def fail(*args,**kwargs):
            add(*args,**kwargs)
            frappe.throw("Assignment failed after insert")
        with patch.object(native,"add",fail):
            result=reports.create_activity_report(token=self.author,report=self._payload(task_list=[{"task_link":task,"description":"Action","responsible_employee":self.reader_employee}]))
        self.assertIn("error",result)
        self.assertFalse(frappe.db.exists("Activity Report",{"title":self.prefix}))
        self.assertEqual(frappe.db.count("ToDo",{"reference_type":"Task","reference_name":task}),0)

    def test_mobile_get_headers_post_dispatch_and_options(self):
        from frappe.handler import execute_cmd
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request
        old_request=getattr(frappe.local,"request",None); old_form=getattr(frappe.local,"form_dict",None)
        report=self._create()
        try:
            for method,args,key in (("get_activity_reports",{"search_text":self.prefix},"reports"),
                                   ("get_activity_report",{"name":report["name"]},"report"),
                                   ("get_activity_report_options",{},"report_types")):
                query={"token":self.author,**args}
                frappe.local.request=Request(EnvironBuilder(method="GET",query_string=query,headers={"Content-Type":"application/json"}).get_environ())
                frappe.local.form_dict=frappe._dict(query)
                result=execute_cmd("mobile_app.api."+method)
                self.assertNotIn("error",result,result);self.assertIn(key,result)
            payload={"token":self.author,"report":self._payload(doc_type="Monthly Report")}
            frappe.local.request=Request(EnvironBuilder(method="POST",json=payload).get_environ())
            frappe.local.form_dict=frappe._dict(payload)
            result=execute_cmd("mobile_app.api.create_activity_report")
            self.assertNotIn("error",result,result)
        finally:frappe.local.request=old_request;frappe.local.form_dict=old_form
        self.assertEqual(reports.get_activity_report_options(token="invalid").get("error"),"Invalid session")

    def test_responsible_change_and_manual_assignment_preserved(self):
        from frappe.desk.form import assign_to
        task=self._task()
        assign_to.add({"doctype":"Task","name":task,"assign_to":[self.reader],"description":"Manual assignment"})
        report=self._create(task_list=[{"task_link":task,"description":"Follow up","responsible_employee":self.reader_employee}])
        changed=reports.update_activity_report(token=self.author,name=report["name"],modified=report["modified"],
            report={"task_list":[{"name":report["task_list"][0]["name"],"task_link":task,"description":"Follow up","responsible_employee":self.absent_employee}]})
        self.assertNotIn("error",changed,changed)
        self.assertEqual(frappe.db.count("ToDo",{"reference_type":"Task","reference_name":task,"allocated_to":self.reader,"status":"Open"}),1)
        self.assertEqual(frappe.db.count("ToDo",{"reference_type":"Task","reference_name":task,"allocated_to":self.absent,"status":"Open"}),1)

    def test_missing_employee_user_and_invalid_json_do_not_save(self):
        from werkzeug.test import EnvironBuilder
        from werkzeug.wrappers import Request
        frappe.set_user("Administrator")
        frappe.db.set_value("Employee",self.reader_employee,"user_id",None)
        task=self._task()
        result=reports.create_activity_report(token=self.author,report=self._payload(task_list=[{"description":"Action","task_link":task,"responsible_employee":self.reader_employee}]))
        self.assertEqual(result.get("error"),"Responsible employee needs an ERP user account")
        self.assertFalse(frappe.db.exists("Activity Report",{"title":self.prefix}))
        old_request=getattr(frappe.local,"request",None)
        try:
            for body in ("[]","null","{broken"):
                frappe.local.request=Request(EnvironBuilder(method="POST",data=body,content_type="application/json").get_environ())
                result=reports.create_activity_report(token=self.author,report=self._payload())
                self.assertEqual(result.get("error"),"Expected a JSON object")
        finally:frappe.local.request=old_request

    def test_failed_save_discards_only_its_notification_callbacks(self):
        from iso9001.iso_9001.doctype.activity_report import activity_report as native
        from frappe.utils import CallbackManager
        task=self._task()
        previous_callbacks=frappe.db.after_commit
        frappe.db.after_commit=CallbackManager()
        called=[]
        frappe.db.after_commit.add(lambda:called.append("outer"))
        def fail(*args,**kwargs):
            frappe.db.after_commit.add(lambda:called.append("failed assignment"))
            frappe.throw("Callback test failure")
        try:
            with patch.object(native,"add",fail):
                result=reports.create_activity_report(token=self.author,report=self._payload(task_list=[{"description":"Action","task_link":task,"responsible_employee":self.reader_employee}]))
            self.assertIn("error",result)
            frappe.db.after_commit.run()
            self.assertEqual(called,["outer"])
        finally:frappe.db.after_commit=previous_callbacks
    def test_employee_lookup_respects_native_user_permissions(self):
        frappe.set_user("Administrator")
        frappe.get_doc({"doctype":"User Permission","user":self.author,"allow":"Employee","for_value":self.author_employee,"apply_to_all_doctypes":1}).insert(ignore_permissions=True)
        frappe.clear_cache(user=self.author)
        result=reports.create_activity_report(token=self.author,report=self._payload())
        self.assertEqual(result.get("error"),"Access denied")
        self.assertFalse(frappe.db.exists("Activity Report",{"title":self.prefix}))
    def test_report_reader_cannot_read_linked_task_title_without_task_permission(self):
        task=self._task()
        report=self._create(task_list=[{"task_link":task,"description":"Report action","status":"Open"}])
        result=reports.get_activity_report(token=self.reader,name=report["name"])
        self.assertNotIn("error",result,result)
        row=result["report"]["task_list"][0]
        self.assertEqual(row["task_link"],task)
        self.assertFalse(row["can_read_task"])
        self.assertNotIn("task_subject",row)
