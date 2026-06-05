################################################################################
# IMPORTS 
################################################################################
import frappe
import json
import re
from frappe.utils import flt, add_days, today


################################################################################
####################  Helper — Get User From SID Token #########################
################################################################################

def get_user_from_sid(token):
    """Retrieves the ERPNext user from the session SID reliably."""
    if not token:
        return None
    try:
        session_info = frappe.db.get_value("Sessions", {"sid": token}, ["user", "status"], as_dict=True)
        if session_info and session_info.status != "Expired":
            return session_info.user
    except Exception:
        pass
    return None


def get_user_permissions(user):
    """
    Returns the allowed companies and warehouses for a given user.
    If no permissions are defined -> returns empty lists (no restrictions for Admins).
    """
    allowed_companies = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Company"},
        pluck="for_value"
    )
    allowed_warehouses = frappe.get_all(
        "User Permission",
        filters={"user": user, "allow": "Warehouse"},
        pluck="for_value"
    )
    return allowed_companies, allowed_warehouses


################################################################################
############################## Hello World Function ############################
################################################################################

@frappe.whitelist(allow_guest=True)
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

    try:
        login_manager = frappe.auth.LoginManager()
        login_manager.authenticate(user=email, pwd=password)
        login_manager.post_login()

        sid = frappe.session.sid
        full_name = frappe.db.get_value("User", email, "full_name")

        # Fetch user permissions to return them to the client
        allowed_companies, allowed_warehouses = get_user_permissions(email)

        return {
            "user": {
                "sid":                sid,
                "email":              frappe.session.user,
                "name":               full_name,
                "allowed_companies":  allowed_companies,
                "allowed_warehouses": allowed_warehouses,
            }
        }

    except frappe.AuthenticationError:
        frappe.clear_messages()
        return {"ok": False, "error": "Invalid credentials"}


################################################################################
######################  Get All Stock Entry Function ###########################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_last_stock_entries(token: str, limit: int = 20, offset: int = 0, search_text=None, status=None):
    limit  = int(limit  or 20)
    offset = int(offset or 0)

    user = get_user_from_sid(token)
    if not user:
        return {"error": "Invalid session"}

    allowed_companies, allowed_warehouses = get_user_permissions(user)

    allowed_docstatus = [0, 1]
    filters = {"docstatus": ["in", allowed_docstatus]}

    # Filter by allowed warehouse if restrictions exist
    if allowed_warehouses:
        filters["from_warehouse"] = ["in", allowed_warehouses]

    is_search = bool(search_text and str(search_text).strip())
    if is_search:
        filters["name"] = ["like", f"%{str(search_text).strip()}%"]

    if status and status != "All":
        filters["workflow_state"] = status

    rows = frappe.get_all(
        "Stock Entry",
        fields=["name", "posting_date", "from_warehouse",
                "to_warehouse", "workflow_state", "docstatus"],
        filters=filters,
        order_by="posting_date desc",
        limit=20  if is_search else limit,
        start=0   if is_search else offset
    )

    out = []
    for r in rows:
        out.append({
            "name":         r.get("name"),
            "posting_date": str(r.get("posting_date") or ""),
            "from":         r.get("from_warehouse") or "",
            "to":           r.get("to_warehouse") or "",
            "status":       r.get("workflow_state") or (
                            "Submitted" if r.get("docstatus") == 1 else "Draft"),
        })

    return {"stock_entries": out, "is_search": is_search}


################################################################################
##################  Get Stock Entry Details Function ###########################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_stock_entry_details_by_name(token: str, name: str):
    if not name:
        return {"error": "Missing Stock Entry name"}

    user = get_user_from_sid(token)
    if not user:
        return {"error": "Invalid session"}

    if not frappe.db.exists("Stock Entry", name):
        return {"error": "Stock Entry not found"}

    doc = frappe.get_doc("Stock Entry", name)

    if doc.docstatus == 2:
        return {"error": "Stock Entry is cancelled"}

    # Check warehouse access restrictions
    allowed_companies, allowed_warehouses = get_user_permissions(user)
    if allowed_warehouses and doc.from_warehouse and doc.from_warehouse not in allowed_warehouses:
        return {"error": "Access denied for this Stock Entry"}

    items = []
    for it in (doc.get("items") or []):
        items.append({
            "id":             it.name or "",
            "idx":            it.idx,
            "itemName":       it.item_name or it.item_code or "",
            "stockEntryName": it.item_code or "",
            "fromWarehouse":  it.s_warehouse or "",
            "toWarehouse":    it.t_warehouse or "",
            "quantity":       int(it.qty or 0),
        })

    return {
        "stockEntry": {
            "name":          doc.name,
            "postingDate":   str(doc.posting_date or ""),
            "fromWarehouse": doc.from_warehouse or "",
            "toWarehouse":   doc.to_warehouse or "",
            "company":       doc.company or "",
            "status":        doc.workflow_state,
        },
        "items": items,
    }


