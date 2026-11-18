"""Stock entries, warehouse balances and warehouse selection."""

import json

import frappe
from frappe.utils import flt

from mobile_app.auth import authenticate_employee


def get_companies(token=None):
    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        companies = frappe.get_list(
            "Company",
            fields=["name", "company_name", "default_currency"],
            order_by="company_name asc",
            limit_page_length=1000,
        )

        return {"companies": companies}

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_companies error")
        return {"error": str(e)}


def get_warehouses(token=None, company=None):
    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        filters = {"is_group": 0, "disabled": 0}

        if company:
            filters["company"] = company

        warehouses = frappe.get_list(
            "Warehouse",
            filters=filters,
            fields=["name", "warehouse_name", "company"],
            order_by="warehouse_name asc",
            limit_page_length=1000,
        )

        return {"warehouses": warehouses}

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_warehouses error")
        return {"error": str(e)}


def get_last_stock_entries(token: str, limit: int = 20, offset: int = 0, search_text=None, status=None):
    limit  = int(limit  or 20)
    offset = int(offset or 0)

    if not authenticate_employee(token):
        return {"error": "Invalid session"}

    allowed_docstatus = [0, 1]
    filters = {"docstatus": ["in", allowed_docstatus]}

    is_search = bool(search_text and str(search_text).strip())
    if is_search:
        filters["name"] = ["like", f"%{str(search_text).strip()}%"]

    if status and status != "All":
        filters["workflow_state"] = status

    try:
        rows = frappe.get_list(
            "Stock Entry",
            fields=["name", "posting_date", "from_warehouse",
                    "to_warehouse", "workflow_state", "docstatus"],
            filters=filters,
            order_by="posting_date desc",
            limit_page_length=20 if is_search else limit,
            limit_start=0 if is_search else offset,
        )
    except frappe.PermissionError:
        return {"error": "Access denied"}

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


def get_stock_entry_details_by_name(token: str, name: str):
    if not name:
        return {"error": "Missing Stock Entry name"}

    if not authenticate_employee(token):
        return {"error": "Invalid session"}

    if not frappe.db.exists("Stock Entry", name):
        return {"error": "Stock Entry not found"}

    try:
        doc = frappe.get_doc("Stock Entry", name)
    except frappe.PermissionError:
        return {"error": "Access denied"}

    if doc.docstatus == 2:
        return {"error": "Stock Entry is cancelled"}

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

        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        if not name or not items:
            return {"error": "Missing parameters: name or items"}

        if not frappe.db.exists("Stock Entry", name):
            return {"error": f"Stock Entry '{name}' not found"}

        try:
            doc = frappe.get_doc("Stock Entry", name)
        except frappe.PermissionError:
            return {"error": "Access denied"}

        if doc.docstatus != 0:
            return {"error": "Stock Entry already submitted or cancelled"}

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

        doc.save()
        frappe.db.commit()

        if action == "approve":
            doc.submit()
            frappe.db.commit()
            return {"message": "Success", "detail": f"Stock Entry {name} approved successfully"}

        return {"message": "Success", "detail": f"Stock Entry {name} saved successfully"}

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "manage_stock_entry error")
        return {"error": str(e)}


