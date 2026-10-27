"""Mobile access to the existing ISO 9001 Activity Report document.

Permissions and assignment side effects belong to the native DocType controller.
"""
from functools import wraps
from inspect import signature

import frappe
from frappe.desk.search import search_link

DOCTYPE = "Activity Report"
TABLES = {
    "attendance_list": ("Activity Report Attendee", ("employee", "present")),
    "done_list": ("Activity Report Simple Item", ("description",)),
    "issue_list": ("Activity Report Simple Item", ("description",)),
    "task_list": ("Activity Report Task Link", ("task_link", "description", "responsible_employee", "deadline", "status")),
}
SCALARS = ("title", "doc_type", "date", "process_link")


def _api(*, write=False):
    def decorate(fn):
        @frappe.whitelist(allow_guest=True, methods=["POST"] if write else ["GET"])
        @wraps(fn)
        def endpoint(*args, **kwargs):
            savepoint = None
            outer_callbacks = None
            committed = False
            previous_realtime = list(getattr(frappe.local, '_realtime_log', []) or [])
            try:
                data = {}
                request = getattr(frappe.local, "request", None)
                if request and request.is_json and request.get_data():
                    body = request.get_json(silent=True)
                    if not isinstance(body, dict):
                        frappe.throw("Expected a JSON object")
                    data.update(body)
                supplied = signature(fn).bind_partial(*args, **kwargs).arguments
                data.update(supplied.pop("kwargs", {}))
                data.update({k: v for k, v in supplied.items() if v is not None})
                from mobile_app.api import authenticate_employee
                user = authenticate_employee(data.get("token"))
                if not user or user == "Guest" or not frappe.get_cached_value("User", user, "enabled"):
                    return {"error": "Invalid session"}
                if write:
                    savepoint = "mobile_activity_report_mutation"
                    frappe.db.savepoint(savepoint)
                    # Isolate after-commit notifications as well as database writes.
                    from frappe.utils import CallbackManager
                    outer_callbacks = {key: getattr(frappe.db, key) for key in (
                        "before_commit", "after_commit", "before_rollback", "after_rollback")}
                    for key in outer_callbacks:
                        setattr(frappe.db, key, CallbackManager())
                result = fn(**data)
                committed = True
                return result
            except Exception as exc:
                if savepoint:
                    frappe.db.before_rollback.run()
                    frappe.db.rollback(save_point=savepoint)
                    frappe.db.after_rollback.run()
                    frappe.local._realtime_log = previous_realtime
                if isinstance(exc, frappe.PermissionError):
                    return {"error": "Access denied"}
                if isinstance(exc, frappe.DoesNotExistError):
                    return {"error": "Activity Report not found"}
                if isinstance(exc, (frappe.ValidationError, ValueError, TypeError)):
                    return {"error": str(exc)}
                frappe.log_error(frappe.get_traceback(), f"{fn.__name__} error")
                return {"error": "Unable to process Activity Report"}
            finally:
                if outer_callbacks:
                    for key, outer in outer_callbacks.items():
                        nested = getattr(frappe.db, key)
                        if committed:
                            outer.add(nested.run)
                        setattr(frappe.db, key, outer)
        return endpoint
    return decorate


def _choices(doctype, field):
    return (frappe.get_meta(doctype).get_field(field).options or "").splitlines()


def _can(doc, permission="read"):
    try:
        doc.check_permission(permission)
        return True
    except frappe.PermissionError:
        return False


def _date(value):
    return str(frappe.utils.getdate(value)) if value else ""


def _page(limit, offset=0):
    limit, offset = int(limit or 20), int(offset or 0)
    if offset < 0:
        frappe.throw("Offset must not be negative")
    return max(1, min(limit, 100)), offset


def _employee():
    return frappe.db.get_value("Employee", {"user_id": frappe.session.user, "status": "Active"},
                               ["name", "employee_name"], as_dict=True)