################################################################################
######################  Get Client By Code Function ############################
################################################################################

@frappe.whitelist(allow_guest=True)
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


################################################################################
##################  Get Invoices By Customer Code Function #####################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_invoices_by_customer_code(code=None, limit=20, offset=0, search_text=None, status=None):
    if not code:
        return {"error": "Missing client code"}

    limit  = int(limit)  if limit  else 20
    offset = int(offset) if offset else 0

    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code},
        fields=["name"],
        limit=1
    )
    if not customer:
        return {"error": "Customer not found"}

    customer_name = customer[0].name

    filters_sales = {"customer": customer_name}
    filters_pos   = {"customer": customer_name, "docstatus": 1}

    if search_text and str(search_text).strip():
        q = str(search_text).strip()
        filters_sales["name"] = ["like", f"%{q}%"]
        filters_pos["name"]   = ["like", f"%{q}%"]

    if status and status != "All":
        filters_sales["status"] = status
        filters_pos["status"]   = status

    is_search = bool(search_text and str(search_text).strip())

    sales_invoices = frappe.get_all(
        "Sales Invoice",
        filters=filters_sales,
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "is_pos"],
        order_by="posting_date desc",
        limit=20  if is_search else limit,
        start=0   if is_search else offset
    )

    pos_invoices = frappe.get_all(
        "POS Invoice",
        filters=filters_pos,
        fields=["name", "posting_date", "grand_total", "outstanding_amount", "status", "is_pos"],
        order_by="posting_date desc",
        limit=20  if is_search else limit,
        start=0   if is_search else offset
    )

    return {
        "customer_code":  code,
        "is_search":      is_search,
        "sales_invoices": sales_invoices,
        "pos_invoices":   pos_invoices
    }


################################################################################
################  Get Notification By Customer Code Function ###################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_notification_by_customer_code(code=None):
    if not code:
        return {"error": "Missing client code"}

    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code},
        fields=["name"],
        limit=1
    )

    if not customer:
        return {"error": "Customer not found"}

    customer_name = customer[0].name

    all_notification = frappe.get_all(
        "Mobile Notification",
        filters={"customer": customer_name, "docstatus": 1},
        fields=["name", "msg", "title"],
    )

    return {"notification": all_notification}


################################################################################
################  Get Payments By Customer Code Function #######################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_payments_by_customer_code(code=None, limit=20, offset=0, search_text=None):
    if not code:
        return {"error": "Missing customer code"}

    limit  = int(limit)  if limit  else 20
    offset = int(offset) if offset else 0

    customer = frappe.get_all(
        "Customer",
        filters={"custom_customer_code": code},
        fields=["name"],
        limit=1
    )
    if not customer:
        return {"error": "Customer not found"}

    customer_name = customer[0].name

    filters = {
        "party_type": "Customer",
        "party":      customer_name,
        "docstatus":  1
    }

    is_search = bool(search_text and str(search_text).strip())
    if is_search:
        filters["name"] = ["like", f"%{str(search_text).strip()}%"]

    payments = frappe.get_all(
        "Payment Entry",
        filters=filters,
        fields=["name", "posting_date", "paid_amount", "payment_type", "mode_of_payment"],
        order_by="posting_date desc",
        limit=20  if is_search else limit,
        start=0   if is_search else offset
    )

    if not payments:
        return {"payments": [], "is_search": is_search}

    pe_names = [p["name"] for p in payments]

    refs = frappe.get_all(
        "Payment Entry Reference",
        filters={"parent": ["in", pe_names], "reference_doctype": "Sales Invoice"},
        fields=["parent", "reference_name", "allocated_amount",
                "total_amount", "outstanding_amount"],
        order_by="parent desc"
    )

    invoice_names = list({r["reference_name"] for r in refs})
    invoice_map = {}
    if invoice_names:
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", invoice_names]},
            fields=["name", "posting_date", "status", "grand_total", "outstanding_amount"],
        )
        invoice_map = {inv["name"]: inv for inv in invoices}

    refs_by_payment = {}
    for r in refs:
        inv = invoice_map.get(r["reference_name"], {})
        refs_by_payment.setdefault(r["parent"], []).append({
            "invoice":              r["reference_name"],
            "allocated_amount":     r.get("allocated_amount"),
            "invoice_posting_date": inv.get("posting_date"),
            "invoice_status":       inv.get("status"),
            "invoice_total":        inv.get("grand_total"),
            "invoice_outstanding":  inv.get("outstanding_amount"),
        })

    for p in payments:
        p["invoices_payed"] = refs_by_payment.get(p["name"], [])

    return {"payments": payments, "is_search": is_search}


