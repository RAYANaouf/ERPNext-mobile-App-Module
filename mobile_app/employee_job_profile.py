################################################################################
######################  Employee Job Profile (Fiche de poste) ##################
################################################################################
# Reads the Job description linked on Employee.custom_fiche_de_poste.
# Managers assign the fiche in Desk; mobile shows only the logged-in employee's fiche.
#
# Example:
# curl -G "http://192.168.100.20:8000/api/method/mobile_app.api.get_my_job_profile" \
#   --data-urlencode "token={{sid}}"

import frappe
from frappe.utils import strip_html


JOB_DESCRIPTION_DOCTYPE = "Job description"
EMPLOYEE_FICHE_FIELD = "custom_fiche_de_poste"


def _articles(rows):
    out = []
    for row in rows or []:
        out.append({
            "idx": row.idx or len(out) + 1,
            "description": row.description or "",
        })
    return out


def _serialize_job_description(doc):
    mission_html = doc.general_mission or ""
    return {
        "name":                      doc.name or "",
        "job_title":                 doc.job_title or "",
        "hierarchical_reporting":    doc.hierarchical_reporting or "",
        "hierarchical_relation":     doc.hierarchical_relation_alt or "",
        "functional_reporting":      doc.functional_reporting or "",
        "general_mission":           mission_html,
        "general_mission_text":      strip_html(mission_html) if mission_html else "",
        "authorities":               _articles(doc.get("authorities")),
        "tasks":                     _articles(doc.get("tasks_description")),
        "workflow_state":            getattr(doc, "workflow_state", None) or "",
        "docstatus":                 int(doc.docstatus or 0),
    }


def _get_employee_for_user(user):
    fields = [
        "name", "employee_name", "user_id", "designation",
        "department", "company", "status",
    ]
    if frappe.get_meta("Employee").has_field(EMPLOYEE_FICHE_FIELD):
        fields.append(EMPLOYEE_FICHE_FIELD)

    emp = frappe.db.get_value(
        "Employee",
        {"user_id": user, "status": "Active"},
        fields,
        as_dict=True,
    )
    if emp:
        return emp
    return frappe.db.get_value(
        "Employee",
        {"user_id": user},
        fields,
        as_dict=True,
    )


@frappe.whitelist(allow_guest=True)
def get_my_job_profile(token=None):
    """
    Return the Job description assigned to the authenticated employee.
    Auth: token = SID (same pattern as stock / tasks APIs).
    Read-only. The employee never sees another person's fiche.
    """
    from mobile_app.api import authenticate_employee

    try:
        if not authenticate_employee(token):
            return {"error": "Invalid session"}

        user = frappe.session.user

        if not frappe.get_meta("Employee").has_field(EMPLOYEE_FICHE_FIELD):
            return {"error": "Custom field custom_fiche_de_poste is missing on Employee"}

        emp = _get_employee_for_user(user)
        if not emp:
            return {"error": "Employee not found for this user"}

        employee_payload = {
            "name":          emp.get("name") or "",
            "employee_name": emp.get("employee_name") or "",
            "user_id":       emp.get("user_id") or user,
            "designation":   emp.get("designation") or "",
            "department":    emp.get("department") or "",
            "company":       emp.get("company") or "",
            "status":        emp.get("status") or "",
        }

        fiche_name = (emp.get(EMPLOYEE_FICHE_FIELD) or "").strip()
        if not fiche_name:
            return {
                "success": True,
                "employee": employee_payload,
                "job_profile": None,
                "message": "Aucune fiche de poste assignée",
            }

        if not frappe.db.exists(JOB_DESCRIPTION_DOCTYPE, fiche_name):
            return {"error": "Job description not found"}

        # Employee roles typically cannot read ISO Job description.
        # Scoped: only the fiche linked on THIS employee's record.
        doc = frappe.get_doc(JOB_DESCRIPTION_DOCTYPE, fiche_name)

        if int(doc.docstatus or 0) == 2:
            return {
                "success": True,
                "employee": employee_payload,
                "job_profile": None,
                "message": "La fiche de poste est rejetée",
            }

        return {
            "success": True,
            "employee": employee_payload,
            "job_profile": _serialize_job_description(doc),
        }

    except frappe.PermissionError:
        return {"error": "Access denied"}
    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "get_my_job_profile error")
        return {"error": str(e)}