def _serialize(doc):
    result = {f: doc.get(f) or "" for f in ("name", "title", "doc_type", "date", "process_link", "owner", "modified")}
    result["date"] = _date(doc.date)
    result["modified"] = str(doc.modified)
    for field, (_, allowed) in TABLES.items():
        result[field] = [{"name": row.name, **{k: row.get(k) or "" for k in allowed}} for row in doc.get(field) or []]
    for row in result["attendance_list"]:
        row["present"] = bool(row["present"])
        row["employee_name"] = frappe.db.get_value("Employee", row["employee"], "employee_name") or row["employee"]
    for row in result["task_list"]:
        row["deadline"] = _date(row["deadline"])
        row["responsible_name"] = (frappe.db.get_value("Employee", row["responsible_employee"], "employee_name") or row["responsible_employee"]) if row["responsible_employee"] else ""
        row["can_read_task"] = False
        if row["task_link"] and frappe.db.exists("Task", row["task_link"]):
            task = frappe.get_doc("Task", row["task_link"])
            row["can_read_task"] = _can(task)
            if row["can_read_task"]:
                row["task_subject"] = task.subject
    return result


def _saved(doc):
    readable = _can(doc)
    return {"success": True, "can_read": readable,
            "can_write": readable and _can(doc, "write"),
            "report": _serialize(doc) if readable else None}


@_api()
def get_activity_reports(token=None, report_type=None, from_date=None, to_date=None,
                         search_text=None, limit=20, offset=0, **kwargs):
    frappe.has_permission(DOCTYPE, "read", throw=True)
    limit, offset = _page(limit, offset)
    filters = []
    if report_type:
        if report_type not in _choices(DOCTYPE, "doc_type"):
            frappe.throw("Invalid report type")
        filters.append(["doc_type", "=", report_type])
    if from_date:
        filters.append(["date", ">=", _date(from_date)])
    if to_date:
        filters.append(["date", "<=", _date(to_date)])
    if from_date and to_date and _date(from_date) > _date(to_date):
        frappe.throw("Invalid date range")
    if search_text and search_text.strip():
        filters.append(["title", "like", f"%{search_text.strip()}%"])
    query = dict(filters=filters)
    total = frappe.get_list(DOCTYPE, fields=["count(name) as count"], **query)[0].count or 0
    rows = frappe.get_list(DOCTYPE, fields=["name", "title", "doc_type", "date", "modified"],
                           limit_page_length=limit, limit_start=offset,
                           order_by="date desc, modified desc, name desc", **query)
    names = [row.name for row in rows]
    counts = {r.parent: int(r.count) for r in frappe.get_all(
        "Activity Report Task Link", filters={"parent": ["in", names], "parenttype": DOCTYPE, "parentfield": "task_list"},
        fields=["parent", "count(name) as count"], group_by="parent", limit_page_length=0,
    )} if names else {}
    for row in rows:
        row.date = _date(row.date)
        row.modified = str(row.modified)
        row["action_count"] = counts.get(row.name, 0)
    return {"success": True, "reports": rows, "total_items": int(total), "has_more": offset + len(rows) < total,
            "can_create": bool(frappe.has_permission(DOCTYPE, "create"))}


@_api()
def get_activity_report(token=None, name=None, **kwargs):
    doc = frappe.get_doc(DOCTYPE, (name or "").strip())
    doc.check_permission("read")
    return _saved(doc)


def _link(doctype, name, *, previous=None):
    if not name:
        return
    if not frappe.db.exists(doctype, name):
        frappe.throw(f"Invalid {doctype} reference")
    if previous == name:
        return  # Do not clear historical links that are no longer selectable.
    if doctype == "Task":
        frappe.get_doc(doctype, name).check_permission("read")
    else:
        rows = search_link(doctype=doctype, txt="", filters={"name": name},
                           reference_doctype=DOCTYPE, page_length=1) or []
        if not any(r.get("value") == name for r in rows):
            frappe.throw("Access denied", frappe.PermissionError)


