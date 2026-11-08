# Activity Report mobile API

This adapter reads and saves the existing `ISO 9001 / Activity Report` document.
It does not introduce a DocType, field, role or workflow. The site must already
have the ISO 9001 Activity Report and its child tables installed.

All methods are exported from `mobile_app.api` and implemented in
`mobile_app.activity_reports`. `token` is the employee SID resolved by the
existing authentication helper. Disabled users and Guest are rejected.

## Endpoints

- GET `get_activity_reports`: token, report_type (optional Weekly Report or Monthly Report),
  from_date, to_date, search_text (title), limit (1..100, default 20), offset.
  Returns reports, total_items, has_more and can_create. Sorting: date, modified,
  name descending. Counts and pagination use native permission-filtered queries.
- GET `get_activity_report`: token, name. Returns report, can_read, can_write.
- GET `get_activity_report_options`: token, kind (metadata, employees, processes),
  search_text, limit. Returns native type/action-status choices, current_employee,
  can_create, and searched items when requested. Searches use native Link search
  permissions; read-only users cannot enumerate employees/processes through this API.
- POST `create_activity_report`: JSON object with token and report.
- POST `update_activity_report`: JSON object with token, name, modified and report.
  The exact modified value from the detail response is required to prevent lost updates.

GET requests may contain a JSON content-type header without a request body.
Malformed or non-object JSON bodies are rejected. Errors use the existing
`{error: ...}` convention inside the Frappe message envelope.

## Editable report payload

Scalar fields: title, doc_type, date, process_link.

- done_list / issue_list: rows with description, optional user (User ID), and,
  for existing rows, name. Responses also include the server-resolved user_name.
  Omitting user on an existing row preserves its selection; an empty user clears it.
- attendance_list: employee, present (0/1), and optional existing row name.
- task_list: description, optional task_link, responsible_employee, deadline,
  status (Open / In Progress / Completed / Cancelled), optional existing row name.

The adapter ignores ownership/permission/doctype fields supplied by clients,
checks row ownership and link access, and resolves employee labels on the server.
Omitted tables are preserved on update. The Flutter form round-trips existing
row IDs and retains fields hidden for the other report type.

## Permissions and effects

List, detail, creation and update enforce the native roles, User Permissions and
ISO 9001 hooks. Weekly reports require attendance marked present; a managerial
role does not grant an exemption. Monthly access follows ISO 9001 policy.

Task assignment is performed once by ActivityReport.on_update. Changing report
tracking status does not change the global Task status, dates or progress. Free
text actions do not create Tasks. Unreadable linked Tasks do not expose their
subjects and cannot be opened from the report detail.

Writes roll back their database changes and transaction callbacks on errors;
failed assignments do not leave reports, ToDos, shares or queued notifications.
When a save removes the author's read access, it returns success with
can_read=false, can_write=false, report=null; the app returns to the list.

## Validation and rollout

Backend tests run against optilens.localhost in transactions rolled back at the
end, with native assignment notifications mocked. They cover presence, roles,
monthly access, pagination, child ownership, version conflicts, assignments,
rollback and HTTP-style GET/POST dispatch. Flutter tests cover HTTP payloads,
models, controllers, read-only screens, network errors, unsaved edits, keyboard
layout and the Arabic calendar. No real user SID is read for automated tests.

Deploy the backend API before the Flutter APK. The new mobile routes are
/activity-reports, /activity-report-detail and /activity-report-form.
The UI is available under My space. Existing ERP reports are not migrated.
