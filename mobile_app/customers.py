"""Mobile customer profiles, access codes and complaints."""

import hmac

import frappe
from frappe.rate_limiter import rate_limit

from mobile_app import customer_sessions


PROFILE_FIELDS = ["name", "customer_name", "email_id", "mobile_no", "custom_debt",
                  "custom_debt_date", "default_price_list"]


def _profile_for_code(code):
    frappe.flags.private_mobile_customer_response = True
    if not isinstance(code, str) or not code or len(code) > 140:
        return None
    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code, "disabled": 0},
        fields=[*PROFILE_FIELDS, "custom_customer_code"],
        limit=2,
    )
    if len(customer) == 1 and hmac.compare_digest(customer[0].custom_customer_code.encode(), code.encode()):
        return customer[0]
    return None


@rate_limit(limit=20, seconds=300)
def get_customer_profile():
    owner = customer_sessions.current_customer()
    if not owner:
        return {"error": "Invalid session"}
    customer = frappe.db.get_value("Customer", {"name": owner, "disabled": 0}, PROFILE_FIELDS, as_dict=True)
    return {"customer": customer} if customer else {"error": "Invalid session"}


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


def create_customer_complaint(description=None, date_reception=None, reference=None):
    customer = customer_sessions.current_customer()
    if not customer:
        return {"error": "Invalid session"}
    if not isinstance(description, str) or not description.strip():
        return {"error": "Missing complaint description"}

    receipt_date = date_reception or frappe.utils.today()
    try:
        if frappe.db.exists("DocType", "reclamtion client"):
            fields = {
                "doctype": "reclamtion client",
                "client": customer,
                "date_reception": receipt_date,
                "documents_reference": reference,
                "desciption_reclamation": description,
            }
        else:
            company = frappe.db.get_single_value("Global Defaults", "default_company")
            if not company:
                return {"error": "No default company configured for customer complaints"}
            fields = {
                "doctype": "Customer Complaint",
                "source_type": "Client",
                "company": company,
                "customer": customer,
                "receipt_date": receipt_date,
                "reference_documents": reference,
                "complaint_description": description,
            }
        doc = frappe.get_doc(fields)
        doc.insert(ignore_permissions=True)
        return {"message": "Success", "id": doc.name}
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title="Mobile Complaint Error", message=frappe.get_traceback())
        return {"error": "Unable to create complaint"}
