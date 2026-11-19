"""Customer notifications and targeted announcements."""

import frappe

from mobile_app.customer_sessions import current_customer


def get_customer_notifications():
    customer_name = current_customer()
    if not customer_name:
        return {"error": "Invalid session"}

    all_notification = frappe.get_all(
        "Mobile Notification",
        filters={"customer": customer_name, "docstatus": 1},
        fields=["name", "msg", "title"],
    )

    return {"notification": all_notification}


def get_customer_announcements(limit=10, offset=0):
    customer_name = current_customer()
    if not customer_name:
        return {"error": "Invalid session"}

    limit        = int(limit)
    offset       = int(offset)
    current_date = frappe.utils.today()

    all_announcements = frappe.get_all(
        "Annonce mobile",
        filters=[
            ["docstatus",    "=",  1],
            ["publish_date", "<=", current_date],
            ["expiry_date",  ">=", current_date]
        ],
        fields=["name", "title", "announcement_typ", "priority", "color",
                "description", "banner_image", "publish_date"],
        order_by="publish_date desc, name desc",
    )

    names = [ann.name for ann in all_announcements]
    audience = frappe.get_all(
        "Mobile Announcement Customer",
        filters={"parenttype": "Annonce mobile", "parent": ["in", names],
                 "parentfield": ["in", ["allowed", "banned"]]},
        fields=["parent", "parentfield", "customer"],
    ) if names else []
    restricted = {row.parent for row in audience if row.parentfield == "allowed"}
    allowed = {row.parent for row in audience if row.parentfield == "allowed" and row.customer == customer_name}
    banned = {row.parent for row in audience if row.parentfield == "banned" and row.customer == customer_name}
    hidden = banned | (restricted - allowed)
    visible = [ann for ann in all_announcements if ann.name not in hidden]

    return {
        "customer": customer_name,
        "total_count": len(visible),
        "announcements": [
            {
                "id":         ann.name,
                "title":      ann.title,
                "subtitle":   ann.description or "",
                "type":       ann.announcement_typ or "Info",
                "priority":   ann.priority or "Medium",
                "color":      ann.color or "#00A89C",
                "postedTime": str(ann.publish_date or ""),
                "image":      ann.banner_image,
            }
            for ann in visible[offset:offset + limit]
        ],
    }
