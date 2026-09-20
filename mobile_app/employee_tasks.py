################################################################################
######################  Employee Tasks (ToDo) Functions ########################
################################################################################
# Professional employee task APIs on ERPNext/Frappe ToDo.
# Managers create/assign ToDos in Desk; mobile shows only the logged-in employee's tasks.
#
# Example — list my tasks for today:
# curl -G "http://192.168.100.20:8000/api/method/mobile_app.api.get_my_tasks" \
#   --data-urlencode "token={{sid}}" \
#   --data-urlencode "status=Open" \
#   --data-urlencode "date=today" \
#   --data-urlencode "limit=20" \
#   --data-urlencode "offset=0"
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


@frappe.whitelist(allow_guest=True)
def get_my_tasks(
    token=None,
    status="Open",
    date=None,
    only_today=0,
    include_overdue=0,
    search_text=None,
    limit=20,
    offset=0,
):
    """
    List ToDo tasks allocated to the authenticated employee.
    Auth: token = SID (same pattern as stock / material request APIs).
    """
    from mobile_app.api import authenticate_employee

    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        user = frappe.session.user
        limit = int(limit or 20)
        offset = int(offset or 0)
        only_today = int(only_today or 0)
        include_overdue = int(include_overdue or 0)

        status = (status or "Open").strip()
        search_text = (search_text or "").strip()
        is_search = bool(search_text)
        date_param = (date or "").strip().lower() if date else ""

        filters = {"allocated_to": user}

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
                fields=[
                    "name", "description", "status", "priority", "date",
                    "allocated_to", "assigned_by",
                    "reference_type", "reference_name",
                    "creation", "modified",
                ],
                order_by="date asc, priority desc, modified desc",
                limit_page_length=limit,
                limit_start=offset,
            )
        except frappe.PermissionError:
            return {"error": "Access denied"}

        tasks = [
            _serialize_todo(r)
            for r in rows
            if (r.get("allocated_to") or "") == user
        ]

        try:
            all_matching = frappe.get_list(
                "ToDo",
                filters=filters,
                or_filters=or_filters,
                fields=["name", "status", "date", "allocated_to"],
                limit_page_length=5000,
            )
        except frappe.PermissionError:
            all_matching = []

        mine = [r for r in all_matching if (r.get("allocated_to") or "") == user]
        open_count = sum(1 for r in mine if (r.get("status") or "") == "Open")
        closed_count = sum(1 for r in mine if (r.get("status") or "") == "Closed")
        overdue_count = sum(
            1 for r in mine
            if (r.get("status") or "") == "Open"
            and r.get("date")
            and str(r.get("date")) < today_str
        )

        total_items = len(mine)
        has_more = (offset + limit) < total_items

        return {
            "success": True,
            "user": user,
            "date": today_str if (date_param == "today" or only_today) else (date_param if date_param not in ("", "all") else ""),
            "status": status,
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
    """Get one ToDo detail. Only if allocated_to = authenticated employee."""
    from mobile_app.api import authenticate_employee

    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        name = (name or "").strip()
        if not name:
            return {"error": "Missing name"}

        user = frappe.session.user

        if not frappe.db.exists("ToDo", name):
            return {"error": "Task not found"}

        try:
            doc = frappe.get_doc("ToDo", name)
        except frappe.PermissionError:
            return {"error": "Access denied"}

        if (doc.allocated_to or "") != user:
            return {"error": "Access denied"}

        return {
            "success": True,
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
def update_my_task_status(name=None, status=None, token=None):
    """
    Update status of a ToDo owned by the authenticated employee.
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

        user = frappe.session.user

        if not frappe.db.exists("ToDo", name):
            return {"error": "Task not found"}

        try:
            doc = frappe.get_doc("ToDo", name)
        except frappe.PermissionError:
            return {"error": "Access denied"}

        if (doc.allocated_to or "") != user:
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
