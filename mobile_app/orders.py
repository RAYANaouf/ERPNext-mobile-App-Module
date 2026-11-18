"""Customer sales orders."""

import json

import frappe


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


        price_list = frappe.db.get_value(
            "Customer", customer_id, "default_price_list"
        ) or "Public - Alger"

        company   = "OPTILENS ALGER"
        warehouse = "Magasins - OA"

        so = frappe.get_doc({
            "doctype":             "Sales Order",
            "customer":            customer_id,
            "company":             company,
            "selling_price_list":  price_list,
            "price_list_currency": "DZD",
            "transaction_date":    frappe.utils.today(),
            "delivery_date":       frappe.utils.add_days(frappe.utils.today(), 2),
            "items":               []
        })

        for it in items:
            item_code = it.get("item_code")
            if not item_code:
                continue

            rate = frappe.db.get_value(
                "Item Price",
                {"item_code": item_code, "price_list": price_list, "selling": 1},
                "price_list_rate"
            )
            if not rate and price_list != "Public - Alger":
                rate = frappe.db.get_value(
                    "Item Price",
                    {"item_code": item_code, "price_list": "Public - Alger", "selling": 1},
                    "price_list_rate"
                )
            rate = float(rate or 0.0)

            uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

            so.append("items", {
                "item_code":     item_code,
                "qty":           float(it.get("qty") or 1),
                "rate":          rate,
                "uom":           uom,
                "warehouse":     warehouse,
                "delivery_date": so.delivery_date
            })

        so.insert(ignore_permissions=True)
        so.submit()
        frappe.db.commit()

        return {
            "status":     "success",
            "order_id":   so.name,
            "price_list": price_list
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Mobile Order Error")
        return {"status": "error", "message": str(e)}


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
