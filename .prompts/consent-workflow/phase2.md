# Consent workflow — Phase 2: Token route and shared consent template

## Objective

Implement the unauthenticated `/consent/<token>` route and the shared Jinja2
template that renders consent preferences. This template will be reused in
Phase 3 (authenticated student dashboard tab) without modification.

This phase has **no dependency** on the email dispatch infrastructure (Phase 4)
— the route works as soon as a `User.consent_token` value exists in the database.

---

## Reconnaissance

Read the following before writing any code:

1. `app/student/views.py` (the `student` blueprint)
    - Note the blueprint registration: `from . import student` at the bottom
      of the file, confirming the blueprint variable name.
    - Note the import block at the top — you will need to add `ConsentAuditEvent`
      to the models imported.
    - Note how `render_template_context` is used (imported from
      `app.shared.context.global_context`) — use this for all template rendering.

2. `app/templates/student/dashboard.html`
    - Note the `{% extends "base_app.html" %}` inheritance.
    - Note the pill navigation block (`{% block pillblock %}`).
    - Note that the "Manage running projects" and "Make selections" tabs are
      rendered as `<a>` elements with `pane` query parameters.

3. `app/templates/base_app.html` (or the base template referenced above)
    - Confirm the block names available: `title`, `pillblock`, `bodyblock`,
      `scripts`.

4. `app/static/css/common.css`
    - Search for `--cd-text-` tokens to confirm which semantic font-size
      tokens are available for use in the new template.

5. `app/shared/utils.py`
    - Note the `redirect_url()` helper — used throughout views for back-navigation.

---

## Changes

### 1. New route file: `app/student/consent.py`

Create a new file `app/student/consent.py` within the `student` blueprint.
This file contains all consent-related routes.

