"""Permission-aware mobile API for ERPNext support Issues."""
import frappe

def _user(token):
    from mobile_app.api import authenticate_employee
    user = authenticate_employee(token)
    if not user or user == "Guest" or not frappe.get_cached_value("User", user, "enabled"):
        frappe.throw("Invalid session", frappe.AuthenticationError)
    frappe.set_user(user)

def _doc(name, p="read"):
    doc = frappe.get_doc("Issue", name)
    doc.check_permission(p)
    return doc

def _data(doc):
    return {k: str(doc.get(k) or "") for k in ("name", "subject", "status", "priority", "issue_type", "customer", "description", "raised_by", "opening_date", "modified")}

def _issue_assignees(name):
    rows = frappe.get_all("ToDo", filters={"reference_type": "Issue", "reference_name": name,
        "status": "Open"}, fields=["allocated_to"], order_by="creation asc")
    users = list(dict.fromkeys(row.allocated_to for row in rows if row.allocated_to))
    labels = {row.name: row.full_name for row in frappe.get_all(
        "User", filters={"name": ["in", users]}, fields=["name", "full_name"]
    )} if users else {}
    return [{"email": user, "full_name": labels.get(user) or user} for user in users]
def _api(methods):
    def deco(fn):
        @frappe.whitelist(allow_guest=True, methods=methods)
        def run(*args, **kwargs):
            savepoint = None
            try:
                req = getattr(frappe.local, "request", None)
                body = req.get_json(silent=True) if req and req.is_json else None
                values = dict(body or {})
                values.update(kwargs)
                if args:
                    values.setdefault("name", args[0])
                _user(values.get("token"))
                if "POST" in methods:
                    savepoint = "mobile_issue_mutation"
                    frappe.db.savepoint(savepoint)
                return fn(**values)
            except Exception as exc:
                if savepoint:
                    frappe.db.rollback(save_point=savepoint)
                if isinstance(exc, (frappe.PermissionError, frappe.AuthenticationError)):
                    return {"error": "Access denied"}
                if isinstance(exc, frappe.DoesNotExistError):
                    return {"error": "Issue not found"}
                if isinstance(exc, (frappe.ValidationError, ValueError, TypeError)):
                    return {"error": str(exc)}
                frappe.log_error(frappe.get_traceback(), fn.__name__ + " mobile API")
                return {"error": "Unable to process Issue"}
        return run
    return deco

@_api(["GET"])
def get_issues(search_text="", status="All", limit=20, offset=0, **kwargs):
    frappe.has_permission("Issue", "read", throw=True)
    limit, offset = min(max(int(limit or 20), 1), 100), max(int(offset or 0), 0)
    filters = {"status": status} if status and status != "All" else {}
    ors = {"subject": ["like", f"%{search_text}%"], "name": ["like", f"%{search_text}%"]} if search_text else None
    rows = frappe.get_list("Issue", filters=filters, or_filters=ors, fields=["name", "subject", "status", "priority", "issue_type", "customer", "opening_date", "modified"], order_by="modified desc", limit_start=offset, limit_page_length=limit)
    total = len(frappe.get_list("Issue", filters=filters, or_filters=ors, fields=["name"]))
    return {"issues": [dict(x) for x in rows], "total": total, "has_more": offset + len(rows) < total, "can_create": frappe.has_permission("Issue", "create")}

@_api(["GET"])
def get_issue(name=None, **kwargs):
    doc = _doc(name)
    comms = frappe.get_all("Communication", filters={"reference_doctype": "Issue", "reference_name": name, "communication_type": "Communication"}, fields=["name", "sender", "content", "creation", "sent_or_received"], order_by="creation asc", limit_page_length=200)
    return {"issue": _data(doc), "communications": [dict(x) for x in comms], "assignees": _issue_assignees(name), "statuses": (frappe.get_meta("Issue").get_field("status").options or "Open").splitlines(), "can_write": frappe.has_permission("Issue", "write", doc=doc)}

