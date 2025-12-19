import frappe


@frappe.whitelist(allow_guest=True)  # Or remove allow_guest for authenticated access only
def hello_world(name=None):
    return {
        "message": f"Hello, {name or 'Guest'}!"
    }




################################################################################
############################### Log In Function ################################
################################################################################



@frappe.whitelist(allow_guest=True)
def login(email: str, password: str):
    if not email or not password:
        return {"ok": False, "error": "Missing email or password"}

    print("the email is", email)
    print("the password is", password)

    try:
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(user=email, pwd=password)
        login_manager.post_login()

        # session id (sid) is also set as cookie automatically if you call via browser.
        sid = frappe.session.sid
        # reliable full name
        full_name = frappe.db.get_value("User", email, "full_name") 

        return {
            "user" : {
                "sid"   : sid,
                "email" : frappe.session.user,
                "name"  : full_name,
            }
        }

    except frappe.AuthenticationError:
        frappe.clear_messages()
        return {"ok": False, "error": "Invalid credentials"}






################################################################################
######################  Get All Stock Entry Function ###########################
################################################################################




import frappe
from frappe import _

@frappe.whitelist(allow_guest=True)
def get_last_stock_entries(token: str, limit: int = 20):
    # If you already have a token validation helper, call it here.
    # Example:
    # user = validate_mobile_token(token)
    # frappe.set_user(user)

    limit = int(limit or 20)

    # fetch latest submitted entries
    rows = frappe.get_all(
        "Stock Entry",
        fields=[
            "name",
            "posting_date",
            "from_warehouse",
            "to_warehouse",
            "workflow_state",
            "docstatus",
        ],
        filters={"docstatus": 1},
        order_by="creation desc",
        limit=limit,
    )


    # map to mobile expected keys
    out = []
    for r in rows:
        out.append({
            "name": r.get("name"),
            "posting_date": str(r.get("posting_date") or ""),
            "from": r.get("from_warehouse") or "",
            "to": r.get("to_warehouse") or "",
            "status": (r.get("workflow_state") or ("Submitted" if r.get("docstatus") == 1 else "Draft")),
        })

    return out







@frappe.whitelist(allow_guest=True)  # Allow without login
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
        user = frappe.get_all(
            "User",
            filters={"new_password":code},
            limit = 1
        )
        if not user:
            return {"error": "Customer or User not found"}
        return{"user":user[0]}

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

    # Step 2: Fetch all Notification filtered by customer and only committed docs (docstatus = 1)
    all_notification = frappe.get_all(
        "Mobile Notification",
        filters={
            "customer": customer_name,
            "docstatus": 1  # Only get committed documents
        },
        fields=["name", "msg", "title"],
    )
    

    return {
        "notification": all_notification,
    }


@frappe.whitelist(allow_guest=True)
def get_payments_by_customer_code(code=None):
    """
    Public endpoint to get payment entries for a customer by their custom code.
    """
    if not code:
        return {"error": "Missing customer code"}

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

    # Step 2: Fetch all Payment Entries for the customer (only committed entries)
    payment_entries = frappe.get_all(
        "Payment Entry",
        filters={
            "party": customer_name,
            "docstatus": 1,  # Only get committed documents
            "party_type": "Customer"
        },
        fields=["name", "posting_date", "paid_amount", "payment_type", "mode_of_payment", "reference_no", "reference_date"],
        order_by="posting_date desc"
    )

    return {
        "payments": payment_entries
    }