################################################################################
######################  Get Single Invoice Details Function ####################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_single_invoice_details(invoice_name=None):
    try:
        if not invoice_name:
            return {"error": "Missing invoice name"}

        invoice_type = "Sales Invoice"
        if not frappe.db.exists(invoice_type, invoice_name):
            invoice_type = "POS Invoice"
            if not frappe.db.exists(invoice_type, invoice_name):
                return {"error": "Invoice not found"}

        doc = frappe.get_doc(invoice_type, invoice_name)

        items = []
        for item in doc.items:
            items.append({
                "item_code": item.item_code or "",
                "qty":       float(item.qty or 0),
                "rate":      float(item.rate or 0),
                "amount":    float(item.amount or 0),
            })

        return {
            "invoice": {
                "name":               doc.name,
                "posting_date":       str(doc.posting_date or ""),
                "grand_total":        float(doc.grand_total or 0),
                "outstanding_amount": float(doc.outstanding_amount or 0),
                "status":             doc.status or "",
                "total_qty":          sum(float(i["qty"]) for i in items),
            },
            "items": items,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Invoice Detail Error")
        return {"error": str(e)}


################################################################################
######################  Manage Stock Entry Function ############################
################################################################################

@frappe.whitelist(allow_guest=True)
def manage_stock_entry(name=None, items=None, action="save"):
    try:
        token = None
        if frappe.request and frappe.request.method == "POST":
            content_type = frappe.request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data   = json.loads(frappe.request.data or "{}")
                name   = name   or data.get("name")
                items  = items  or data.get("items")
                action = data.get("action", action)
                token  = data.get("token")

        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        if not name or not items:
            return {"error": "Missing parameters: name or items"}

        if not frappe.db.exists("Stock Entry", name):
            return {"error": f"Stock Entry '{name}' not found"}

        doc = frappe.get_doc("Stock Entry", name)

        if doc.docstatus != 0:
            return {"error": "Stock Entry already submitted or cancelled"}

        # Validate warehouse access rights
        allowed_companies, allowed_warehouses = get_user_permissions(user)
        if allowed_warehouses and doc.from_warehouse and doc.from_warehouse not in allowed_warehouses:
            return {"error": "Access denied for this Stock Entry"}

        if isinstance(items, str):
            items = json.loads(items)

        existing_items = {row.item_code: row for row in doc.items}

        for it in items:
            item_code = it.get("item_code") or it.get("itemName")
            if not item_code or not frappe.db.exists("Item", item_code):
                continue

            qty = float(it.get("quantity", 0))

            if item_code in existing_items:
                row = existing_items[item_code]
                row.qty         = qty
                row.s_warehouse = it.get("fromWarehouse", row.s_warehouse)
                row.t_warehouse = it.get("toWarehouse",   row.t_warehouse)
            else:
                doc.append("items", {
                    "item_code":   item_code,
                    "qty":         qty,
                    "s_warehouse": it.get("fromWarehouse"),
                    "t_warehouse": it.get("toWarehouse"),
                })

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        if action == "approve":
            doc.submit()
            frappe.db.commit()
            return {"message": "Success", "detail": f"Stock Entry {name} approved successfully"}

        return {"message": "Success", "detail": f"Stock Entry {name} saved successfully"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "manage_stock_entry error")
        return {"error": str(e)}


################################################################################
############################  Search Items Function ############################
################################################################################

@frappe.whitelist(allow_guest=True)
def search_items(search_text=None, customer_code=None):

    if not search_text:
        return []

    search_text = str(search_text).strip()

    if len(search_text) > 50:
        return {"status": "error", "message": "Search text too long (max 50 characters)"}

    if not re.match(r'^[\w\s\-\.+]+$', search_text, re.UNICODE):
        return {"status": "error", "message": "Unauthorized characters in search text"}

    items = frappe.get_all(
        "Item",
        filters={"disabled": 0, "is_sales_item": 1},
        or_filters={
            "item_code": ["like", f"%{search_text}%"],
            "item_name": ["like", f"%{search_text}%"]
        },
        fields=["item_code", "item_name"],
        limit=10
    )

    if not items:
        return []

    price_list = "Public - Alger"
    if customer_code:
        customer_price_list = frappe.db.get_value(
            "Customer",
            {"custom_customer_code": customer_code},
            "default_price_list"
        )
        if customer_price_list:
            price_list = customer_price_list

    item_codes = [item["item_code"] for item in items]

    prices_raw = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", item_codes], "price_list": price_list, "selling": 1},
        fields=["item_code", "price_list_rate"]
    )
    price_map = {p["item_code"]: p["price_list_rate"] for p in prices_raw}

    fallback_map = {}
    if price_list != "Public - Alger":
        fallback_raw = frappe.get_all(
            "Item Price",
            filters={"item_code": ["in", item_codes], "price_list": "Public - Alger", "selling": 1},
            fields=["item_code", "price_list_rate"]
        )
        fallback_map = {p["item_code"]: p["price_list_rate"] for p in fallback_raw}

    for item in items:
        code = item["item_code"]
        rate = price_map.get(code) or fallback_map.get(code)
        item["standard_rate"] = flt(rate) if rate else 0.0

    return items


