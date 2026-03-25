---
name: emailworkflow blueprint
description: Details about the emailworkflow blueprint added to the MPS-Project for inspecting and managing EmailWorkflow instances
type: project
---

A new `emailworkflow` blueprint was added at `/emailworkflow/` to provide UI for managing EmailWorkflow instances.

**Why:** Admins and email managers need to inspect, pause/unpause, and preview email workflows and their items without
direct database access.

**How to apply:** When working with email workflow management features, refer to this blueprint.

## Files created

- `app/emailworkflow/__init__.py` — blueprint definition
- `app/emailworkflow/forms.py` — EditWorkflowForm (send_time, max_attachment_size)
- `app/emailworkflow/views.py` — all views and AJAX endpoints
- `app/ajax/site/email_workflows.py` — DataTables data formatters
- `app/templates/emailworkflow/email_workflows.html` — workflow list (Task 2)
- `app/templates/emailworkflow/workflow_items.html` — items for a workflow (Task 3)
- `app/templates/emailworkflow/preview_item.html` — email preview (Task 4)
- `app/templates/emailworkflow/payload_view.html` — raw payload inspection
- `app/templates/emailworkflow/edit_workflow.html` — edit send_time and max_attachment_size

## Files modified

- `app/models/emails.py` — added `EmailTemplate.render_content_(template, subject_kwargs, body_kwargs) -> (str, str)`
  static method
- `app/tasks/email_workflow.py` — exposed `decode_email_payload = _decode_email_payload` as public alias
- `app/__init__.py` — registered emailworkflow blueprint at `/emailworkflow`
- `app/templates/base.html` — added "Email workflows..." menu item in Site management dropdown (visible to
  root/admin/email roles, above "Email log...")
- `app/ajax/site/__init__.py` — added imports for email_workflow_data and email_workflow_item_data

## Access control

Routes protected with `@roles_accepted("root", "admin", "email")`.
Menu item visible when `is_root or is_admin or is_emailer`.
