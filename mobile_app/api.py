

import frappe


@frappe.whitelist(allow_guest=True)  # Or remove allow_guest for authenticated access only
def hello_world(name=None):
    return {
        "message": f"Hello, {name or 'Guest'}!"
    }





@frappe.whitelist(allow_guest=True)  # ✅ Allow without login
def get_client_by_code(code=None):
    """
    Public endpoint to get a customer by their client code (custom field).
    """
    if not code:
        return {"error": "Missing client code"}

    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code},  # Replace with your actual field name
        fields=["name", "email_id", "mobile_no", "custom_customer_code" ],
        limit=1
    )

    if not customer:
        return {"error": "Customer not found"}

    return {"customer": customer[0]}

