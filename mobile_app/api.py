

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
        fields=["name", "email_id", "mobile_no", "custom_debt" , "custom_debt_date" ,"custom_customer_code" ],
        limit=1
    )

    if not customer:
        return {"error": "Customer not found"}

    return {"customer": customer[0]}


@frappe.whitelist(allow_guest=True)
def get_invoices_by_customer_code(code=None):
    """
    Public endpoint to get both Sales Invoices and POS Invoices by a customer's custom code.
    """
    if not code:
        return {"error": "Missing client code"}

    # Step 1: Get customer by custom code
    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code},
        fields=["name"],
        limit=1
    )

    if not customer:
        return {"error": "Customer not found"}

    customer_name = customer[0].name

    # Step 2: Fetch all Sales Invoices (POS and non-POS)
    all_invoices = frappe.get_all(
        "Sales Invoice",
        filters={"customer": customer_name},
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "is_pos"],
        order_by="posting_date desc"
    )
    
    # Step 3: Fetch all POS Invoices (non-consolidated) 
    pos_invoices = frappe.get_all(
        "POS Invoice",
        filters  = {"customer": customer_name , "docstatus": 1  },
        fields   = ["name", "posting_date", "grand_total", "outstanding_amount", "status", "is_pos"],
        order_by ="posting_date desc"
    )

    return {
        "customer_code": code,
        "sales_invoices": all_invoices,
        "pos_invoices": pos_invoices
    }



@frappe.whitelist(allow_guest=True)
def get_notification_by_customer_code(code=None):
    """
    Public endpoint to get both Sales Invoices and POS Invoices by a customer's custom code.
    """
    if not code:
        return {"error": "Missing client code"}

    # Step 1: Get customer by custom code
    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code},
        fields=["name"],
        limit=1
    )

    if not customer:
        return {"error": "Customer not found"}

    customer_name = customer[0].name

    # Step 2: Fetch all Notification filttred by customer
    all_notification = frappe.get_all(
        "Mobile Notification",
        filters  ={"customer": customer_name},
        fields   = ["name", "msg"],
    )
    

    return {
        "notification": all_notification,
    }
