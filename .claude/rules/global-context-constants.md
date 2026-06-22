# Global template context constants

`build_static_context_data()` in `app/shared/context/global_context.py` injects a set of
model-layer constant namespaces into every Jinja2 template via `render_template_context()`.
When writing new templates or route handlers, **use these names directly** rather than passing
the same values as per-view keyword arguments.

## Available constant namespaces

| Template name                   | Python source                | Typical usage                                                           |
|---------------------------------|------------------------------|-------------------------------------------------------------------------|
| `MarkingEventWorkflowStates`    | `app/models/markingevent.py` | `event.workflow_state == MarkingEventWorkflowStates.CLOSED`             |
| `SubmitterReportWorkflowStates` | `app/models/markingevent.py` | `sr.workflow_state == SubmitterReportWorkflowStates.FEEDBACK_AVAILABLE` |
| `SubmissionRoleTypesMixin`      | `app/models/model_mixins.py` | `mr.role.role == SubmissionRoleTypesMixin.ROLE_MARKER`                  |

## Other static values always in context

These are also provided by `build_static_context_data()` and do not need per-view injection:

- `website_revision`, `website_copyright_dates` — site metadata
- `branding_label`, `branding_login_landing_string`, `branding_public_landing_string` — tenant branding
- `email_is_live`, `backup_is_live` — feature flags

Per-request role flags (`is_faculty`, `is_student`, `is_convenor`, `is_root`, `is_admin`, etc.)
and dynamic data (`current_user`, `current_time`, `all_pclasses`, etc.) are added by
`_build_global_context()` on every request — see `app/shared/context/global_context.py` and
`app/shared/context/global_context.py:_build_global_context` for the full list.

## Policy

If a new route needs a constant that is not yet in the pool, consider adding the containing class
or mixin to `_static_ctx` rather than injecting the individual constants per-view. Suitable
candidates are pure namespace containers (enums, int-constant mixins) with no ORM or request
state. ORM model classes that carry query methods should generally **not** be added — pass query
results as explicit per-view kwargs instead.