################################################################################
################  Get Announcements By Customer Code Function ##################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_announcements_by_customer_code(code=None, limit=10, offset=0):
    if not code:
        return {"error": "Missing client code"}

    limit        = int(limit)
    offset       = int(offset)
    current_date = frappe.utils.today()

    customer_name = frappe.db.get_value("Customer", {"custom_customer_code": code}, "name")
    if not customer_name:
        return {"error": "Customer not found"}

    all_announcements = frappe.get_all(
        "Annonce mobile",
        filters=[
            ["docstatus",    "=",  1],
            ["publish_date", "<=", current_date],
            ["expiry_date",  ">=", current_date]
        ],
        fields=["name", "title", "announcement_typ", "priority", "color",
                "description", "banner_image", "publish_date"],
        order_by="publish_date desc",
        ignore_permissions=True
    )

    valid_announcements = []

    for ann in all_announcements:
        doc = frappe.get_doc("Annonce mobile", ann.name, ignore_permissions=True)

        is_banned = any(row.customer == customer_name for row in doc.get("banned", []))
        if is_banned:
            continue

        allowed_list = doc.get("allowed", [])
        is_allowed = not allowed_list or any(row.customer == customer_name for row in allowed_list)

        if is_allowed:
            valid_announcements.append({
                "id":         ann.name,
                "title":      ann.title,
                "subtitle":   ann.description or "",
                "type":       ann.announcement_typ or "Info",
                "priority":   ann.priority or "Medium",
                "color":      ann.color or "#00A89C",
                "postedTime": str(ann.publish_date or ""),
                "image":      ann.banner_image,
            })

    paginated_list = valid_announcements[offset: offset + limit]

    return {
        "customer":      customer_name,
        "total_count":   len(valid_announcements),
        "announcements": paginated_list
    }


################################################################################
######################  Get Items By Customer Code Function ####################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_items_by_customer_code(customer_code):
    try:
        if not customer_code:
            return {"status": "error", "message": "Missing customer_code"}

        price_list = frappe.db.get_value(
            "Customer",
            {"custom_customer_code": customer_code},
            "default_price_list"
        ) or "Public - Alger"

        items = frappe.get_all(
            "Item",
            filters={"disabled": 0, "is_sales_item": 1},
            fields=["item_code", "item_name", "description", "item_group", "stock_uom"]
        )

        if not items:
            return {"status": "success", "price_list": price_list, "items": []}

        item_codes = [item["item_code"] for item in items]

        customer_prices_raw = frappe.get_all(
            "Item Price",
            filters={"item_code": ["in", item_codes], "price_list": price_list, "selling": 1},
            fields=["item_code", "price_list_rate"]
        )
        customer_price_map = {p["item_code"]: p["price_list_rate"] for p in customer_prices_raw}

        fallback_price_map = {}
        if price_list != "Public - Alger":
            fallback_prices_raw = frappe.get_all(
                "Item Price",
                filters={"item_code": ["in", item_codes], "price_list": "Public - Alger", "selling": 1},
                fields=["item_code", "price_list_rate"]
            )
            fallback_price_map = {p["item_code"]: p["price_list_rate"] for p in fallback_prices_raw}

        result = []
        for item in items:
            code = item["item_code"]
            rate = customer_price_map.get(code) or fallback_price_map.get(code) or 0.0
            result.append({
                "item_code":   code,
                "item_name":   item["item_name"],
                "description": item.get("description") or "",
                "item_group":  item.get("item_group") or "",
                "uom":         item.get("stock_uom") or "Nos",
                "rate":        float(rate),
                "currency":    "DZD",
                "price_list":  price_list
            })

        return {"status": "success", "price_list": price_list, "items": result}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Error get_items")
        return {"status": "error", "message": str(e)}


