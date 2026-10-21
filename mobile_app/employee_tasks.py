################################################################################
######################  Employee Tasks (ToDo) Functions ########################
################################################################################
# ToDo APIs aligned with Stock Entry: SID + frappe.set_user, then ERPNext Role
# Permissions decide what the user sees/creates. No forced allocated_to filter.
#
# Example — list (permissions apply like Desk):
# curl -G "http://192.168.100.20:8000/api/method/mobile_app.api.get_my_tasks" \
#   --data-urlencode "token={{sid}}" \
#   --data-urlencode "status=Open" \
#   --data-urlencode "date=today" \
#   --data-urlencode "limit=20" \
#   --data-urlencode "offset=0"
#
# Example — create (requires ToDo Create in Role Permissions):
# curl -X POST "http://192.168.100.20:8000/api/method/mobile_app.api.create_todo" \
#   -H "Content-Type: application/json" \
#   -d '{"token":"{{sid}}","description":"Check stock Alger","allocated_to":"user@example.com","date":"2026-09-22","priority":"Medium"}'
#
# Example — update status:
# curl -X POST "http://192.168.100.20:8000/api/method/mobile_app.api.update_my_task_status" \
#   -H "Content-Type: application/json" \
#   -d '{"token":"{{sid}}","name":"TODO-0001","status":"Closed"}'

import frappe
import json
import math
from functools import wraps
from inspect import signature


def _serialize_todo(row):
    """Normalize a ToDo row for the mobile client (no nulls)."""
    return {
        "name":            row.get("name") or "",
        "description":     row.get("description") or "",
        "status":          row.get("status") or "Open",
        "priority":        row.get("priority") or "Medium",
        "date":            str(row.get("date") or ""),
        "allocated_to":    row.get("allocated_to") or "",
        "assigned_by":     row.get("assigned_by") or "",
        "reference_type":  row.get("reference_type") or "",
        "reference_name":  row.get("reference_name") or "",
        "creation":        str(row.get("creation") or ""),
        "modified":        str(row.get("modified") or ""),
    }


def _todo_fields():
    return [
        "name", "description", "status", "priority", "date",
        "allocated_to", "assigned_by",
        "reference_type", "reference_name",
        "creation", "modified",
    ]


