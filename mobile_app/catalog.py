"""Item search and selling prices for the mobile catalog."""

import re

import frappe
from frappe.utils import flt

from mobile_app.auth import authenticate_employee


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


def get_price_lists(token=None):
    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        price_lists = frappe.get_list(
            "Price List",
            filters={"enabled": 1},
            fields=["name", "currency"],
            order_by="name asc",
            limit_page_length=1000,
        )

        return {"price_lists": price_lists}

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_price_lists error")
        return {"error": str(e)}