def _apply(doc, payload):
    if isinstance(payload, str):
        payload = frappe.parse_json(payload)
    if not isinstance(payload, dict):
        frappe.throw("Expected a report object")
    for field in SCALARS:
        if field not in payload:
            continue
        value = str(payload[field] or "").strip()
        if field == "title" and not value:
            frappe.throw("Report title is required")
        if field == "doc_type" and value not in _choices(DOCTYPE, "doc_type"):
            frappe.throw("Invalid report type")
        if field == "date":
            value = _date(value) or None
        if field == "process_link":
            _link("Process sheet", value, previous=doc.get(field))
        doc.set(field, value)
    if not doc.title or not doc.doc_type:
        frappe.throw("Report title and type are required")
    for field, (child_type, allowed) in TABLES.items():
        if field not in payload:
            continue
        incoming = payload[field]
        if not isinstance(incoming, list):
            frappe.throw("Report lines must be lists")
        previous = {r.name: r for r in doc.get(field) or []}
        seen = set()
        sanitized = []
        for row in incoming:
            if not isinstance(row, dict):
                frappe.throw("Invalid report line")
            name = row.get("name")
            if name and (name not in previous or name in seen):
                frappe.throw("Report line does not belong to this report")
            if name:
                seen.add(name)
            old = previous.get(name)
            values = {k: row.get(k) for k in allowed}
            if name:
                values["name"] = name
            if field in ("done_list", "issue_list", "task_list"):
                values["description"] = str(values.get("description") or "").strip()
                if not values["description"]:
                    frappe.throw("Action description is required")
            if field == "attendance_list":
                employee = values.get("employee")
                if not employee:
                    frappe.throw("Employee is required")
                _link("Employee", employee, previous=old.employee if old else None)
                if any(r.get("employee") == employee for r in sanitized):
                    frappe.throw("Duplicate participant")
                values["present"] = frappe.utils.cint(values.get("present"))
                if values["present"] not in (0, 1):
                    frappe.throw("Invalid presence value")
                values["employee_name"] = frappe.db.get_value("Employee", employee, "employee_name")
            if field == "task_list":
                values["task_link"] = values.get("task_link") or None
                values["responsible_employee"] = values.get("responsible_employee") or None
                _link("Task", values["task_link"], previous=old.task_link if old else None)
                _link("Employee", values["responsible_employee"], previous=old.responsible_employee if old else None)
                if (values["task_link"] and values["responsible_employee"]
                        and frappe.db.get_value("Task", values["task_link"], "status") not in ("Completed", "Cancelled")
                        and not frappe.db.get_value("Employee", values["responsible_employee"], "user_id")):
                    frappe.throw("Responsible employee needs an ERP user account")
                values["deadline"] = _date(values.get("deadline")) or None
                values["status"] = values.get("status") or "Open"
                if values["status"] not in _choices(child_type, "status"):
                    frappe.throw("Invalid action status")
            sanitized.append(values)
        doc.set(field, sanitized)


@_api(write=True)
def create_activity_report(token=None, report=None, **kwargs):
    frappe.has_permission(DOCTYPE, "create", throw=True)
    doc = frappe.new_doc(DOCTYPE)
    _apply(doc, report)
    doc.insert()
    return _saved(doc)


@_api(write=True)
def update_activity_report(token=None, name=None, modified=None, report=None, **kwargs):
    doc = frappe.get_doc(DOCTYPE, (name or "").strip(), for_update=True)
    doc.check_permission("read")
    doc.check_permission("write")
    if not modified or str(doc.modified) != str(modified):
        frappe.throw("Report has changed. Refresh before saving.")
    _apply(doc, report)
    doc.save()
    return _saved(doc)


@_api()
def get_activity_report_options(token=None, kind="metadata", search_text=None, limit=20, **kwargs):
    if not (frappe.has_permission(DOCTYPE, "read") or frappe.has_permission(DOCTYPE, "create")):
        frappe.throw("Access denied", frappe.PermissionError)
    if kind not in ("metadata", "employees", "processes"):
        frappe.throw("Invalid report options kind")
    limit, _ = _page(limit)
    result = {"success": True, "report_types": _choices(DOCTYPE, "doc_type"),
              "action_statuses": _choices("Activity Report Task Link", "status"),
              "can_create": bool(frappe.has_permission(DOCTYPE, "create")), "current_employee": _employee()}
    if kind != "metadata":
        if not (frappe.has_permission(DOCTYPE, "create") or frappe.has_permission(DOCTYPE, "write")):
            frappe.throw("Access denied", frappe.PermissionError)
        doctype = "Employee" if kind == "employees" else "Process sheet"
        rows = search_link(doctype=doctype, txt=(search_text or "").strip(), page_length=limit,
                           reference_doctype=DOCTYPE) or []
        result["items"] = [{"value": r["value"], "label": r.get("label") or r.get("description") or r["value"]} for r in rows]
        if kind == "employees":
            for row in result["items"]:
                row["label"] = frappe.db.get_value("Employee", row["value"], "employee_name") or row["value"]
    return result
