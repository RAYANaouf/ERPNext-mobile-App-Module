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
            "id"             : it.name or "",  
            "idx"            : it.idx,
            "itemName"       : it.item_code or "",
            "stockEntryName" : it.item_code or "",
            "fromWarehouse"  : it.s_warehouse or "",
            "toWarehouse"    : it.t_warehouse or "",
            "quantity"       : int(it.qty or 0),
            
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
        filters  = {"customer": customer_name , "docstatus": 1 , "is_consolidated": 0},
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
        filters  = {"customer": customer_name , "docstatus": 1 },
        fields   = ["name", "posting_date", "grand_total", "outstanding_amount", "status", "is_pos"],
        order_by ="posting_date desc"
    )

    return {
        "customer_code": code,
        "sales_invoices": all_invoices,
        "pos_invoices": pos_invoices
    }



@frappe.whitelist(allow_guest=True)
def get_single_invoice_details(invoice_name=None):
    """
    Get invoice details with items - SAFE VERSION
    """
    try:
        # Log pour debug
        frappe.log_error(f"get_single_invoice_details called with: {invoice_name}", "Invoice Detail Debug")
        
        if not invoice_name:
            return {"error": "Missing invoice name"}
        
        # Essayer Sales Invoice d'abord
        invoice_type = "Sales Invoice"
        if not frappe.db.exists(invoice_type, invoice_name):
            # Essayer POS Invoice
            invoice_type = "POS Invoice"
            if not frappe.db.exists(invoice_type, invoice_name):
                return {"error": "Invoice not found"}
        
        frappe.log_error(f"Found invoice type: {invoice_type}", "Invoice Detail Debug")
        
        # Méthode 1 : Utiliser get_doc (plus sûr)
        doc = frappe.get_doc(invoice_type, invoice_name)
        
        # Construire les items
        items = []
        for item in doc.items:
            items.append({
                "item_code": item.item_code or "",
                "item_name": item.item_name or item.item_code or "",
                "qty": float(item.qty or 0),
                "rate": float(item.rate or 0),
                "amount": float(item.amount or 0),
            })
        
        # Construire la réponse
        response = {
            "invoice": {
                "name": doc.name,
                "posting_date": str(doc.posting_date or ""),
                "grand_total": float(doc.grand_total or 0),
                "outstanding_amount": float(doc.outstanding_amount or 0),
                "status": doc.status or "",
                "total_qty": len(items),
            },
            "items": items,
        }
        
        frappe.log_error(f"Success! Returning {len(items)} items", "Invoice Detail Debug")
        return response
        
    except Exception as e:
        error_message = f"Error in get_single_invoice_details: {str(e)}"
        frappe.log_error(error_message, "Invoice Detail Error")
        frappe.log_error(frappe.get_traceback(), "Invoice Detail Traceback")
        return {"error": str(e)}
    
    
    

import frappe
import json

@frappe.whitelist(allow_guest=True)
def manage_stock_entry(name=None, items=None, action="save", token=None):

    try:
        frappe.log_error("=== manage_stock_entry called ===", "Stock Entry Debug")

        # ==============================
        # RÉCUPÉRER LE TOKEN
        # ==============================
        if not token:
            token = frappe.form_dict.get("token")

        # ==============================
        # LECTURE JSON BODY
        # ==============================
        if frappe.request and frappe.request.method == "POST":
            content_type = frappe.request.headers.get("Content-Type", "")

            if "application/json" in content_type:
                data = json.loads(frappe.request.data or "{}")
                name = name or data.get("name")
                items = items or data.get("items")
                action = data.get("action", action)
                token = token or data.get("token")

        # ==============================
        # VALIDATION TOKEN
        # ==============================
        if not token:
            return {"error": "Authentication required - no token"}

        # ==============================
        # VALIDATION PARAMÈTRES
        # ==============================
        if not name or not items:
            return {"error": "Missing parameters: name or items"}

        if not frappe.db.exists("Stock Entry", name):
            return {"error": f"Stock Entry '{name}' not found"}

        # ==============================
        # CHARGEMENT DU DOCUMENT
        # ==============================
        doc = frappe.get_doc("Stock Entry", name)

        if doc.docstatus != 0:
            return {"error": "Stock Entry already submitted or cancelled"}

        # ==============================
        # PARSER ITEMS
        # ==============================
        if isinstance(items, str):
            items = json.loads(items)

        # ==============================
        # INDEX DES ARTICLES EXISTANTS
        # ==============================
        existing_items = {row.item_code: row for row in doc.items}

        # ==============================
        # AJOUT / UPDATE DES ARTICLES
        # ==============================
        for it in items:
            item_code = it.get("item_code") or it.get("itemName")

            if not item_code:
                continue

            if not frappe.db.exists("Item", item_code):
                continue

            qty = float(it.get("quantity", 0))

            # 🔁 ARTICLE EXISTANT → UPDATE
            if item_code in existing_items:
                row = existing_items[item_code]
                row.qty = qty
                row.s_warehouse = it.get("fromWarehouse", row.s_warehouse)
                row.t_warehouse = it.get("toWarehouse", row.t_warehouse)

            # ➕ NOUVEL ARTICLE
            else:
                doc.append("items", {
                    "item_code": item_code,
                    "qty": qty,
                    "s_warehouse": it.get("fromWarehouse"),
                    "t_warehouse": it.get("toWarehouse"),
                })

        # ==============================
        # SAVE
        # ==============================
        doc.save(ignore_permissions=True)
        frappe.db.commit()

        # ==============================
        # SUBMIT SI APPROVE
        # ==============================
        if action == "approve":
            doc.submit()
            frappe.db.commit()
            return {
                "message": "Success",
                "detail": f"Stock Entry {name} approved successfully"
            }

        return {
            "message": "Success",
            "detail": f"Stock Entry {name} saved successfully"
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "manage_stock_entry error")
        return {"error": str(e)}


@frappe.whitelist(allow_guest=True)
def search_items(token=None, search_text=None):
    """
    Retourne les articles actifs pour autocomplete.
    """
    if not search_text:
        return []

    items = frappe.get_all(
        "Item",
        filters={
            "item_code": ["like", f"%{search_text}%"],
            "disabled": 0
        },
        fields=["item_code", "item_name"],
        limit=10
    )
    
    # Aussi chercher par item_name
    items_by_name = frappe.get_all(
        "Item",
        filters={
            "item_name": ["like", f"%{search_text}%"],
            "disabled": 0
        },
        fields=["item_code", "item_name"],
        limit=10
    )
    
    # Combiner et dédupliquer
    seen = set()
    result = []
    for item in items + items_by_name:
        if item['item_code'] not in seen:
            seen.add(item['item_code'])
            result.append(item)
    
    return result[:10]  # Limiter à 10 résultats