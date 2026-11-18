"""Employee login and session lookup."""

import frappe


def get_user_from_sid(token):
    """Retrieves the ERPNext user from the session SID using direct SQL query on tabSessions."""
    if not token:
        return None
    try:
        result = frappe.db.sql(
            "SELECT user, status FROM tabSessions WHERE sid=%s LIMIT 1",
            (token,),
            as_dict=True
        )
        if result and result[0].get("status") != "Expired":
            return result[0].get("user")
    except Exception:
        pass
    return None


def authenticate_employee(token):
    """Resolve the SID and switch the request to that ERPNext user so Role + User Permissions apply."""
    user = get_user_from_sid(token)
    if not user:
        return None
    frappe.set_user(user)
    return user


def login(email: str, password: str):
    if not email or not password:
        return {"ok": False, "error": "Missing email or password"}

    try:
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(user=email, pwd=password)
        login_manager.post_login()

        sid = frappe.session.sid
        user = frappe.session.user
        full_name = frappe.db.get_value("User", user, "full_name")
        return {"user": {"sid": sid, "email": user, "name": full_name}}

    except frappe.AuthenticationError:
        frappe.clear_messages()
        return {"ok": False, "error": "Invalid credentials"}


def get_my_user_name(token=None):
    user = authenticate_employee(token)
    if not user or user == "Guest" or not frappe.get_cached_value("User", user, "enabled"):
        return {"error": "Invalid session"}
    return {"name": frappe.get_cached_value("User", user, "full_name") or ""}
