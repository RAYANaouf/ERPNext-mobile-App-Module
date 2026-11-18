"""Mobile customer profiles, access codes and complaints."""

import json

import frappe


def get_client_by_code(code=None):
    if not code:
        return {"error": "Missing client code"}

    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code},
        fields=["name", "email_id", "mobile_no", "custom_debt", "custom_debt_date",
                "custom_customer_code", "default_price_list"],
        limit=1
    )

    if not customer:
        return {"error": "Customer not found"}

    return {"customer": customer[0]}


def change_customer_code(old_code=None, new_code=None):
    if not old_code or not new_code:
        return {"success": False, "error": "Missing old_code or new_code"}

    old_code = str(old_code).strip()
    new_code = str(new_code).strip()

    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": old_code},
        fields=["name", "customer_name", "custom_customer_code"],
        limit=1
    )
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
        frappe.db.set_value("Customer", customer[0]["name"], "custom_customer_code", new_code)
        frappe.db.commit()

        return {
            "success":       True,
            "customer_name": customer[0]["customer_name"],
            "old_code":      old_code,
            "new_code":      new_code
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