################################################################################
######################  Create Sales Order Function ############################
################################################################################

@frappe.whitelist(allow_guest=True)
def create_sales_order():
    try:
        data = None

        if frappe.request:
            content_type = frappe.request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                raw = frappe.request.data
                if raw:
                    data = json.loads(raw)

        if not data:
            data = frappe.form_dict

        code_envoye = data.get("customer_code")
        items       = data.get("items")

        if not code_envoye:
            return {"status": "error", "message": "Missing customer_code"}
        if not items:
            return {"status": "error", "message": "Missing items"}

        if isinstance(items, str):
            items = json.loads(items)

        customer_id = frappe.db.get_value("Customer", {"custom_customer_code": code_envoye}, "name")
        if not customer_id:
            return {"status": "error", "message": f"Customer '{code_envoye}' not found in ERPNext"}

        customer_data = frappe.db.get_value(
            "Customer", customer_id, "default_price_list", as_dict=True
        )
        price_list = (customer_data.get("default_price_list") if customer_data else None) or "Public - Alger"

        company    = "OPTILENS ALGER"
        default_wh = frappe.db.get_value("Warehouse", {"company": company, "is_group": 0}, "name")

        so = frappe.get_doc({
            "doctype":          "Sales Order",
            "customer":         customer_id,
            "company":          company,
            "transaction_date": frappe.utils.today(),
            "delivery_date":    frappe.utils.add_days(frappe.utils.today(), 2),
            "items":            []
        })

        for it in items:
            item_code = it.get("item_code")
            if not item_code:
                continue

            rate = frappe.db.get_value(
                "Item Price",
                {"item_code": item_code, "price_list": price_list, "selling": 1},
                "price_list_rate"
            ) or 0.0

            uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

            so.append("items", {
                "item_code":     item_code,
                "qty":           float(it.get("qty") or 1),
                "rate":          float(rate),
                "uom":           uom,
                "warehouse":     default_wh or "Magasins - OA",
                "delivery_date": so.delivery_date
            })

        so.insert(ignore_permissions=True)
        so.submit()
        frappe.db.commit()

        return {"status": "success", "order_id": so.name}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Mobile Order Error")
        return {"status": "error", "message": str(e)}


################################################################################
######################  Get Customer Orders Function ###########################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_customer_orders(customer_code):
    if not customer_code:
        return {"status": "error", "message": "Missing customer_code"}

    customer_id = frappe.db.get_value("Customer", {"custom_customer_code": customer_code}, "name")

    if not customer_id:
        return {"status": "error", "message": f"Customer '{customer_code}' not found"}

    orders = frappe.get_all(
        "Sales Order",
        filters={"customer": customer_id},
        fields=["name", "transaction_date", "status", "grand_total"],
        order_by="creation desc"
    )
    return {"status": "success", "orders": orders}


################################################################################
######################  Get Order Details Function #############################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_order_details(order_id=None):
    if not order_id:
        order_id = frappe.form_dict.get('order_id')

    if not order_id:
        return {"status": "error", "message": "Missing order ID"}

    try:
        doc = frappe.get_doc("Sales Order", order_id, ignore_permissions=True)

        items_list = []
        for item in doc.items:
            items_list.append({
                "item_code": item.item_code,
                "qty":       item.qty,
                "rate":      item.rate,
                "amount":    item.amount
            })

        return {
            "status":      "success",
            "name":        doc.name,
            "grand_total": doc.grand_total,
            "items":       items_list
        }
    except Exception as e:
        return {"status": "error", "message": f"Order not found: {str(e)}"}


################################################################################
######################  Create Customer Complaint Function #####################
################################################################################

@frappe.whitelist(allow_guest=True)
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


################################################################################
######################  Change Customer Code Function ##########################
################################################################################

@frappe.whitelist(allow_guest=True)
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


################################################################################
######################  Get Companies Function #################################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_companies(token=None):
    try:
        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        allowed_companies, allowed_warehouses = get_user_permissions(user)

        filters = {}

        # Filter by allowed companies if restrictions exist
        if allowed_companies:
            filters["name"] = ["in", allowed_companies]

        companies = frappe.get_all(
            "Company",
            filters=filters,
            fields=["name", "company_name", "default_currency"],
            order_by="company_name asc",
            ignore_permissions=True,
        )

        return {"companies": companies}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_companies error")
        return {"error": str(e)}