```python
"""
Consent management routes for the student blueprint.

Two entry points:
  - /student/consent          — authenticated, @login_required, session-based
  - /consent/<token>          — unauthenticated, token-based (no @login_required)

Both render the same template: student/consent/manage.html
"""

import uuid
from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_security import current_user, login_required

from ...database import db
from ...models import ConsentAuditEvent, SubmissionRecord, SubmittingStudent, User
from ...shared.context.global_context import render_template_context
from ...shared.workflow_logging import log_db_commit
from .. import student


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_eligible_records_for_user(user: User):
    """
    Return all SubmissionRecords that are consent-eligible for this User,
    ordered by most recent first (via period → config → year).
    Records are eligible when:
      - period.closed is True
      - report_grade is not None
    """
    from sqlalchemy import desc
    from ...models import SubmittingStudent, SubmissionPeriodRecord, ProjectClassConfig

    records = (
        db.session.query(SubmissionRecord)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
        .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
        .filter(
            SubmittingStudent.student_id == user.id,
            SubmissionPeriodRecord.closed.is_(True),
            SubmissionRecord.report_grade.isnot(None),
        )
        .order_by(desc(ProjectClassConfig.year))
        .all()
    )
    return records


def _apply_consent_update(record: SubmissionRecord, actor_id, ip_address: str):
    """
    Read consent toggle values from the current POST request and apply them
    to the given SubmissionRecord, writing ConsentAuditEvent rows as needed.
    Returns True if any changes were made.
    """
    now = datetime.utcnow()
    changed = False

    exemplar_new = request.form.get("exemplar_consent") == "1"
    openday_new = request.form.get("openday_consent") == "1"

    # --- Exemplar consent ---
    exemplar_currently_active = record.exemplar_consent_active

    if exemplar_new and not exemplar_currently_active:
        # Grant (or re-grant after withdrawal)
        if record.exemplar_consent_granted_at is None:
            # First ever grant — set the permanent granted_at timestamp
            record.exemplar_consent_granted_at = now
        record.exemplar_consent_withdrawn = False
        record.exemplar_consent_withdrawn_at = None
        db.session.add(ConsentAuditEvent(
            record_id=record.id,
            actor_id=actor_id,
            event_type=ConsentAuditEvent.EXEMPLAR_GRANTED,
            timestamp=now,
            ip_address=ip_address,
        ))
        changed = True

    elif not exemplar_new and exemplar_currently_active:
        # Withdraw
        record.exemplar_consent_withdrawn = True
        record.exemplar_consent_withdrawn_at = now
        db.session.add(ConsentAuditEvent(
            record_id=record.id,
            actor_id=actor_id,
            event_type=ConsentAuditEvent.EXEMPLAR_WITHDRAWN,
            timestamp=now,
            ip_address=ip_address,
        ))
        changed = True

    # --- Open day consent ---
    openday_currently_active = record.openday_consent_active

    if openday_new and not openday_currently_active:
        if record.openday_consent_granted_at is None:
            record.openday_consent_granted_at = now
        record.openday_consent_withdrawn = False
        record.openday_consent_withdrawn_at = None
        db.session.add(ConsentAuditEvent(
            record_id=record.id,
            actor_id=actor_id,
            event_type=ConsentAuditEvent.OPENDAY_GRANTED,
            timestamp=now,
            ip_address=ip_address,
        ))
        changed = True

    elif not openday_new and openday_currently_active:
        record.openday_consent_withdrawn = True
        record.openday_consent_withdrawn_at = now
        db.session.add(ConsentAuditEvent(
            record_id=record.id,
            actor_id=actor_id,
            event_type=ConsentAuditEvent.OPENDAY_WITHDRAWN,
            timestamp=now,
            ip_address=ip_address,
        ))
        changed = True

    return changed


# ---------------------------------------------------------------------------
# Token-authenticated route (unauthenticated session)
# ---------------------------------------------------------------------------

@student.route("/consent/<string:token>", methods=["GET", "POST"])
def consent_by_token(token):
    """
    Render and process the consent management page for a student identified
    by their User.consent_token. No Flask-Security session required.

    GET  — render consent form for all eligible SubmissionRecords
    POST — update consent for a single SubmissionRecord identified by
           the 'record_id' hidden field; redirect back to GET
    """
    user: User = User.query.filter_by(consent_token=token).first()
    if user is None:
        abort(404)

    ip = request.remote_addr

    if request.method == "POST":
        record_id = request.form.get("record_id", type=int)
        if record_id is None:
            abort(400)

        record: SubmissionRecord = SubmissionRecord.query.get(record_id)
        if record is None:
            abort(404)

        # Security: verify this record belongs to this token's user
        if record.owner is None or record.owner.student_id != user.id:
            abort(403)

        if not record.consent_eligible:
            abort(403)

        changed = _apply_consent_update(record, actor_id=None, ip_address=ip)

        if changed:
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                # Render page with error message rather than crashing
                records = _get_eligible_records_for_user(user)
                return render_template(
                    "student/consent/manage.html",
                    user=user,
                    records=records,
                    token_mode=True,
                    error="An error occurred saving your preferences. Please try again.",
                )

        return redirect(url_for("student.consent_by_token", token=token))

    records = _get_eligible_records_for_user(user)
    return render_template(
        "student/consent/manage.html",
        user=user,
        records=records,
        token_mode=True,
        error=None,
    )
```

Register this module in `app/student/__init__.py` (or wherever the student
blueprint imports its submodules) by adding:

```python
from . import consent  # noqa: F401
```

alongside the existing `from . import views` import.

### 2. Authenticated route in `app/student/views.py`

Add the following route to `app/student/views.py`, importing
`ConsentAuditEvent` and `_get_eligible_records_for_user` and
`_apply_consent_update` from the new `consent.py` module:

```python
@student.route("/use_of_work", methods=["GET", "POST"])
@login_required
@roles_accepted("student")
def use_of_work():
    """
    Authenticated consent management tab on the student dashboard.
    Renders the same template as consent_by_token but with session auth.
    """
    from .consent import _get_eligible_records_for_user, _apply_consent_update

    ip = request.remote_addr

    if request.method == "POST":
        record_id = request.form.get("record_id", type=int)
        if record_id is None:
            abort(400)

        record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

        # Security: verify this record belongs to the current user
        if record.owner is None or record.owner.student_id != current_user.id:
            abort(403)

        if not record.consent_eligible:
            flash("This record is not currently eligible for consent management.", "warning")
            return redirect(url_for("student.use_of_work"))

        changed = _apply_consent_update(record, actor_id=current_user.id, ip_address=ip)

        if changed:
            try:
                log_db_commit(
                    f"Updated consent preferences for submission record #{record.id}",
                    user=current_user,
                )
            except Exception:
                db.session.rollback()
                flash("An error occurred saving your preferences.", "danger")
                return redirect(url_for("student.use_of_work"))

        return redirect(url_for("student.use_of_work"))

    records = _get_eligible_records_for_user(current_user)
    return render_template_context(
        "student/consent/manage.html",
        user=current_user,
        records=records,
        token_mode=False,
        error=None,
    )
```

### 3. New template: `app/templates/student/consent/manage.html`

Create the directory `app/templates/student/consent/` and the file
`manage.html`. This template has two rendering modes controlled by
`token_mode`:

- `token_mode=True` — no `{% extends %}`, stripped layout, no navbar.
- `token_mode=False` — extends `base_app.html`, renders inside the student
  dashboard with the pill navigation.