@frappe.whitelist(allow_guest=True)
def get_my_tasks(
    token=None,
    status="Open",
    date=None,
    only_today=0,
    include_overdue=0,
    allocated_to=None,
    search_text=None,
    limit=20,
    offset=0,
):
    """
    List ToDos visible to the authenticated user (ERPNext permissions).
    Same pattern as get_last_stock_entries: SID → set_user → get_list.
    Optional allocated_to filter (only returns rows the user is allowed to read).
    """
    from mobile_app.api import authenticate_employee

    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        if not frappe.has_permission("ToDo", "read"):
            return {"error": "Access denied"}

        user = frappe.session.user
        limit = int(limit or 20)
        offset = int(offset or 0)
        only_today = int(only_today or 0)
        include_overdue = int(include_overdue or 0)

        status = (status or "Open").strip()
        search_text = (search_text or "").strip()
        is_search = bool(search_text)
        date_param = (date or "").strip().lower() if date else ""
        allocated_to = (allocated_to or "").strip()

        filters = {}

        # Optional filter — still subject to Role Permissions via get_list
        if allocated_to:
            filters["allocated_to"] = allocated_to

        if status and status != "All":
            filters["status"] = status

        today_str = frappe.utils.today()

        if date_param == "today" or only_today:
            filters["date"] = today_str
        elif date_param and date_param != "all":
            filters["date"] = date_param

        or_filters = None
        if include_overdue and (date_param == "today" or only_today):
            filters.pop("date", None)
            or_filters = [
                ["date", "=", today_str],
                ["date", "<", today_str],
                ["date", "is", "not set"],
            ]

        if is_search:
            filters["description"] = ["like", f"%{search_text}%"]

        try:
            rows = frappe.get_list(
                "ToDo",
                filters=filters,
                or_filters=or_filters,
                fields=_todo_fields(),
                order_by="date asc, priority desc, modified desc",
                limit_page_length=limit,
                limit_start=offset,
            )
        except frappe.PermissionError:
            return {"error": "Access denied"}

        tasks = [_serialize_todo(r) for r in rows]

        try:
            all_matching = frappe.get_list(
                "ToDo",
                filters=filters,
                or_filters=or_filters,
                fields=["name", "status", "date"],
                limit_page_length=5000,
            )
        except frappe.PermissionError:
            return {"error": "Access denied"}

        open_count = sum(1 for r in all_matching if (r.get("status") or "") == "Open")
        closed_count = sum(1 for r in all_matching if (r.get("status") or "") == "Closed")
        overdue_count = sum(
            1 for r in all_matching
            if (r.get("status") or "") == "Open"
            and r.get("date")
            and str(r.get("date")) < today_str
        )

        total_items = len(all_matching)
        has_more = (offset + limit) < total_items

        return {
            "success": True,
            "user": user,
            "can_create": bool(frappe.has_permission("ToDo", "create")),
            "date": today_str if (date_param == "today" or only_today) else (date_param if date_param not in ("", "all") else ""),
            "status": status,
            "allocated_to": allocated_to,
            "summary": {
                "total_items": total_items,
                "open_count": open_count,
                "closed_count": closed_count,
                "overdue_count": overdue_count,
            },
            "tasks": tasks,
            "is_search": is_search,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_my_tasks error")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_task_detail(token=None, name=None):
    """
    Get one ToDo. Access controlled by ERPNext permissions (like Stock Entry detail).
    """
    from mobile_app.api import authenticate_employee

    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        if not frappe.has_permission("ToDo", "read"):
            return {"error": "Access denied"}

        name = (name or "").strip()
        if not name:
            return {"error": "Missing name"}

        if not frappe.db.exists("ToDo", name):
            return {"error": "Task not found"}

        try:
            doc = frappe.get_doc("ToDo", name)
        except frappe.PermissionError:
            return {"error": "Access denied"}

        return {
            "success": True,
            "can_write": bool(frappe.has_permission("ToDo", "write", doc=doc)),
            "task": _serialize_todo({
                "name": doc.name,
                "description": doc.description,
                "status": doc.status,
                "priority": doc.priority,
                "date": doc.date,
                "allocated_to": doc.allocated_to,
                "assigned_by": doc.assigned_by,
                "reference_type": doc.reference_type,
                "reference_name": doc.reference_name,
                "creation": doc.creation,
                "modified": doc.modified,
            }),
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_task_detail error")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def create_todo(
    token=None,
    description=None,
    allocated_to=None,
    date=None,
    priority=None,
    reference_type=None,
    reference_name=None,
):
    """
    Create a ToDo. Requires ToDo Create permission in ERPNext (like inserting a Stock Entry).
    """
    from mobile_app.api import authenticate_employee

    try:
        if frappe.request and frappe.request.method == "POST":
            content_type = frappe.request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data = json.loads(frappe.request.data or "{}")
                token = token or data.get("token")
                description = description or data.get("description")
                allocated_to = allocated_to or data.get("allocated_to")
                date = date or data.get("date")
                priority = priority or data.get("priority")
                reference_type = reference_type or data.get("reference_type")
                reference_name = reference_name or data.get("reference_name")

        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        if not frappe.has_permission("ToDo", "create"):
            return {"error": "Access denied"}

        description = (description or "").strip()
        if not description:
            return {"error": "Missing description"}

        allocated_to = (allocated_to or "").strip() or frappe.session.user
        if not frappe.db.exists("User", allocated_to):
            return {"error": f"User '{allocated_to}' not found"}

        priority = (priority or "Medium").strip()
        if priority not in ("Low", "Medium", "High"):
            priority = "Medium"

        date = (date or "").strip() or frappe.utils.today()

        doc = frappe.get_doc({
            "doctype": "ToDo",
            "description": description,
            "allocated_to": allocated_to,
            "assigned_by": frappe.session.user,
            "date": date,
            "priority": priority,
            "status": "Open",
            "reference_type": (reference_type or "").strip() or None,
            "reference_name": (reference_name or "").strip() or None,
        })
        doc.insert()
        frappe.db.commit()

        return {
            "success": True,
            "message": "Success",
            "detail": f"Task {doc.name} created",
            "task": _serialize_todo({
                "name": doc.name,
                "description": doc.description,
                "status": doc.status,
                "priority": doc.priority,
                "date": doc.date,
                "allocated_to": doc.allocated_to,
                "assigned_by": doc.assigned_by,
                "reference_type": doc.reference_type,
                "reference_name": doc.reference_name,
                "creation": doc.creation,
                "modified": doc.modified,
            }),
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_todo error")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def update_my_task_status(name=None, status=None, token=None):
    """
    Update ToDo status. Write permission enforced by ERPNext (like manage_stock_entry).
    Allowed status: Open, Closed.
    """
    from mobile_app.api import authenticate_employee

    try:
        if frappe.request and frappe.request.method == "POST":
            content_type = frappe.request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data = json.loads(frappe.request.data or "{}")
                name = name or data.get("name")
                status = status or data.get("status")
                token = token or data.get("token")

        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        name = (name or "").strip()
        status = (status or "").strip()

        if not name:
            return {"error": "Missing name"}
        if status not in ("Open", "Closed"):
            return {"error": "Invalid status. Use: Open, Closed"}

        if not frappe.db.exists("ToDo", name):
            return {"error": "Task not found"}

        try:
            doc = frappe.get_doc("ToDo", name)
        except frappe.PermissionError:
            return {"error": "Access denied"}

        if not frappe.has_permission("ToDo", "write", doc=doc):
            return {"error": "Access denied"}

        doc.status = status
        doc.save()
        frappe.db.commit()

        return {
            "success": True,
            "message": "Success",
            "detail": f"Task {name} marked as {status}",
            "task": _serialize_todo({
                "name": doc.name,
                "description": doc.description,
                "status": doc.status,
                "priority": doc.priority,
                "date": doc.date,
                "allocated_to": doc.allocated_to,
                "assigned_by": doc.assigned_by,
                "reference_type": doc.reference_type,
                "reference_name": doc.reference_name,
                "creation": doc.creation,
                "modified": doc.modified,
            }),
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "update_my_task_status error")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def get_assignable_users(token=None, search_text=None, limit=20):
    """
    List active Users for ToDo "Allocated To" — same source as Desk Link search.
    Requires ToDo create or read. Auth: token = SID.
    """
    from mobile_app.api import authenticate_employee

    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        if not (
            frappe.has_permission("ToDo", "create")
            or frappe.has_permission("ToDo", "read")
        ):
            return {"error": "Access denied"}

        limit = int(limit or 20)
        if limit < 1:
            limit = 20
        if limit > 100:
            limit = 100

        search_text = (search_text or "").strip()
        is_search = bool(search_text)

        users = []

        # Prefer Desk Link search (same results as Allocated To in ERP UI)
        try:
            from frappe.desk.search import search_link

            link_results = search_link(
                doctype="User",
                txt=search_text or "",
                page_length=limit,
                reference_doctype="ToDo",
                filters={"enabled": 1},
            ) or []

            names = []
            for item in link_results:
                if isinstance(item, dict):
                    value = item.get("value") or item.get("name") or ""
                elif isinstance(item, (list, tuple)) and item:
                    value = item[0]
                else:
                    value = str(item or "")
                value = (value or "").strip()
                if value and value != "Guest" and value not in names:
                    names.append(value)

            if names:
                meta_rows = frappe.get_all(
                    "User",
                    filters={"name": ["in", names], "enabled": 1},
                    fields=["name", "full_name", "email", "user_image"],
                )
                meta_map = {r.get("name"): r for r in meta_rows}
                for name in names:
                    r = meta_map.get(name) or {}
                    users.append({
                        "name": name,
                        "email": r.get("email") or name,
                        "full_name": r.get("full_name") or name,
                        "user_image": r.get("user_image") or "",
                    })
        except Exception:
            frappe.log_error(frappe.get_traceback(), "get_assignable_users search_link")
            users = []

        # Fallback: get_list if search_link empty / unavailable
        if not users:
            filters = {"enabled": 1, "name": ["not in", ["Guest"]]}
            or_filters = None
            if is_search:
                or_filters = [
                    ["name", "like", f"%{search_text}%"],
                    ["full_name", "like", f"%{search_text}%"],
                    ["email", "like", f"%{search_text}%"],
                ]
            try:
                rows = frappe.get_list(
                    "User",
                    filters=filters,
                    or_filters=or_filters,
                    fields=["name", "full_name", "email", "user_image"],
                    order_by="full_name asc, name asc",
                    limit_page_length=limit,
                )
            except frappe.PermissionError:
                return {"error": "Access denied"}

            for r in rows:
                name = r.get("name") or ""
                if not name or name == "Guest":
                    continue
                users.append({
                    "name": name,
                    "email": r.get("email") or name,
                    "full_name": r.get("full_name") or name,
                    "user_image": r.get("user_image") or "",
                })

        return {
            "success": True,
            "users": users,
            "is_search": is_search,
            "limit": limit,
            "count": len(users),
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_assignable_users error")
        return {"error": str(e)}


################################################################################
# ERPNext Task APIs. The ToDo endpoints above remain backward compatible.
# GET /api/method/mobile_app.api.get_tasks?token={{sid}}&scope=mine&status=Active
# POST create_task: {token, subject, assignees: [user_email, ...], ...}
# POST update_task: {token, name, modified, status: "Working", ...}
################################################################################

_TASK_FIELDS = [
    "name", "subject", "description", "status", "priority", "progress",
    "exp_start_date", "exp_end_date", "project", "company", "department",
    "owner", "creation", "modified", "is_group", "is_template",
]
_TASK_EDIT_FIELDS = (
    "subject", "description", "company", "project", "exp_start_date",
    "exp_end_date", "priority", "progress", "status",
)
_TASK_FINISHED = ("Completed", "Cancelled", "Template")


def _task_api(*, write=False):
    """Authenticate once and roll back the complete mutation on a handled error."""
    def decorate(fn):
        @frappe.whitelist(allow_guest=True, methods=["POST"] if write else ["GET"])
        @wraps(fn)
        def endpoint(*args, **kwargs):
            savepoint = None
            try:
                data = {}
                request = getattr(frappe.local, "request", None)
                # Content-Type alone does not imply a body (Flutter GETs also
                # carry application/json). Match Frappe's request parsing.
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
                if not user or user == "Guest":
                    return {"error": "Invalid session"}
                if not frappe.get_cached_value("User", user, "enabled"):
                    return {"error": "Invalid session"}
                if write:
                    savepoint = "mobile_task_mutation"
                    frappe.db.savepoint(savepoint)
                return fn(**data)
            except Exception as exc:
                if savepoint:
                    frappe.db.rollback(save_point=savepoint)
                if isinstance(exc, frappe.PermissionError):
                    return {"error": "Access denied"}
                if isinstance(exc, frappe.DoesNotExistError):
                    return {"error": "Task not found"}
                if isinstance(exc, (frappe.ValidationError, ValueError, TypeError)):
                    return {"error": str(exc)}
                frappe.log_error(frappe.get_traceback(), f"{fn.__name__} error")
                return {"error": "Unable to process Task"}

        return endpoint
    return decorate


def _task_require_permission(ptype):
    frappe.has_permission("Task", ptype, throw=True)


def _task_choices(field):
    return (frappe.get_meta("Task").get_field(field).options or "").splitlines()


def _task_pagination(limit, offset=0):
    limit, offset = int(limit or 20), int(offset or 0)
    if offset < 0:
        frappe.throw("Offset must not be negative")
    return max(1, min(limit, 100)), offset


def _task_date(value):
    return str(frappe.utils.getdate(value)) if value else ""


def _task_assigned_names(user):
    # Assignment metadata is internal; access to the resulting Tasks is always
    # checked by get_list. Closed assignments retain completed Task history.
    rows = frappe.get_all(
        "ToDo",
        filters={"reference_type": "Task", "allocated_to": user,
                 "status": ["!=", "Cancelled"]},
        fields=["reference_name", "status"],
    )
    active = {r.reference_name for r in rows if r.reference_name and r.status == "Open"}
    closed = {r.reference_name for r in rows if r.reference_name and r.status == "Closed"}
    if closed:
        active.update(r.name for r in frappe.get_list(
            "Task", filters={"name": ["in", list(closed)], "status": "Completed"},
            fields=["name"], limit_page_length=0,
        ))
    return list(active)


def _task_assignments(names):
    if not names:
        return {}
    rows = frappe.get_all(
        "ToDo",
        filters={"reference_type": "Task", "reference_name": ["in", names],
                 "status": ["!=", "Cancelled"]},
        fields=["reference_name", "allocated_to", "status"],
        order_by="creation desc",
    )
    users = list({r.allocated_to for r in rows if r.allocated_to})
    labels = {r.name: r.full_name for r in frappe.get_all(
        "User", filters={"name": ["in", users]}, fields=["name", "full_name"]
    )} if users else {}
    result = {}
    for row in rows:
        task = result.setdefault(row.reference_name, {"assignees": {}, "previous_assignees": {}})
        key = "assignees" if row.status == "Open" else "previous_assignees"
        if row.allocated_to:
            task[key][row.allocated_to] = {
                "name": row.allocated_to,
                "full_name": labels.get(row.allocated_to) or row.allocated_to,
            }
    return result


def _serialize_task(doc, assignments=None):
    if assignments is None:
        assignments = _task_assignments([doc.name])
    people = assignments.get(doc.name, {})
    active = people.get("assignees", {})
    previous = people.get("previous_assignees", {})
    can_write = bool(frappe.has_permission("Task", "write", doc=doc))
    status = doc.status or "Open"
    due = _task_date(doc.exp_end_date)
    return {
        "name": doc.name,
        "subject": doc.subject or "",
        "description": doc.description or "",
        "status": status,
        "priority": doc.priority or "Medium",
        "progress": float(doc.progress or 0),
        "exp_start_date": _task_date(doc.exp_start_date),
        "exp_end_date": due,
        "project": doc.project or "",
        "company": doc.company or "",
        "department": doc.department or "",
        "owner": doc.owner or "",
        "creation": str(doc.creation or ""),
        "modified": str(doc.modified or ""),
        "is_group": bool(doc.is_group),
        "is_template": bool(doc.is_template),
        "is_overdue": status == "Overdue" or bool(
            due and due < frappe.utils.today() and status not in _TASK_FINISHED
        ),
        "assignees": list(active.values()),
        "previous_assignees": [v for k, v in previous.items() if k not in active],
        "can_write": can_write,
        "allowed_statuses": [s for s in _task_choices("status")
                             if s != "Template" or doc.is_template] if can_write else [],
    }


@_task_api()
def get_tasks(token=None, scope="mine", status="Active", date=None,
              include_overdue=1, allocated_to=None, search_text=None,
              company=None, project=None, limit=20, offset=0, **kwargs):
    """List real Tasks with permission-aware totals, never standalone ToDos."""
    _task_require_permission("read")
    if scope not in ("mine", "accessible"):
        frappe.throw("Invalid scope. Use: mine, accessible")
    limit, offset = _task_pagination(limit, offset)
    filters = []
    users = {frappe.session.user} if scope == "mine" else set()
    if allocated_to:
        users.add(allocated_to.strip())
    for user in users:
        filters.append(["name", "in", _task_assigned_names(user) or [""]])
    if status == "Active":
        filters.append(["status", "not in", list(_TASK_FINISHED)])
    elif status and status != "All" and status != "Overdue":
        if status not in _task_choices("status"):
            frappe.throw("Invalid Task status")
        filters.append(["status", "=", status])
    if status == "Overdue":
        overdue_names = [r.name for r in frappe.get_list(
            "Task", fields=["name"], limit_page_length=0,
            filters={"status": ["not in", list(_TASK_FINISHED)]},
            or_filters=[["status", "=", "Overdue"],
                        ["exp_end_date", "<", frappe.utils.today()]],
        )]
        filters.append(["name", "in", overdue_names or [""]])
    for field, value in (("company", company), ("project", project)):
        if value:
            filters.append([field, "=", value])
    or_filters = []
    if date and date != "all":
        target = frappe.utils.today() if date == "today" else _task_date(date)
        filters.append(["exp_end_date", "<=" if int(include_overdue or 0) else "=", target])
    search_text = (search_text or "").strip()
    if search_text:
        or_filters = [[f, "like", f"%{search_text}%"] for f in ("name", "subject", "description")]
    query = {"filters": filters, "or_filters": or_filters}
    counts = frappe.get_list("Task", fields=["status", "count(name) as count"],
                             group_by="status", limit_page_length=0, **query)
    by_status = {r.status: int(r.count) for r in counts}
    overdue = frappe.get_list(
        "Task", fields=["count(name) as count"],
        filters=filters + [["status", "not in", list(_TASK_FINISHED) + ["Overdue"]],
                           ["exp_end_date", "<", frappe.utils.today()]],
        or_filters=or_filters,
    )
    total = sum(by_status.values())
    rows = frappe.get_list(
        "Task", fields=_TASK_FIELDS, order_by="modified desc, name asc",
        limit_page_length=limit, limit_start=offset, **query,
    )
    assignments = _task_assignments([r.name for r in rows])
    return {
        "success": True, "user": frappe.session.user, "date": frappe.utils.today(),
        "scope": scope, "status": status,
        "can_create": bool(frappe.has_permission("Task", "create")),
        "summary": {
            "total_items": total, "open_count": by_status.get("Open", 0),
            "working_count": by_status.get("Working", 0),
            "pending_review_count": by_status.get("Pending Review", 0),
            "completed_count": by_status.get("Completed", 0),
            "cancelled_count": by_status.get("Cancelled", 0),
            "overdue_count": by_status.get("Overdue", 0) + int(overdue[0].count or 0),
        },
        "tasks": [_serialize_task(frappe.get_doc("Task", r.name), assignments) for r in rows],
        "limit": limit, "offset": offset, "has_more": offset + len(rows) < total,
        "is_search": bool(search_text),
    }


@_task_api()
def get_task(token=None, name=None, **kwargs):
    doc = frappe.get_doc("Task", (name or "").strip())
    doc.check_permission("read")
    task = _serialize_task(doc)
    return {"success": True, "can_write": task["can_write"], "task": task}


def _task_values(data, *, creating=False):
    values = {field: data[field] for field in _TASK_EDIT_FIELDS if field in data}
    if creating or "subject" in values:
        values["subject"] = str(values.get("subject") or "").strip()
        if not values["subject"]:
            frappe.throw("Missing subject")
    for field in ("exp_start_date", "exp_end_date"):
        if field in values:
            values[field] = _task_date(values[field]) or None
    for field in ("company", "project"):
        if field in values:
            values[field] = values[field] or None
    if "priority" in values and values["priority"] not in _task_choices("priority"):
        frappe.throw("Invalid Task priority")
    if "status" in values and values["status"] not in _task_choices("status"):
        frappe.throw("Invalid Task status")
    if "progress" in values:
        progress = float(values["progress"])
        if not math.isfinite(progress) or not 0 <= progress <= 100:
            frappe.throw("Progress must be between 0 and 100")
        values["progress"] = progress
    return values


def _task_users(assignees):
    if isinstance(assignees, str):
        assignees = frappe.parse_json(assignees)
    if not isinstance(assignees, list) or any(not isinstance(u, str) for u in assignees):
        frappe.throw("Assignees must be a list of User names")
    users = list(dict.fromkeys(u.strip() for u in assignees if u.strip()))
    for user in users:
        if user == "Guest" or not frappe.get_cached_value("User", user, "enabled"):
            frappe.throw(f"User '{user}' is not active")
    return users


def _task_sync_assignments(doc, users, values=None):
    from frappe.desk.form import assign_to

    values = values or {}
    rows = frappe.get_all("ToDo", filters={"reference_type": "Task", "reference_name": doc.name,
                                          "status": "Open"}, fields=["allocated_to"])
    current = {r.allocated_to for r in rows}
    for user in current - set(users):
        assign_to.remove("Task", doc.name, user)
    added = [u for u in users if u not in current]
    if added:
        priority = values.get("priority", doc.priority) or "Medium"
        assign_to.add({"doctype": "Task", "name": doc.name, "assign_to": json.dumps(added),
                       "description": values.get("subject", doc.subject),
                       "date": _task_date(values.get("exp_end_date", doc.exp_end_date)) or frappe.utils.today(),
                       # ToDo has no Urgent option; the Task keeps its real priority.
                       "priority": "High" if priority == "Urgent" else priority})


@_task_api(write=True)
def create_task(token=None, **kwargs):
    _task_require_permission("create")
    values = _task_values(kwargs, creating=True)
    values["status"] = "Open"
    users = _task_users(kwargs.get("assignees", []))
    doc = frappe.get_doc({"doctype": "Task", **values})
    doc.insert()
    _task_sync_assignments(doc, users)
    doc.reload()
    return {"success": True, "task": _serialize_task(doc)}


@_task_api(write=True)
def update_task(token=None, name=None, modified=None, **kwargs):
    doc = frappe.get_doc("Task", (name or "").strip(), for_update=True)
    doc.check_permission("read")
    doc.check_permission("write")
    if modified and str(doc.modified) != str(modified):
        frappe.throw("Task has changed. Refresh before saving.")
    values = _task_values(kwargs)
    if "assignees" in kwargs:
        users = _task_users(kwargs["assignees"])
        if doc.status in ("Completed", "Cancelled"):
            frappe.throw("Reopen the Task before changing assignments")
        _task_sync_assignments(doc, users, values)
        doc.reload()
    doc.update(values)
    doc.save()
    doc.reload()
    return {"success": True, "task": _serialize_task(doc)}


@_task_api()
def get_task_options(token=None, kind="all", search_text=None, company=None, limit=20, **kwargs):
    """Task metadata and native Link searches; no ToDo role requirement."""
    if not (frappe.has_permission("Task", "read") or frappe.has_permission("Task", "create")):
        frappe.throw("Access denied", frappe.PermissionError)
    from frappe.desk.search import search_link

    if kind not in ("all", "users", "projects", "companies"):
        frappe.throw("Invalid Task options kind")
    limit, _ = _task_pagination(limit)
    search_text = (search_text or "").strip()
    result = {"success": True, "statuses": _task_choices("status"),
              "priorities": _task_choices("priority"),
              "can_create": bool(frappe.has_permission("Task", "create"))}
    if kind in ("all", "users"):
        links = search_link(doctype="User", txt=search_text, page_length=limit,
                            reference_doctype="Task", filters={"enabled": 1}) or []
        names = [r.get("value") for r in links if r.get("value") and r.get("value") != "Guest"]
        metadata = {r.name: r.full_name for r in frappe.get_all(
            "User", filters={"name": ["in", names]}, fields=["name", "full_name"]
        )} if names else {}
        result["users"] = [{"name": n, "full_name": metadata.get(n) or n} for n in names]
    if kind in ("all", "projects"):
        try:
            result["projects"] = frappe.get_list(
                "Project", fields=["name", "project_name", "company"],
                filters={"company": company} if company else {},
                or_filters=[[f, "like", f"%{search_text}%"] for f in ("name", "project_name")] if search_text else [],
                limit_page_length=limit, order_by="modified desc",
            )
        except frappe.PermissionError:
            result["projects"] = []
    if kind in ("all", "companies"):
        try:
            result["companies"] = [r.name for r in frappe.get_list("Company", fields=["name"], limit_page_length=0)]
        except frappe.PermissionError:
            result["companies"] = []
    return result
