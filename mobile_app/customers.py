"""Mobile customer profiles, access codes and complaints."""

import hmac
import json

import frappe
from frappe.rate_limiter import rate_limit

from mobile_app import customer_sessions


def _profile_for_code(code):
    frappe.flags.private_mobile_customer_response = True
    if not isinstance(code, str) or not code or len(code) > 140:
        return None
    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code, "disabled": 0},
        fields=["name", "customer_name", "email_id", "mobile_no", "custom_debt", "custom_debt_date",
                "custom_customer_code", "default_price_list"],
        limit=2,
    )
    if len(customer) == 1 and hmac.compare_digest(customer[0].custom_customer_code.encode(), code.encode()):
        return customer[0]
    return None


@rate_limit(limit=20, seconds=300)
def get_client_by_code(code=None):
    customer = _profile_for_code(code)
    return {"customer": customer} if customer else {"error": "Customer not found"}


@rate_limit(limit=10, seconds=300)
def login_customer(code=None):
    customer = _profile_for_code(code)
    if not customer:
        return {"error": "Invalid customer code"}
    return {"customer": customer, "customer_session": customer_sessions.issue(customer.name, code)}


@rate_limit(limit=10, seconds=300)
def change_customer_code(old_code=None, new_code=None):
    if not isinstance(old_code, str) or not isinstance(new_code, str):
        return {"success": False, "error": "Missing old_code or new_code"}

    old_code = old_code.strip()
    new_code = new_code.strip()

    if not new_code or len(new_code) > 140:
        return {"success": False, "error": "Invalid new code"}
    customer = _profile_for_code(old_code)
    if not customer:
        return {"success": False, "error": "Customer not found"}

    existing = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": new_code},
        fields=["name"],
        limit=1
    )
    if existing:
        return {"success": False, "error": "New code already used by another customer"}

    try:
        # Serialize concurrent rotations and recheck the secret under the row lock.
        current = frappe.db.get_value("Customer", customer.name, "custom_customer_code", for_update=True)
        if not current or not hmac.compare_digest(current.encode(), old_code.encode()):
            return {"success": False, "error": "Customer not found"}
        frappe.db.set_value("Customer", customer.name, "custom_customer_code", new_code)
        customer_sessions.invalidate_all(customer.name)
        frappe.db.commit()

        return {
            "success":       True,
            "customer_name": customer.customer_name,
        }
    except Exception as e:
        frappe.db.rollback()
        return {"success": False, "error": str(e)}


def create_customer_complaint():
    try:
        if frappe.request.method != "POST":
            return {"error": "Method not allowed"}

        data = json.loads(frappe.request.data)

        doc = frappe.get_doc({
            "doctype":                "reclamtion client",
            "client":                 data.get("client"),
            "date_reception":         data.get("date_reception") or frappe.utils.today(),
            "documents_reference":    data.get("reference"),
            "desciption_reclamation": data.get("description"),
            "docstatus":              0
        })

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return {"message": "Success", "id": doc.name}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Mobile Complaint Error")
        return {"error": str(e)}
