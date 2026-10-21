# Employee Task APIs

The mobile task module now uses ERPNext **Task** documents. Existing standalone
ToDos and the legacy ToDo endpoints are preserved. No schema, role, permission or
Workflow configuration changes are required.

All URLs use /api/method/mobile_app.api.<method>. GET sends token (the employee
SID) in query parameters; POST sends token in its JSON body. Frappe wraps returned
objects in message. Invalid session and Access denied retain their existing format.

## Endpoints

- GET get_tasks: scope=mine|accessible, status=Active|All|Open|Working|Pending Review|Completed|Cancelled|Overdue|Template,
  date=today|YYYY-MM-DD|all, include_overdue=0|1, allocated_to (User name),
  company, project, search_text, limit (1–100, default 20), offset.
- GET get_task: token, name (Task ID).
- GET get_task_options: token, kind=all|users|projects|companies, search_text,
  company (optional project filter), limit.
- POST create_task: token, subject, description, company, project,
  exp_start_date, exp_end_date, priority, progress, assignees (list of User names).
- POST update_task: token, name, modified (version returned by GET), and any of
  subject, description, company, project, exp_start_date, exp_end_date, priority,
  progress, status, assignees.

Optional dates, company and project may be cleared with an empty string.
Omit description on update to preserve existing rich text. Omit assignees to
leave assignments unchanged. An empty assignees array removes active assignments.
Task creation starts in Open. Metadata contains native Task statuses/priorities;
Urgent stays on Task while native assignment ToDos use High.

Successful creation/update returns {success: true, task: {...}}. Task data includes:
name, subject, description, status, priority, progress, dates, company, project,
department, owner, modified, is_overdue, assignees, previous_assignees, can_write,
allowed_statuses. Each assignee contains name (User email) and full_name.

List responses contain success, user, date, scope, status, can_create, summary,
tasks, limit, offset, has_more and is_search. Summary contains total_items,
open_count, working_count, pending_review_count, completed_count, cancelled_count,
and overdue_count. Summary is calculated on all matching authorized records before
pagination. Search matches name, subject or description. Default ordering is
modified descending, then name.

## Permissions and assignment history

Read/create/write checks use **Task**, not ToDo. Native Frappe assignment helpers
create, cancel and close linked ToDos and perform the usual sharing behavior.
Task document access is checked explicitly for details and updates.

A task has one status/progress for all its assignees. Pending Review is an ordinary
status while no Task Workflow is active: write permission also permits completion.
No custom approval role or transition graph is imposed.

Completed closes active assignments through the native Task controller.
The personal view uses active assignments plus closed assignment history for
Completed Tasks. Reopening follows native ERP behavior: assignments are not
silently reopened. Reassign the reopened Task when needed. Cancelled assignments
are excluded from personal assignment history.

POST mutations use a database savepoint. Validation or permission errors roll back
the entire change, including partially created assignments. No explicit commits
are performed by these endpoints; Frappe handles successful POST transactions.

## Compatibility and rollout

Deploy the updated Python source before distributing the updated Flutter app.
No bench migrate is required for this feature. Reload Python workers using the
usual deployment procedure if hot reload is unavailable.

Legacy URLs remain unchanged:
get_my_tasks, get_task_detail, create_todo, update_my_task_status,
get_assignable_users. Old apps continue using ToDo. New apps use the endpoints
above; existing ToDos are not automatically converted to Task.

## Validation

Backend integration tests: mobile_app.tests.test_employee_tasks. Run against a
configured test site, or an initialized Frappe unittest context. Tests roll back
their writes and mock assignment notifications. They cover multi-assignment,
Urgent priority, native completion, history, read-only sharing, denied operations,
paging totals, stale versions, atomic rollback, legacy ToDo reads and JSON dispatch.

Flutter:
    flutter analyze --no-pub
    flutter test --no-pub
    flutter build apk --debug --no-pub

Manual acceptance on a device:
1. Create in ERP, assign several users, refresh the app.
2. Create/edit in the app and check the Task in ERP.
3. Compare My tasks/Accessible tasks, statuses and totals.
4. Complete/reopen and inspect native assignment history.
5. Verify users without read/create/write cannot perform forbidden operations.