@_api(["POST"])
def create_issue(subject=None, description=None, priority=None, issue_type=None, status=None, assignees=None, **kwargs):
    frappe.has_permission("Issue", "create", throw=True)
    if not (subject or "").strip(): frappe.throw("Subject is required")
    doc = frappe.new_doc("Issue"); doc.subject = subject.strip(); doc.description = description or ""; doc.raised_by = frappe.session.user
    if priority: doc.priority = priority
    if issue_type: doc.issue_type = issue_type
    if status: doc.status = status

    doc.insert()
    if isinstance(assignees, str):
        assignees = frappe.parse_json(assignees)
    if assignees:
        if not isinstance(assignees, list):
            frappe.throw("Assignees must be a list of User names")
        users = list(dict.fromkeys(str(user).strip() for user in assignees if str(user).strip()))
        for user in users:
            if user == "Guest" or not frappe.get_cached_value("User", user, "enabled"):
                frappe.throw("Assignee is not an active user")
        from frappe.desk.form import assign_to
        assign_to.add({"doctype": "Issue", "name": doc.name, "assign_to": frappe.as_json(users),
                       "description": "Issue " + doc.name, "date": frappe.utils.today()})
    return {"issue": _data(doc), "assignees": _issue_assignees(doc.name)}


@_api(["POST"])
def reply_to_issue(name=None, content=None, **kwargs):
    doc = _doc(name, "write")
    if not (content or "").strip(): frappe.throw("Reply is required")
    comm = frappe.get_doc({"doctype":"Communication", "communication_type":"Communication", "communication_medium":"Other", "sent_or_received":"Sent", "sender":frappe.session.user, "subject":doc.subject, "content":content.strip(), "status":"Linked", "reference_doctype":"Issue", "reference_name":name})
    comm.insert()
    if doc.status == "Open": doc.status = "Replied"; doc.save()
    return {"communication":{"name":comm.name,"sender":comm.sender,"content":comm.content,"creation":str(comm.creation),"sent_or_received":comm.sent_or_received},"issue":_data(doc)}

@_api(["POST"])
def create_task_from_issue(token=None, name=None, task_type=None, assignees=None, **kwargs):
    issue = _doc(name, "read")
    from mobile_app.employee_tasks import create_task
    if not task_type and issue.issue_type and frappe.db.exists("Task Type", issue.issue_type):
        task_type = issue.issue_type
    result = create_task(token=token, subject=issue.subject,
        description=(issue.description or ""), issue=issue.name,
        type=task_type or None, assignees=assignees or [])
    if result.get("error"):
        frappe.throw(result["error"])
    return result





@_api(["GET"])
def get_issue_options(kind="metadata", search_text="", **kwargs):
    if not (frappe.has_permission("Issue", "read") or frappe.has_permission("Issue", "create")):
        frappe.throw("Access denied", frappe.PermissionError)
    return {
        "statuses": (frappe.get_meta("Issue").get_field("status").options or "Open").splitlines(),
        "issue_types": [x.name for x in frappe.get_list("Issue Type", fields=["name"], order_by="name asc", limit_page_length=100)],
        "priorities": [x.name for x in frappe.get_list("Issue Priority", fields=["name"], order_by="name asc", limit_page_length=100)],
    }







@_api(["GET"])
def get_issue_users(search_text="", **kwargs):
    if not (frappe.has_permission("Issue", "read") or frappe.has_permission("Issue", "create")):
        frappe.throw("Access denied", frappe.PermissionError)
    from frappe.desk.search import search_link
    matches = search_link(doctype="User", txt=(search_text or "").strip(), page_length=20,
                          reference_doctype="Issue", filters={"enabled": 1}) or []
    names = [row.get("value") for row in matches if row.get("value") and row.get("value") != "Guest"]
    users = frappe.get_all("User", filters={"name": ["in", names]}, fields=["name", "full_name"]) if names else []
    labels = {row.name: row.full_name for row in users}
    return {"users": [{"email": user, "full_name": labels.get(user) or user} for user in names]}




@_api(["POST"])
def update_issue_status(name=None, status=None, **kwargs):
    doc = _doc(name, "write")
    choices = (frappe.get_meta("Issue").get_field("status").options or "Open").splitlines()
    if status not in choices:
        frappe.throw("Invalid Issue status")
    doc.status = status
    doc.save()
    return {"issue": _data(doc)}
