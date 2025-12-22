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




@frappe.whitelist(allow_guest=True)
def get_last_stock_entries(token: str, limit: int = 20):
    # If you already have a token validation helper, call it here.
    # Example:
    # user = validate_mobile_token(token)
    # frappe.set_user(user)

    limit = int(limit or 20)
    # docstatus: 0 = Draft, 1 = Submitted, 2 = Cancelled
    allowed_docstatus = [0, 1]

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
        filters={"docstatus": ["in", allowed_docstatus]},
        order_by="posting_date desc",
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








@frappe.whitelist(allow_guest=True)
def get_stock_entry_details_by_name(token: str, name: str):
    """
    Public endpoint to get Stock Entry full details by document name.
    Returns: header + items rows.
    """

    # If you already have a token validation helper, call it here.
    # user = validate_mobile_token(token)
    # frappe.set_user(user)

    if not name:
        return {"error": "Missing Stock Entry name"}

    # Ensure Stock Entry exists
    if not frappe.db.exists("Stock Entry", name):
        return {"error": "Stock Entry not found"}

    doc = frappe.get_doc("Stock Entry", name)

    # Optional: prevent exposing cancelled docs
    if doc.docstatus == 2:
        return {"error": "Stock Entry is cancelled"}


    # Items
    items = []
    for it in (doc.get("items") or []):
        items.append({
            "id"             : it.name,  
            "idx"            : it.idx,
            "itemName"       : it.item_code or "",
            "stockEntryName" : it.item_code or "",
            "fromWarehouse"  : it.s_warehouse or "",
            "toWarehouse"    : it.t_warehouse or "",
            "quantity"       : float(it.qty or 0),
        })

    return {
        "stockEntry" : {
            "name": doc.name,
            "postingDate": str(doc.posting_date or ""),
            "fromWarehouse": doc.from_warehouse or "",
            "toWarehouse": doc.to_warehouse or "",
            "company": doc.company or "",
            "status": doc.workflow_state,
        },
        "items": items,
    }






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



import frappe

@frappe.whitelist(allow_guest=True)
def get_payments_by_customer_code(code=None):
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

    # Step 2: Fetch Payment Entries (submitted only)
    payments = frappe.get_all(
        "Payment Entry",
        filters={
            "party_type": "Customer",
            "party": customer_name,
            "docstatus": 1
        },
        fields=["name", "posting_date", "paid_amount", "payment_type", "mode_of_payment"],
        order_by="posting_date desc"
    )

    if not payments:
        return {"payments": []}

    pe_names = [p["name"] for p in payments]

    # Step 3: Fetch referenced invoices for those Payment Entries
    refs = frappe.get_all(
        "Payment Entry Reference",
        filters={
            "parent": ["in", pe_names],
            "reference_doctype": "Sales Invoice"
        },
        fields=[
            "parent",               # Payment Entry name
            "reference_name",       # Sales Invoice name
            "allocated_amount",
            "total_amount",
            "outstanding_amount"
        ],
        order_by="parent desc"
    )

    # Step 4: (optional but useful) Get invoice extra info (status, grand_total, outstanding)
    invoice_names = list({r["reference_name"] for r in refs})
    invoice_map = {}
    if invoice_names:
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", invoice_names]},
            fields=["name", "posting_date", "status", "grand_total", "outstanding_amount"],
        )
        invoice_map = {inv["name"]: inv for inv in invoices}

    # Group references by payment entry
    refs_by_payment = {}
    for r in refs:
        inv = invoice_map.get(r["reference_name"], {})
        refs_by_payment.setdefault(r["parent"], []).append({
            "invoice": r["reference_name"],
            "allocated_amount": r.get("allocated_amount"),
            "invoice_posting_date": inv.get("posting_date"),
            "invoice_status": inv.get("status"),
            "invoice_total": inv.get("grand_total"),
            "invoice_outstanding": inv.get("outstanding_amount"),
        })

    # Attach invoices list to each payment
    for p in payments:
        p["invoices_payed"] = refs_by_payment.get(p["name"], [])

    return {"payments": payments}
