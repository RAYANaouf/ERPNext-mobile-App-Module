"""Material requests and their conversion to stock entries."""

import json

import frappe

from mobile_app.auth import authenticate_employee


STOCK_ENTRY_MR_TYPES = (
    "Material Transfer",
    "Material Issue",
)


def get_material_requests(token=None, limit=20, offset=0, search_text=None, status=None):
    try:
        limit  = int(limit  or 20)
        offset = int(offset or 0)

        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        filters = {}

        is_search = bool(search_text and str(search_text).strip())
        if is_search:
            filters["name"] = ["like", f"%{str(search_text).strip()}%"]

        if status and status != "All":
            filters["status"] = status

        requests = frappe.get_list(
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
            limit_page_length=20 if is_search else limit,
            limit_start=0 if is_search else offset,
        )

        result = []
        for req in requests:
            items = frappe.get_all(
                "Material Request Item",
                filters={"parent": req["name"]},
                fields=["item_code", "item_name", "qty",
                        "received_qty", "uom", "warehouse", "schedule_date"],
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

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_material_requests error")
        return {"error": str(e)}


def get_material_request_detail(token=None, name=None):
    try:
        if not name:
            return {"success": False, "error": "Missing name"}

        if not authenticate_employee(token):
            return {"success": False, "error": "Invalid session"}

        if not frappe.db.exists("Material Request", name):
            return {"success": False, "error": "Material Request not found"}

        doc = frappe.get_doc("Material Request", name)

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

    except frappe.PermissionError:
        return {"success": False, "error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_material_request_detail error")
        return {"success": False, "error": str(e)}


def create_material_request():
    try:
        if frappe.request.method != "POST":
            return {"success": False, "error": "Method not allowed"}

        data               = json.loads(frappe.request.data)
        token              = data.get("token")
        items              = data.get("items")
        purpose            = data.get("purpose") or "Material Transfer"

        if not authenticate_employee(token):
            return {"success": False, "error": "Invalid session"}

        company = data.get("company")
        if not company:
            companies = frappe.get_list("Company", fields=["name"], limit_page_length=1)
            company = (companies[0].get("name") if companies else None) or frappe.db.get_default("company") or "OPTILENS ALGER"

        set_warehouse      = data.get("set_warehouse",      "")
        set_from_warehouse = data.get("set_from_warehouse", "")
        price_list         = data.get("price_list",         "")
        required_by        = data.get("required_by") or frappe.utils.add_days(frappe.utils.today(), 7)

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
            source_wh = set_from_warehouse or set_warehouse
            if not source_wh:
                return {"success": False, "error": "Source warehouse required for Material Issue"}
            # ERPNext uses set_warehouse as the issue source
            set_from_warehouse = source_wh
            set_warehouse = source_wh

        else:
            if not set_warehouse:
                warehouses = frappe.get_list(
                    "Warehouse",
                    filters={"company": company, "is_group": 0},
                    fields=["name"],
                    limit_page_length=1,
                )
                set_warehouse = warehouses[0].get("name") if warehouses else ""

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
            item_row = {
                "item_code":     item_code,
                "qty":           float(it.get("qty") or 1),
                "uom":           uom,
                "warehouse":     it.get("warehouse") or set_warehouse,
                "schedule_date": required_by,
            }
            if purpose == "Material Transfer":
                item_row["from_warehouse"] = it.get("from_warehouse") or set_from_warehouse
            doc.append("items", item_row)

        if not doc.items:
            return {"success": False, "error": "No valid items found"}

        doc.insert()
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

    except frappe.PermissionError:
        return {"success": False, "error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_material_request error")
        return {"success": False, "error": str(e)}


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

        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        if not name:
            return {"error": "Missing name"}

        if not frappe.db.exists("Material Request", name):
            return {"error": f"Material Request '{name}' not found"}

        doc = frappe.get_doc("Material Request", name)

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
            frappe.delete_doc("Material Request", name)
            frappe.db.commit()
            return {"message": "Success", "detail": f"Material Request {name} deleted successfully"}

        else:
            return {"error": f"Unknown action '{action}'. Use: submit, cancel, delete"}

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "manage_material_request error")
        return {"error": str(e)}


def create_stock_entry_from_mr(name=None):
    try:
        token = None
        if frappe.request and frappe.request.method == "POST":
            content_type = frappe.request.headers.get("Content-Type", "")
            if "application/json" in content_type:
                data  = json.loads(frappe.request.data or "{}")
                name  = name or data.get("name")
                token = data.get("token")

        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        if not name:
            return {"error": "Missing Material Request name"}

        if not frappe.db.exists("Material Request", name):
            return {"error": f"Material Request '{name}' not found"}

        mr = frappe.get_doc("Material Request", name)

        if mr.docstatus != 1:
            return {"error": "Material Request must be submitted first"}
        if mr.material_request_type not in STOCK_ENTRY_MR_TYPES:
            return {
                "error": (
                    f"Material Request type '{mr.material_request_type}' "
                    "cannot create a Stock Entry"
                )
            }
        if mr.status in ["Transferred", "Received", "Issued", "Stopped"]:
            return {"error": f"Material Request already {mr.status}"}

        from erpnext.stock.doctype.material_request.material_request import make_stock_entry

        se = make_stock_entry(name)

        if not se.items:
            return {"error": "No remaining quantity to create a Stock Entry"}

        if mr.material_request_type == "Material Issue":
            source_wh = mr.set_from_warehouse or mr.set_warehouse
            se.from_warehouse = source_wh
            se.to_warehouse = None
            for row in se.items:
                row.s_warehouse = source_wh
                row.t_warehouse = None

        if hasattr(se, "material_request_ref"):
            se.material_request_ref = name

        se.insert()
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
            "success":          True,
            "stock_entry_id":   se.name,
            "mr_name":          name,
            "purpose":          se.purpose or "",
            "stock_entry_type": se.stock_entry_type or "",
            "from_warehouse":   se.from_warehouse or "",
            "to_warehouse":     se.to_warehouse   or "",
            "items_count":      len(se.items),
            "items":            items,
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "create_stock_entry_from_mr error")
        return {"error": str(e)}