```jinja
{% if not token_mode %}
{% extends "base_app.html" %}

{% block title %}Use of your work{% endblock %}

{% block pillblock %}
    <ul class="nav nav-pills dashboard-nav">
        <li class="nav-item">
            <a class="nav-link" href="{{ url_for('student.dashboard', pane='submit') }}">
                Manage running projects
            </a>
        </li>
        <li class="nav-item">
            <a class="nav-link" href="{{ url_for('student.dashboard', pane='select') }}">
                Make selections
            </a>
        </li>
        <li class="nav-item">
            <a class="nav-link active" href="{{ url_for('student.use_of_work') }}">
                <i class="fas fa-shield-alt fa-fw"></i> Use of your work
            </a>
        </li>
    </ul>
{% endblock %}

{% block bodyblock %}
{% endif %}

{# ------------------------------------------------------------------ #}
{# Shared content — rendered in both modes                             #}
{# ------------------------------------------------------------------ #}

{% if token_mode %}
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Manage report permissions — MPS projects</title>
    {# Minimal Bootstrap only — no app chrome #}
    <link rel="stylesheet" href="{{ url_for('static', filename='css/bootstrap.min.css') }}">
    <link rel="stylesheet" href="{{ url_for('static', filename='css/common.css') }}">
</head>
<body style="background: var(--bs-tertiary-bg)">
<div class="container py-4" style="max-width: 680px">
    <div class="mb-3">
        <span class="fw-500" style="font-size: var(--cd-text-section)">MPS projects management</span>
        <span class="ms-3 text-body-secondary" style="font-size: var(--cd-text-small)">Limited access &middot; private link</span>
    </div>
    <p style="font-size: var(--cd-text-body); color: var(--bs-body-color)">
        Manage permissions for your submitted reports
    </p>
    <p class="text-body-secondary" style="font-size: var(--cd-text-small)">
        You are accessing this page via a private link. You can review and update your
        permissions below. No other features are available via this link.
    </p>
{% endif %}

{% if error %}
    <div class="alert alert-danger">{{ error }}</div>
{% endif %}

{% if records %}
    {% for record in records %}
        {% set config = record.period.config %}
        {% set pclass = config.project_class %}
        <div class="card mt-3 mb-3">
            <div class="card-header d-flex justify-content-between align-items-baseline"
                 style="background: var(--bs-tertiary-bg); border-bottom: 1px solid var(--bs-border-color)">
                <div>
                    <span class="fw-semibold" style="font-size: var(--cd-text-body)">
                        {{ pclass.name }}
                    </span>
                    {% if not token_mode %}
                        <span class="text-body-secondary ms-2" style="font-size: var(--cd-text-small)">
                            {{ config.submit_year_a }}&ndash;{{ config.submit_year_b }}
                            &middot;
                            {% if record.supervisor_roles.first() %}
                                {{ record.supervisor_roles.first().user.name }}
                            {% endif %}
                            {% if record.project %}
                                &middot; {{ record.project.name }}
                            {% endif %}
                        </span>
                    {% else %}
                        <span class="text-body-secondary ms-2" style="font-size: var(--cd-text-small)">
                            {{ config.submit_year_a }}&ndash;{{ config.submit_year_b }}
                        </span>
                    {% endif %}
                </div>
                {% if record.report_grade is not none %}
                    <span class="badge"
                          style="background: var(--bs-success-bg-subtle);
                                 color: var(--bs-success-text-emphasis);
                                 border: 1px solid var(--bs-success-border-subtle);
                                 font-size: var(--cd-text-micro)">
                        {{ "%.0f"|format(record.report_grade) }}%
                    </span>
                {% endif %}
            </div>
            <div class="card-body">
                {% if not token_mode %}
                    <div class="alert alert-info py-2 px-3 mb-3" style="font-size: var(--cd-text-small)">
                        Please let us know whether we can use your project report.
                        You can optionally make your report available as an exemplar or for open days.
                    </div>
                {% endif %}

                {# Determine POST target URL #}
                {% if token_mode %}
                    {% set post_url = url_for('student.consent_by_token', token=request.view_args.get('token', '')) %}
                {% else %}
                    {% set post_url = url_for('student.use_of_work') %}
                {% endif %}

                <form method="POST" action="{{ post_url }}">
                    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                    <input type="hidden" name="record_id" value="{{ record.id }}">

                    {# Exemplar consent row #}
                    <div class="p-3 rounded mb-2
                        {% if record.exemplar_consent_active %}border border-success{% else %}border{% endif %}"
                         style="{% if record.exemplar_consent_active %}background: var(--bs-success-bg-subtle){% else %}background: var(--bs-tertiary-bg){% endif %}">
                        <div class="d-flex align-items-start gap-3">
                            <div class="form-check form-switch mt-1 mb-0">
                                <input class="form-check-input" type="checkbox"
                                       role="switch"
                                       id="exemplar-{{ record.id }}"
                                       name="exemplar_consent"
                                       value="1"
                                       {% if record.exemplar_consent_active %}checked{% endif %}
                                       onchange="this.form.submit()">
                            </div>
                            <div>
                                <label class="fw-semibold mb-1 d-block"
                                       for="exemplar-{{ record.id }}"
                                       style="font-size: var(--cd-text-body)">
                                    Use as a teaching exemplar
                                </label>
                                <p class="mb-1 text-body-secondary" style="font-size: var(--cd-text-small)">
                                    Your report may be shared
                                    with future cohorts as an exemplar. Your name won't appaer.
                                </p>
                                <span style="font-size: var(--cd-text-micro); font-weight: 500;
                                             color: {% if record.exemplar_consent_active %}var(--bs-success-text-emphasis){% else %}var(--bs-secondary-color){% endif %}">
                                    {% if record.exemplar_consent_active %}
                                        <i class="fas fa-check fa-fw"></i>
                                        Permission given
                                        {% if record.exemplar_consent_granted_at %}
                                            &middot; {{ record.exemplar_consent_granted_at.strftime("%d %b %Y") }}
                                        {% endif %}
                                    {% else %}
                                        No permission given
                                    {% endif %}
                                </span>
                            </div>
                        </div>
                    </div>

                    {# Open day consent row #}
                    <div class="p-3 rounded mb-3
                        {% if record.openday_consent_active %}border border-success{% else %}border{% endif %}"
                         style="{% if record.openday_consent_active %}background: var(--bs-success-bg-subtle){% else %}background: var(--bs-tertiary-bg){% endif %}">
                        <div class="d-flex align-items-start gap-3">
                            <div class="form-check form-switch mt-1 mb-0">
                                <input class="form-check-input" type="checkbox"
                                       role="switch"
                                       id="openday-{{ record.id }}"
                                       name="openday_consent"
                                       value="1"
                                       {% if record.openday_consent_active %}checked{% endif %}
                                       onchange="this.form.submit()">
                            </div>
                            <div>
                                <label class="fw-semibold mb-1 d-block"
                                       for="openday-{{ record.id }}"
                                       style="font-size: var(--cd-text-body)">
                                    Use at open days and promotional events
                                </label>
                                <p class="mb-1 text-body-secondary" style="font-size: var(--cd-text-small)">
                                    Your project may be used on Applicant Visit Days.
                                </p>
                                <span style="font-size: var(--cd-text-micro); font-weight: 500;
                                             color: {% if record.openday_consent_active %}var(--bs-success-text-emphasis){% else %}var(--bs-secondary-color){% endif %}">
                                    {% if record.openday_consent_active %}
                                        <i class="fas fa-check fa-fw"></i>
                                        Permission given
                                        {% if record.openday_consent_granted_at %}
                                            &middot; {{ record.openday_consent_granted_at.strftime("%d %b %Y") }}
                                        {% endif %}
                                    {% else %}
                                        No permission given
                                    {% endif %}
                                </span>
                            </div>
                        </div>
                    </div>

                </form>

                <div class="p-2 rounded border" style="background: var(--bs-secondary-bg); font-size: var(--cd-text-micro); color: var(--bs-secondary-color)">
                    <i class="fas fa-lock fa-fw"></i>
                    <strong>Keep your permanent consent link safe.</strong>
                    When your account is anonymized, we will no longer be able to identify
                    your report by your name or email address. Your consent link is your
                    permanent way to manage your preferences.
                </div>
            </div>
        </div>
    {% endfor %}

{% else %}
    <div class="alert alert-info mt-3">
        <i class="fas fa-info-circle fa-fw"></i>
        You do not currently have any graded project reports for which consent
        can be managed.
    </div>
{% endif %}

{% if token_mode %}
    {% if not records %}
        <p class="text-body-secondary mt-3" style="font-size: var(--cd-text-small)">
            <i class="fas fa-shield-alt fa-fw"></i>
            This link is personal to you. Do not share it. For queries about how
            your data is used, contact the School office.
        </p>
    {% endif %}
</div>
</body>
</html>
{% else %}
{% endblock %}
{% endif %}
```

