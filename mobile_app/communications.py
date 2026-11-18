"""Customer notifications and targeted announcements."""

import frappe


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
