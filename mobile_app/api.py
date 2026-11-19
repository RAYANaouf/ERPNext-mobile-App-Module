"""Public Frappe methods used by the mobile app under /api/method/mobile_app.api.*."""

import frappe

from mobile_app import auth, billing, catalog, communications, customer_sessions, customers, material_requests, orders, stock
from mobile_app.activity_reports import (
    create_activity_report,
    get_activity_report,
    get_activity_report_options,
    get_activity_reports,
    update_activity_report,
)
from mobile_app.auth import authenticate_employee, get_user_from_sid
from mobile_app.employee_job_profile import get_my_job_profile
from mobile_app.employee_tasks import (
    create_task,
    create_todo,
    get_assignable_users,
    get_my_tasks,
    get_task,
    get_task_detail,
    get_task_options,
    get_task_photo,
    get_task_voice,
    get_tasks,
    update_my_task_status,
    update_task,
)
from mobile_app.issues import (
    add_issue_photo,
    create_issue,
    create_task_from_issue,
    get_issue,
    get_issue_options,
    get_issue_photo,
    get_issue_users,
    get_issue_voice,
    get_issues,
    reply_to_issue,
    update_issue_status,
    update_issue_voice,
)
from mobile_app.material_requests import STOCK_ENTRY_MR_TYPES


@frappe.whitelist(allow_guest=True)
def hello_world(name=None):
    return {
        "message": f"Hello, {name or 'Guest'}!"
    }


# Register the HTTP methods here so the domain modules only expose Python functions.
_mobile_method = frappe.whitelist(allow_guest=True)

login = _mobile_method(auth.login)
get_my_user_name = frappe.whitelist(allow_guest=True, methods=["POST"])(auth.get_my_user_name)

get_customer_profile = frappe.whitelist(allow_guest=True, methods=["GET", "POST"])(customers.get_customer_profile)
get_client_by_code = get_customer_profile
login_customer = frappe.whitelist(allow_guest=True, methods=["POST"])(customers.login_customer)
logout_customer = frappe.whitelist(allow_guest=True, methods=["POST"])(customer_sessions.logout_customer)
change_customer_code = frappe.whitelist(allow_guest=True, methods=["POST"])(customers.change_customer_code)
create_customer_complaint = frappe.whitelist(allow_guest=True, methods=["POST"])(customers.create_customer_complaint)

get_customer_invoices = frappe.whitelist(allow_guest=True, methods=["GET", "POST"])(billing.get_customer_invoices)
get_invoices_by_customer_code = get_customer_invoices
get_single_invoice_details = frappe.whitelist(allow_guest=True, methods=["GET", "POST"])(billing.get_single_invoice_details)
get_customer_payments = frappe.whitelist(allow_guest=True, methods=["GET", "POST"])(billing.get_customer_payments)
get_payments_by_customer_code = get_customer_payments

create_sales_order = frappe.whitelist(allow_guest=True, methods=["POST"])(orders.create_sales_order)
get_customer_orders = frappe.whitelist(allow_guest=True, methods=["GET"])(orders.get_customer_orders)
get_order_details = frappe.whitelist(allow_guest=True, methods=["GET"])(orders.get_order_details)

search_items = _mobile_method(catalog.search_items)
get_items_by_customer_code = _mobile_method(catalog.get_items_by_customer_code)
get_price_lists = _mobile_method(catalog.get_price_lists)

get_notification_by_customer_code = _mobile_method(communications.get_notification_by_customer_code)
get_announcements_by_customer_code = _mobile_method(communications.get_announcements_by_customer_code)

get_companies = _mobile_method(stock.get_companies)
get_warehouses = _mobile_method(stock.get_warehouses)
get_last_stock_entries = _mobile_method(stock.get_last_stock_entries)
get_stock_entry_details_by_name = _mobile_method(stock.get_stock_entry_details_by_name)
manage_stock_entry = _mobile_method(stock.manage_stock_entry)
get_stock_summary = _mobile_method(stock.get_stock_summary)

get_material_requests = _mobile_method(material_requests.get_material_requests)
get_material_request_detail = _mobile_method(material_requests.get_material_request_detail)
create_material_request = _mobile_method(material_requests.create_material_request)
manage_material_request = _mobile_method(material_requests.manage_material_request)
create_stock_entry_from_mr = _mobile_method(material_requests.create_stock_entry_from_mr)