**Important implementation notes for this template:**

- The toggles use `onchange="this.form.submit()"` for immediate submission —
  no separate Save button is required. Each toggle is its own `<form>` scoped
  to one `record_id`.
- CSRF protection must be active for both routes. The token route does not
  have a session, so you must ensure Flask-WTF CSRF is either disabled for
  this endpoint (using `@csrf.exempt`) or that the token is rendered correctly.
  Check how other CSRF-exempt routes are handled in the codebase (search for
  `csrf.exempt` or `WTF_CSRF_CHECK_DEFAULT`). The simplest approach is to add
  `@csrf.exempt` to `consent_by_token` and rely on the token-in-URL as the
  anti-CSRF mechanism instead.
- The `supervisor_roles` dynamic relationship used in the template should be
  verified against the actual backref name on `SubmissionRole` — search
  `SubmissionRecord` for the correct relationship name for supervisor roles.

### 4. Update student dashboard navigation

In `app/templates/student/dashboard.html`, add a "Use of your work" pill
to the pill navigation block, after the existing "Make selections" link:

```jinja
<li class="nav-item">
    <a class="nav-link {% if pane=='consent' %}active{% endif %}"
       href="{{ url_for('student.use_of_work') }}">
        <i class="fas fa-shield-alt fa-fw"></i> Use of your work
    </a>
</li>
```

The pill should only be visible when the student has at least one eligible
record. Wrap it in a conditional:

```jinja
{% if has_consent_eligible_records %}
    <li class="nav-item">...
{% endif %}
```

Pass `has_consent_eligible_records` from the student dashboard route by
querying whether any `SubmissionRecord` for this user is `consent_eligible`.
Add this to the existing `dashboard` view function in `app/student/views.py`.

---

## Verification

```bash
# 1. Route is registered
flask routes | grep consent

# 2. Token route returns 404 for unknown token
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/consent/not-a-real-token
# Expected: 404

# 3. Authenticated route redirects unauthenticated users to login
curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/student/use_of_work
# Expected: 302 (redirect to login)

# 4. Template renders without error for a known user with eligible records
# (manual test with a real consent_token from the database)
```