"""Short-lived, site-scoped credentials for the mobile customer API."""

import hashlib
import hmac
import json
import re
import secrets

import frappe


SESSION_SECONDS = 24 * 60 * 60
SESSION_HEADER = "X-Mobile-Customer-Session"


def _session_key(token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    return frappe.cache.make_key(f"mobile:customer-session:{digest}")


def _generation_key(customer):
    return frappe.cache.make_key(f"mobile:customer-generation:{customer}")


def _code_tag(generation, code):
    return hmac.new(generation, code.encode(), hashlib.sha256).hexdigest()


def issue(customer, code):
    cache = frappe.cache
    key = _generation_key(customer)
    cache.set(key, secrets.token_bytes(32), nx=True)
    generation = cache.get(key)
    if not generation:
        raise RuntimeError("Customer sessions unavailable")
    token = secrets.token_urlsafe(32)
    cache.setex(_session_key(token), SESSION_SECONDS, json.dumps([customer, _code_tag(generation, code)]))
    return token


def _request_token():
    token = frappe.get_request_header(SESSION_HEADER, "")
    return token if re.fullmatch(r"[A-Za-z0-9_-]{43}", token or "") else None


def current_customer():
    frappe.flags.private_mobile_customer_response = True
    token = _request_token()
    stored = frappe.cache.get(_session_key(token)) if token else None
    if not stored:
        return None
    customer, issued_tag = json.loads(stored)
    code = frappe.db.get_value("Customer", {"name": customer, "disabled": 0}, "custom_customer_code")
    generation = frappe.cache.get(_generation_key(customer))
    if code and generation and hmac.compare_digest(issued_tag, _code_tag(generation, code)):
        return customer
    return None


def logout_customer():
    frappe.flags.private_mobile_customer_response = True
    token = _request_token()
    if token:
        frappe.cache.delete(_session_key(token))
    return {"success": True}


def invalidate_all(customer):
    frappe.cache.delete(_generation_key(customer))


def protect_response(response):
    if response is not None and frappe.flags.private_mobile_customer_response:
        response.headers["Cache-Control"] = "private, no-store"