################################################################################
######################  Get Material Requests Function #########################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_material_requests(token=None, limit=20, offset=0, search_text=None, status=None):
    try:
        limit  = int(limit  or 20)
        offset = int(offset or 0)

        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        allowed_companies, allowed_warehouses = get_user_permissions(user)

        filters = {}

        if allowed_companies:
            filters["company"] = ["in", allowed_companies]

        if allowed_warehouses:
            filters["set_warehouse"] = ["in", allowed_warehouses]

        is_search = bool(search_text and str(search_text).strip())
        if is_search:
            filters["name"] = ["like", f"%{str(search_text).strip()}%"]

        if status and status != "All":
            filters["status"] = status

        requests = frappe.get_all(
            "Material Request",
            filters=filters,
            fields=[
                "name", "company", "transaction_date", "status",
                "material_request_type", "schedule_date",
                "set_warehouse", "set_from_warehouse",
                "buying_price_list",
                "docstatus"
            ],
            order_by="transaction_date desc",
            limit=20  if is_search else limit,
            start=0   if is_search else offset,
            ignore_permissions=True
        )

        result = []
        for req in requests:
            items = frappe.get_all(
                "Material Request Item",
                filters={"parent": req["name"]},
                fields=["item_code", "item_name", "qty",
                        "received_qty", "uom", "warehouse", "schedule_date"],
                ignore_permissions=True
            )
            result.append({
                "name":                  req["name"],
                "company":               req["company"]                or "",
                "transaction_date":      str(req["transaction_date"]   or ""),
                "status":                req["status"]                 or "",
                "material_request_type": req["material_request_type"]  or "",
                "schedule_date":         str(req["schedule_date"]      or ""),
                "warehouse":             req["set_warehouse"]          or "",
                "set_from_warehouse":    req["set_from_warehouse"]     or "",
                "price_list":            req["buying_price_list"]      or "",
                "docstatus":             req["docstatus"],
                "items":                 items
            })

        return {"material_requests": result, "is_search": is_search}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_material_requests error")
        return {"error": str(e)}


