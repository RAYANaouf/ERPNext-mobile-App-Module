"""Customer invoices and payments."""

import frappe

from mobile_app.customer_sessions import current_customer


def get_customer_invoices(limit=20, offset=0, search_text=None, status=None):
    customer_name = current_customer()
    if not customer_name:
        return {"error": "Invalid session"}

    limit  = int(limit)  if limit  else 20
    offset = int(offset) if offset else 0

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
        "is_search":      is_search,
        "sales_invoices": sales_invoices,
        "pos_invoices":   pos_invoices
    }


def get_single_invoice_details(invoice_name=None):
    customer_name = current_customer()
    if not customer_name:
        return {"error": "Invalid session"}
    if not isinstance(invoice_name, str) or not invoice_name.strip():
        return {"error": "Missing invoice name"}

    try:
        owner_filters = {"name": invoice_name, "customer": customer_name}
        for invoice_type, filters in (
            ("Sales Invoice", owner_filters),
            ("POS Invoice", {**owner_filters, "docstatus": 1}),
        ):
            try:
                doc = frappe.get_doc(invoice_type, filters)
                break
            except frappe.DoesNotExistError:
                frappe.clear_last_message()
        else:
            return {"error": "Invoice not found"}

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

    except Exception:
        frappe.log_error(frappe.get_traceback(), "Invoice Detail Error")
        return {"error": "Unable to load invoice"}


def get_customer_payments(limit=20, offset=0, search_text=None):
    customer_name = current_customer()
    if not customer_name:
        return {"error": "Invalid session"}

    limit  = int(limit)  if limit  else 20
    offset = int(offset) if offset else 0

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
        order_by="posting_date desc, name desc",
        limit=20  if is_search else limit,
        start=0   if is_search else offset
    )

    if not payments:
        return {"payments": [], "is_search": is_search}

    pe_names = [p["name"] for p in payments]

    refs = frappe.get_all(
        "Payment Entry Reference",
        filters={"parenttype": "Payment Entry", "parentfield": "references",
                 "parent": ["in", pe_names], "reference_doctype": "Sales Invoice"},
        fields=["parent", "reference_name", "allocated_amount",
                "total_amount", "outstanding_amount"],
        order_by="parent desc"
    )

    invoice_names = list({r["reference_name"] for r in refs})
    invoice_map = {}
    if invoice_names:
        invoices = frappe.get_all(
            "Sales Invoice",
            filters={"name": ["in", invoice_names], "customer": customer_name},
            fields=["name", "posting_date", "status", "grand_total", "outstanding_amount"],
        )
        invoice_map = {inv["name"]: inv for inv in invoices}

    refs_by_payment = {}
    for r in refs:
        inv = invoice_map.get(r["reference_name"])
        if inv is None:
            continue
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
