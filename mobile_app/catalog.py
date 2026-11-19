"""Item search and selling prices for the mobile catalog."""

import re

import frappe
from frappe.utils import flt

from mobile_app.auth import authenticate_employee
from mobile_app.customer_sessions import current_customer

PUBLIC_PRICE_LIST = "Public - Alger"


def _matching_items(search_text, list_items):
    if not search_text:
        return []

    search_text = str(search_text).strip()

    if len(search_text) > 50:
        return {"status": "error", "message": "Search text too long (max 50 characters)"}

    if not re.match(r'^[\w\s\-\.+]+$', search_text, re.UNICODE):
        return {"status": "error", "message": "Unauthorized characters in search text"}

    return list_items(
        "Item",
        filters={"disabled": 0, "is_sales_item": 1},
        or_filters={
            "item_code": ["like", f"%{search_text}%"],
            "item_name": ["like", f"%{search_text}%"]
        },
        fields=["item_code", "item_name"],
        limit=10
    )


def _customer_price_list(customer):
    return frappe.db.get_value("Customer", customer, "default_price_list") or PUBLIC_PRICE_LIST


def _selling_rates(items, price_list):
    if not items:
        return {}
    item_codes = [item["item_code"] for item in items]

    prices = frappe.get_all(
        "Item Price",
        filters={"item_code": ["in", item_codes], "price_list": ["in", [price_list, PUBLIC_PRICE_LIST]],
                 "selling": 1},
        fields=["item_code", "price_list", "price_list_rate"],
    )
    rates = {(row["price_list"], row["item_code"]): row["price_list_rate"] for row in prices}
    return {
        code: flt(rates.get((price_list, code)) or rates.get((PUBLIC_PRICE_LIST, code)))
        for code in item_codes
    }


def search_customer_items(search_text=None):
    customer = current_customer()
    if not customer:
        return {"error": "Invalid session"}
    items = _matching_items(search_text, frappe.get_all)
    if not isinstance(items, list) or not items:
        return items
    rates = _selling_rates(items, _customer_price_list(customer))
    for item in items:
        item["standard_rate"] = rates[item["item_code"]]
    return items


def search_employee_items(search_text=None, token=None):
    user = authenticate_employee(token)
    if not user or user == "Guest" or not frappe.get_cached_value("User", user, "enabled"):
        return {"error": "Invalid session"}
    try:
        return _matching_items(search_text, frappe.get_list)
    except frappe.PermissionError:
        return {"error": "Access denied"}


def get_customer_items():
    customer = current_customer()
    if not customer:
        return {"error": "Invalid session"}
    try:
        price_list = _customer_price_list(customer)
        items = frappe.get_all(
            "Item",
            filters={"disabled": 0, "is_sales_item": 1},
            fields=["item_code", "item_name", "description", "item_group", "stock_uom"]
        )

        rates = _selling_rates(items, price_list)
        result = []
        for item in items:
            code = item["item_code"]
            result.append({
                "item_code":   code,
                "item_name":   item["item_name"],
                "description": item.get("description") or "",
                "item_group":  item.get("item_group") or "",
                "uom":         item.get("stock_uom") or "Nos",
                "rate":        rates[code],
                "currency":    "DZD",
                "price_list":  price_list
            })

        return {"status": "success", "price_list": price_list, "items": result}

    except Exception:
        frappe.log_error(title="Mobile catalog error", message=frappe.get_traceback())
        return {"status": "error", "message": "Unable to load items"}


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