################################################################################
######################  Get Material Request Detail Function ###################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_material_request_detail(token=None, name=None):
    try:
        if not name:
            return {"success": False, "error": "Missing name"}

        user = get_user_from_sid(token)
        if not user:
            return {"success": False, "error": "Invalid session"}

        if not frappe.db.exists("Material Request", name):
            return {"success": False, "error": "Material Request not found"}

        doc = frappe.get_doc("Material Request", name)

        # Enforce company and warehouse restrictions if they exist
        allowed_companies, allowed_warehouses = get_user_permissions(user)
        if allowed_companies and doc.company and doc.company not in allowed_companies:
            return {"success": False, "error": "Access denied for this Material Request (Company restriction)"}
        if allowed_warehouses and doc.set_warehouse and doc.set_warehouse not in allowed_warehouses:
            return {"success": False, "error": "Access denied for this Material Request (Warehouse restriction)"}

        items = []
        for it in doc.items:
            items.append({
                "item_code":     it.item_code          or "",
                "item_name":     it.item_name          or "",
                "qty":           float(it.qty          or 0),
                "received_qty":  float(it.received_qty or 0),
                "uom":           it.uom                or "",
                "warehouse":     it.warehouse          or "",
                "schedule_date": str(it.schedule_date  or ""),
            })

        return {
            "success": True,
            "material_request": {
                "name":                  doc.name,
                "company":               doc.company               or "",
                "transaction_date":      str(doc.transaction_date  or ""),
                "status":                doc.status                or "",
                "material_request_type": doc.material_request_type or "",
                "schedule_date":         str(doc.schedule_date     or ""),
                "warehouse":             doc.set_warehouse         or "",
                "set_from_warehouse":    doc.set_from_warehouse    or "",
                "price_list":            doc.buying_price_list     or "",
                "docstatus":             doc.docstatus,
            },
            "items": items
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_material_request_detail error")
        return {"success": False, "error": str(e)}


################################################################################
######################  Create Material Request Function #######################
################################################################################

@frappe.whitelist(allow_guest=True)
def create_material_request():
    try:
        if frappe.request.method != "POST":
            return {"success": False, "error": "Method not allowed"}

        data               = json.loads(frappe.request.data)
        token              = data.get("token")
        items              = data.get("items")
        purpose            = data.get("purpose", "Material Transfer")
        
        user = get_user_from_sid(token)
        if not user:
            return {"success": False, "error": "Invalid session"}

        allowed_companies, allowed_warehouses = get_user_permissions(user)

        # Dynamic company assignment according to user permissions
        company = data.get("company")
        if not company:
            if allowed_companies:
                company = allowed_companies[0]
            else:
                company = frappe.db.get_default("company") or "OPTILENS ALGER"

        if allowed_companies and company not in allowed_companies:
            return {"success": False, "error": f"Access denied for company '{company}'"}

        set_warehouse      = data.get("set_warehouse",      "")
        set_from_warehouse = data.get("set_from_warehouse", "")
        price_list         = data.get("price_list",         "")
        required_by        = data.get("required_by") or frappe.utils.add_days(frappe.utils.today(), 7)

        if allowed_warehouses and set_warehouse and set_warehouse not in allowed_warehouses:
            return {"success": False, "error": f"Access denied for warehouse '{set_warehouse}'"}
        if allowed_warehouses and set_from_warehouse and set_from_warehouse not in allowed_warehouses:
            return {"success": False, "error": f"Access denied for warehouse '{set_from_warehouse}'"}

        if not items:
            return {"success": False, "error": "Missing items"}

        if isinstance(items, str):
            items = json.loads(items)

        if purpose == "Material Transfer":
            if not set_from_warehouse:
                return {"success": False, "error": "Source warehouse required for Material Transfer"}
            if not set_warehouse:
                return {"success": False, "error": "Target warehouse required for Material Transfer"}

        elif purpose == "Material Issue":
            if not set_from_warehouse:
                return {"success": False, "error": "Source warehouse required for Material Issue"}
            if not set_warehouse:
                set_warehouse = set_from_warehouse
        else:
            if not set_warehouse:
                set_warehouse = frappe.db.get_value(
                    "Warehouse", {"company": company, "is_group": 0}, "name"
                ) or ""

        doc_fields = {
            "doctype":               "Material Request",
            "material_request_type": purpose,
            "transaction_date":      frappe.utils.today(),
            "schedule_date":         required_by,
            "company":               company,
            "set_warehouse":         set_warehouse,
            "items":                 [],
        }

        if set_from_warehouse and purpose in ["Material Transfer", "Material Issue", "Material Transfer for Manufacture"]:
            doc_fields["set_from_warehouse"] = set_from_warehouse

        if price_list:
            doc_fields["buying_price_list"] = price_list

        doc = frappe.get_doc(doc_fields)

        for it in items:
            item_code = it.get("item_code")
            if not item_code or not frappe.db.exists("Item", item_code):
                continue

            uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"
            doc.append("items", {
                "item_code":     item_code,
                "qty":           float(it.get("qty") or 1),
                "uom":           uom,
                "warehouse":     it.get("warehouse") or set_warehouse,
                "schedule_date": required_by,
            })

        if not doc.items:
            return {"success": False, "error": "No valid items found"}

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return {
            "success":            True,
            "id":                 doc.name,
            "status":             doc.status,
            "company":            company,
            "purpose":            purpose,
            "price_list":         price_list,
            "set_warehouse":      set_warehouse,
            "set_from_warehouse": set_from_warehouse,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_material_request error")
        return {"success": False, "error": str(e)}


################################################################################
######################  Manage Material Request Function #######################
################################################################################

@frappe.whitelist(allow_guest=True)
def manage_material_request(name=None, action="submit"):
    try:
        token = None
        if frappe.request and frappe.request.method == "POST":
            content_type = frappe.request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data   = json.loads(frappe.request.data or "{}")
                name   = name   or data.get("name")
                action = data.get("action", action)
                token  = data.get("token")

        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        if not name:
            return {"error": "Missing name"}

        if not frappe.db.exists("Material Request", name):
            return {"error": f"Material Request '{name}' not found"}

        doc = frappe.get_doc("Material Request", name)

        # Check document-level permissions
        allowed_companies, allowed_warehouses = get_user_permissions(user)
        if allowed_companies and doc.company and doc.company not in allowed_companies:
            return {"error": "Access denied for this Material Request (Company restriction)"}
        if allowed_warehouses and doc.set_warehouse and doc.set_warehouse not in allowed_warehouses:
            return {"error": "Access denied for this Material Request (Warehouse restriction)"}

        if action == "submit":
            if doc.docstatus == 1:
                return {"error": "Already submitted"}
            if doc.docstatus == 2:
                return {"error": "Document is cancelled"}
            doc.submit()
            frappe.db.commit()
            return {"message": "Success", "detail": f"Material Request {name} submitted successfully", "status": doc.status}

        elif action == "cancel":
            if doc.docstatus == 2:
                return {"error": "Already cancelled"}
            if doc.docstatus == 0:
                return {"error": "Cannot cancel a draft — delete it instead"}
            doc.cancel()
            frappe.db.commit()
            return {"message": "Success", "detail": f"Material Request {name} cancelled successfully", "status": "Cancelled"}

        elif action == "delete":
            if doc.docstatus != 0:
                return {"error": "Can only delete Draft documents"}
            frappe.delete_doc("Material Request", name, ignore_permissions=True, force=True)
            frappe.db.commit()
            return {"message": "Success", "detail": f"Material Request {name} deleted successfully"}

        else:
            return {"error": f"Unknown action '{action}'. Use: submit, cancel, delete"}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "manage_material_request error")
        return {"error": str(e)}


################################################################################
######################  Create Stock Entry From MR Function ####################
################################################################################

@frappe.whitelist(allow_guest=True)
def create_stock_entry_from_mr(name=None):
    try:
        token = None
        if frappe.request and frappe.request.method == "POST":
            content_type = frappe.request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data  = json.loads(frappe.request.data or "{}")
                name  = name or data.get("name")
                token = data.get("token")

        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        if not name:
            return {"error": "Missing Material Request name"}

        if not frappe.db.exists("Material Request", name):
            return {"error": f"Material Request '{name}' not found"}

        mr = frappe.get_doc("Material Request", name)

        # Validate permission rules
        allowed_companies, allowed_warehouses = get_user_permissions(user)
        if allowed_companies and mr.company and mr.company not in allowed_companies:
            return {"error": "Access denied for this Material Request"}

        if mr.docstatus != 1:
            return {"error": "Material Request must be submitted first"}
        if mr.material_request_type != "Material Transfer":
            return {"error": "Only Material Transfer type can create a Stock Entry"}
        if mr.status in ["Transferred", "Received", "Stopped"]:
            return {"error": f"Material Request already {mr.status}"}

        from erpnext.stock.doctype.material_request.material_request import make_stock_entry

        se = make_stock_entry(name)
        se.insert(ignore_permissions=True)
        frappe.db.commit()

        items = []
        for it in se.items:
            items.append({
                "item_code":      it.item_code   or "",
                "item_name":      it.item_name   or "",
                "qty":            float(it.qty   or 0),
                "from_warehouse": it.s_warehouse or "",
                "to_warehouse":   it.t_warehouse or "",
                "uom":            it.uom         or "",
            })

        return {
            "success":        True,
            "stock_entry_id": se.name,
            "mr_name":        name,
            "from_warehouse": se.from_warehouse or "",
            "to_warehouse":   se.to_warehouse   or "",
            "items_count":    len(se.items),
            "items":          items,
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_stock_entry_from_mr error")
        return {"error": str(e)}


################################################################################
######################  Get Warehouses Function ################################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_warehouses(token=None, company=None):
    try:
        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        allowed_companies, allowed_warehouses = get_user_permissions(user)

        filters = {"is_group": 0, "disabled": 0}

        if company:
            filters["company"] = company
        elif allowed_companies:
            filters["company"] = ["in", allowed_companies]

        if allowed_warehouses:
            filters["name"] = ["in", allowed_warehouses]

        warehouses = frappe.get_all(
            "Warehouse",
            filters=filters,
            fields=["name", "warehouse_name", "company"],
            order_by="warehouse_name asc",
            ignore_permissions=True,
        )

        return {"warehouses": warehouses}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_warehouses error")
        return {"error": str(e)}
    

################################################################################
######################  Get Companies Function #################################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_companies(token=None):
    try:
        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        allowed_companies, allowed_warehouses = get_user_permissions(user)

        filters = {}

        # If restrictions exist, filter by allowed companies. Otherwise, fetch all.
        if allowed_companies:
            filters["name"] = ["in", allowed_companies]

        companies = frappe.get_all(
            "Company",
            filters=filters,
            fields=["name", "company_name", "default_currency"],
            order_by="company_name asc",
            ignore_permissions=True,
        )

        return {"companies": companies}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_companies error")
        return {"error": str(e)}    


################################################################################
######################  Get Price Lists Function ###############################
################################################################################

@frappe.whitelist(allow_guest=True)
def get_price_lists(token=None):
    try:
        user = get_user_from_sid(token)
        if not user:
            return {"error": "Invalid session"}

        price_lists = frappe.get_all(
            "Price List",
            filters={"enabled": 1},
            fields=["name", "currency"],
            order_by="name asc",
            ignore_permissions=True,
        )

        return {"price_lists": price_lists}

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_price_lists error")
        return {"error": str(e)}