# Example:
# curl -G "http://192.168.100.20:8000/api/method/mobile_app.api.get_stock_summary" \
#   --data-urlencode "token={{sid}}" \
#   --data-urlencode "warehouse=" \
#   --data-urlencode "company=OPTILENS ALGER" \
#   --data-urlencode "search_text=" \
#   --data-urlencode "qty_filter=positive" \
#   --data-urlencode "include_low_stock_only=0" \
#   --data-urlencode "limit=20" \
#   --data-urlencode "offset=0"
# qty_filter: positive | all | negative
# (aliases: only_in_stock=1 → positive, only_negative=1 → negative)
def get_stock_summary(
    token=None,
    warehouse=None,
    search_text=None,
    company=None,
    limit=20,
    offset=0,
    qty_filter=None,
    only_in_stock=1,
    only_negative=0,
    include_low_stock_only=0,
):
    """
    Stock overview for the employee app: quantities from Bin + Item,
    low-stock flags from Item Reorder. No prices / monetary values.
    Qty sign filter is applied server-side (SQL) before summary + pagination.
    Auth: token = SID (same pattern as get_last_stock_entries / get_warehouses).
    """
    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        limit = int(limit or 20)
        offset = int(offset or 0)
        only_in_stock = int(only_in_stock if only_in_stock is not None else 1)
        only_negative = int(only_negative or 0)
        include_low_stock_only = int(include_low_stock_only or 0)

        warehouse = (warehouse or "").strip()
        company = (company or "").strip()
        search_text = (search_text or "").strip()
        is_search = bool(search_text)

        # Resolve qty sign filter (100% server-side)
        resolved_qty_filter = (qty_filter or "").strip().lower()
        if resolved_qty_filter not in ("positive", "all", "negative"):
            if only_negative:
                resolved_qty_filter = "negative"
            elif only_in_stock:
                resolved_qty_filter = "positive"
            else:
                resolved_qty_filter = "all"

        # Warehouses the current user is allowed to see (Role + User Permission)
        wh_filters = {"is_group": 0, "disabled": 0}
        if company:
            wh_filters["company"] = company

        try:
            allowed_wh_rows = frappe.get_list(
                "Warehouse",
                filters=wh_filters,
                fields=["name"],
                limit_page_length=5000,
            )
        except frappe.PermissionError:
            return {"error": "Access denied"}

        allowed_warehouses = [r.get("name") for r in allowed_wh_rows if r.get("name")]

        if warehouse:
            if warehouse not in allowed_warehouses:
                return {"error": "Access denied"}
            target_warehouses = [warehouse]
        else:
            target_warehouses = allowed_warehouses

        empty_response = {
            "success": True,
            "warehouse": warehouse,
            "company": company,
            "summary": {
                "total_items": 0,
                "total_qty": 0,
                "low_stock_count": 0,
            },
            "items": [],
            "is_search": is_search,
            "limit": limit,
            "offset": offset,
            "has_more": False,
        }

        if not target_warehouses:
            return empty_response

        conditions = ["b.warehouse IN %(warehouses)s"]
        values = {"warehouses": tuple(target_warehouses)}

        if resolved_qty_filter == "positive":
            conditions.append("b.actual_qty > 0")
        elif resolved_qty_filter == "negative":
            conditions.append("b.actual_qty < 0")
        # qty_filter=all → no sign filter on qty

        if is_search:
            conditions.append("(b.item_code LIKE %(search)s OR i.item_name LIKE %(search)s)")
            values["search"] = f"%{search_text}%"

        where_sql = " AND ".join(conditions)

        # All matching bins (no N+1): Bin + Item in one query
        bins = frappe.db.sql(
            f"""
            SELECT
                b.item_code AS item_code,
                COALESCE(i.item_name, '') AS item_name,
                b.warehouse AS warehouse,
                COALESCE(b.actual_qty, 0) AS qty,
                COALESCE(i.stock_uom, 'Nos') AS uom
            FROM `tabBin` b
            INNER JOIN `tabItem` i ON i.name = b.item_code
            WHERE {where_sql}
              AND IFNULL(i.disabled, 0) = 0
            ORDER BY i.item_name ASC, b.warehouse ASC
            """,
            values,
            as_dict=True,
        )

        item_codes = list({row.get("item_code") for row in bins if row.get("item_code")})

        # Reorder levels in one query (warehouse-specific preferred)
        reorder_by_wh = {}
        reorder_any = {}
        if item_codes:
            reorders = frappe.get_all(
                "Item Reorder",
                filters={"parent": ["in", item_codes]},
                fields=["parent", "warehouse", "warehouse_reorder_level"],
            )
            for r in reorders:
                parent = r.get("parent")
                level = flt(r.get("warehouse_reorder_level") or 0)
                wh = (r.get("warehouse") or "").strip()
                if not parent:
                    continue
                if wh:
                    reorder_by_wh[(parent, wh)] = level
                else:
                    reorder_any[parent] = level

        items_all = []
        for row in bins:
            item_code = row.get("item_code") or ""
            wh = row.get("warehouse") or ""
            qty = flt(row.get("qty") or 0)
            reorder_level = flt(
                reorder_by_wh.get((item_code, wh), reorder_any.get(item_code, 0))
            )
            is_low_stock = bool(qty <= reorder_level) if reorder_level > 0 else False

            if include_low_stock_only and not is_low_stock:
                continue

            items_all.append({
                "item_code": item_code,
                "item_name": row.get("item_name") or "",
                "warehouse": wh,
                "qty": qty,
                "uom": row.get("uom") or "Nos",
                "is_low_stock": is_low_stock,
                "reorder_level": reorder_level,
            })

        total_items = len(items_all)
        total_qty = sum(flt(i["qty"]) for i in items_all)
        low_stock_count = sum(1 for i in items_all if i["is_low_stock"])

        page = items_all[offset: offset + limit]
        has_more = (offset + limit) < total_items

        return {
            "success": True,
            "warehouse": warehouse,
            "company": company,
            "summary": {
                "total_items": total_items,
                "total_qty": total_qty,
                "low_stock_count": low_stock_count,
            },
            "items": page,
            "is_search": is_search,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_stock_summary error")
        return {"error": str(e)}
