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
