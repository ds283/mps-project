# Consent workflow — Phase 4: Supervisor approval email and faculty My Students page

## Objective

Two related pieces:

**4a** — When a student first grants exemplar consent (i.e.
`exemplar_consent_granted_at` transitions from `None` to a value), send a
one-time email to the responsible supervisor asking them to approve or decline.
This is triggered from the consent update logic added in Phase 2.

**4b** — Implement the "My students" faculty dashboard tab: a single page
collecting all `SubmissionRecord`s where the current user holds a
`ROLE_SUPERVISOR` or `ROLE_RESPONSIBLE_SUPERVISOR` role, with search, filtering,
report thumbnails, language metrics, feedback, and inline consent approval
controls.

---

## Reconnaissance

Read the following before writing any code:

1. `app/student/consent.py` (created in Phase 2)
    - Locate `_apply_consent_update`. This is where the supervisor email
      trigger must be added: after committing an exemplar grant where
      `exemplar_consent_granted_at` was previously `None`.

2. `app/models/submissions.py`
    - Find `SubmissionRoleTypesMixin` and note `ROLE_SUPERVISOR` and
      `ROLE_RESPONSIBLE_SUPERVISOR` integer constants.
    - Find the `SubmissionRole` model and its `user` relationship.
    - Find `SubmissionRecord.supervisor_roles` (or equivalent) — the
      relationship or property that returns supervisor `SubmissionRole` objects.
      Confirm the correct attribute name by searching for `ROLE_SUPERVISOR` usage.

3. `app/models/emails.py`
    - Note `EmailTemplateTypesMixin.CONSENT_SUPERVISOR_APPROVAL_REQUEST = 72`
      (added in Phase 1).

4. `app/faculty/views.py`
    - Find the `my_projects` dropdown menu rendering. Search for "Students" to
      locate the existing stub menu item (currently unimplemented).
    - Note the blueprint name (`faculty`) and the `@roles_accepted` pattern used.
    - Find `view_feedback` route as a reference for how `SubmissionRole`-gated
      access is implemented.

5. `app/templates/faculty/dashboard/dashboard.html`
    - Note the pill navigation block and the pattern used for existing tabs
      (Administration, Moderation, Approvals, My enrolments).
    - Note how `pane` query parameter is used to switch between tabs.

6. `app/templates/convenor/dashboard/submitters_v2.html`
    - Study the card-per-student layout, metric capsule pattern, and status
      strip chips as reference for the faculty card layout.

7. `app/convenor-ui-patterns.md` and `app/template-colours.md`
    - Re-read the metric capsule styling rules and colour token policy before
      writing any template HTML.

8. `documents` blueprint
    - Confirm the thumbnail route URL pattern:
      `url_for('documents.serve_thumbnail', asset_type='submitted', asset_id=<id>, size='small')`
    - Note `size='small'` produces 200×200px images.
    - The thumbnail is only available when `record.report is not None` and
      `record.report.small_thumbnail is not None`.

---

## Changes — Part 4a: Supervisor approval email trigger

### Modify `app/student/consent.py` — `_apply_consent_update`

In `_apply_consent_update`, after the block that sets
`record.exemplar_consent_granted_at = now` (the first-ever grant), add:

```python
        # First-ever exemplar consent grant: trigger one-time supervisor
# approval email if not already requested.
if record.exemplar_supervisor_approved is None:
    _request_supervisor_approval(record)
```

Add the following helper function to `consent.py` (above
`_apply_consent_update`):

```python
def _request_supervisor_approval(record: SubmissionRecord):
    """
    Send a one-time approval request email to the responsible supervisor(s)
    for this SubmissionRecord.

    Guard: only called when exemplar_supervisor_approved IS None — i.e. the
    supervisor has never been contacted. Subsequent student consent changes
    do NOT trigger further emails.
    """
    from ..models import EmailTemplate, EmailWorkflow, EmailWorkflowItem
    from ..models.emails import EmailTemplateTypesMixin, encode_email_payload
    from flask import current_app

    pclass = record.period.config.project_class
    config = record.period.config

    tmpl = EmailTemplate.find_template_(
        EmailTemplateTypesMixin.CONSENT_SUPERVISOR_APPROVAL_REQUEST,
        pclass_id=pclass.id,
    )
    if tmpl is None:
        current_app.logger.warning(
            f"No CONSENT_SUPERVISOR_APPROVAL_REQUEST template for pclass #{pclass.id}; "
            f"supervisor approval email not sent for record #{record.id}"
        )
        return

    # Collect responsible supervisors
    from ..models.submissions import SubmissionRoleTypesMixin
    supervisor_roles = record.roles.filter(
        SubmissionRole.role.in_([
            SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
            SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
        ])
    ).all()

    if not supervisor_roles:
        current_app.logger.warning(
            f"No supervisor roles found for record #{record.id}; "
            f"supervisor approval email not sent"
        )
        return

    workflow = EmailWorkflow.build_(
        name=f"Exemplar approval request: record #{record.id}",
        template=tmpl,
        pclasses=[pclass],
    )
    db.session.add(workflow)
    db.session.flush()

    for role in supervisor_roles:
        supervisor_user = role.user
        if supervisor_user is None or not supervisor_user.email:
            continue

        approval_url = url_for(
            "faculty.my_students",
            _external=True,
        )

        item = EmailWorkflowItem.build_(
            subject_payload=encode_email_payload({
                "pclass_name": pclass.name,
                "year_a": config.submit_year_a,
                "year_b": config.submit_year_b,
            }),
            body_payload=encode_email_payload({
                "record": record,
                "pclass": pclass,
                "config": config,
                "approval_url": approval_url,
            }),
            recipient_list=[supervisor_user.email],
        )
        workflow.items.append(item)
```

Note: the supervisor approval email links to the `faculty.my_students` page
(implemented in 4b below) rather than a per-record URL, since the supervisor
uses authenticated session login. The page will show the pending approval
prominently at the top.

---

## Changes — Part 4b: Faculty "My students" page

### 1. New route: `faculty.my_students`

Add the following route to `app/faculty/views.py`. This implements the
existing "Students..." stub menu item:

```python
@faculty.route("/my_students", methods=["GET"])
@roles_accepted("faculty", "admin", "root")
def my_students():
    """
    Aggregated view of all SubmissionRecords where the current faculty member
    holds ROLE_SUPERVISOR or ROLE_RESPONSIBLE_SUPERVISOR.
    Supports search (name/project title), project class filter, and year filter.
    """
    from sqlalchemy import desc, or_
    from ..models import (
        LiveProject, ProjectClass, ProjectClassConfig,
        SubmissionPeriodRecord, SubmissionRecord, SubmissionRole,
        SubmittingStudent, StudentData, User,
    )
    from ..models.submissions import SubmissionRoleTypesMixin

    # --- Query parameters ---
    search_q = request.args.get("q", "").strip()
    pclass_filter = request.args.get("pclass_id", type=int)
    year_filter = request.args.get("year", "").strip()  # e.g. "2025" or "" for all
    year_order = request.args.get("order", "desc")  # "asc" or "desc"
    show_pending = request.args.get("pending", type=int, default=0)

    # --- Base query: all SubmissionRecords supervised by current user ---
    base_q = (
        db.session.query(SubmissionRecord)
        .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
        .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id)
        .join(StudentData, StudentData.id == SubmittingStudent.student_id)
        .join(User, User.id == StudentData.id)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.id == SubmissionRecord.period_id)
        .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id)
        .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id)
        .filter(
            SubmissionRole.user_id == current_user.id,
            SubmissionRole.role.in_([
                SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
            ]),
            SubmissionRecord.report_grade.isnot(None),
        )
        .distinct()
    )

    # --- Apply search filter ---
    # Search on name (when not anonymised) and project title.
    # After Tier 2 anonymisation User.first_name is None; User.name property
    # handles display but we filter on the raw columns here.
    if search_q:
        pattern = f"%{search_q}%"
        base_q = base_q.filter(
            or_(
                User.first_name.ilike(pattern),
                User.last_name.ilike(pattern),
                SubmissionRecord.project.has(LiveProject.name.ilike(pattern)),
            )
        )

    # --- Apply project class filter ---
    if pclass_filter:
        base_q = base_q.filter(ProjectClass.id == pclass_filter)

    # --- Apply year filter ---
    if year_filter:
        try:
            yr = int(year_filter)
            base_q = base_q.filter(ProjectClassConfig.year == yr)
        except ValueError:
            pass

    # --- Apply pending-approval filter ---
    if show_pending:
        base_q = base_q.filter(
            SubmissionRecord.exemplar_consent_granted_at.isnot(None),
            SubmissionRecord.exemplar_consent_withdrawn.is_(False),
            SubmissionRecord.exemplar_supervisor_approved.is_(None),
        )

    # --- Apply ordering ---
    if year_order == "asc":
        base_q = base_q.order_by(ProjectClassConfig.year.asc(), User.last_name.asc())
    else:
        base_q = base_q.order_by(ProjectClassConfig.year.desc(), User.last_name.asc())

    records = base_q.limit(100).all()

    # --- Counts for the alert banner ---
    pending_approval_count = (
        db.session.query(SubmissionRecord)
        .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
        .filter(
            SubmissionRole.user_id == current_user.id,
            SubmissionRole.role.in_([
                SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
            ]),
            SubmissionRecord.exemplar_consent_granted_at.isnot(None),
            SubmissionRecord.exemplar_consent_withdrawn.is_(False),
            SubmissionRecord.exemplar_supervisor_approved.is_(None),
        )
        .distinct()
        .count()
    )

    # --- Distinct project classes for filter pills ---
    available_pclasses = (
        db.session.query(ProjectClass)
        .join(ProjectClassConfig, ProjectClassConfig.pclass_id == ProjectClass.id)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.config_id == ProjectClassConfig.id)
        .join(SubmissionRecord, SubmissionRecord.period_id == SubmissionPeriodRecord.id)
        .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
        .filter(
            SubmissionRole.user_id == current_user.id,
            SubmissionRole.role.in_([
                SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
            ]),
            SubmissionRecord.report_grade.isnot(None),
        )
        .distinct()
        .order_by(ProjectClass.name)
        .all()
    )

    # --- Available years for dropdown ---
    year_rows = (
        db.session.query(ProjectClassConfig.year)
        .join(SubmissionPeriodRecord, SubmissionPeriodRecord.config_id == ProjectClassConfig.id)
        .join(SubmissionRecord, SubmissionRecord.period_id == SubmissionPeriodRecord.id)
        .join(SubmissionRole, SubmissionRole.submission_id == SubmissionRecord.id)
        .filter(
            SubmissionRole.user_id == current_user.id,
            SubmissionRole.role.in_([
                SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
            ]),
            SubmissionRecord.report_grade.isnot(None),
        )
        .distinct()
        .order_by(ProjectClassConfig.year.desc())
        .all()
    )
    available_years = [r[0] for r in year_rows]

    # Determine which MarkingReports belong to the current user on each record
    # (for the "My feedback" button visibility check)
    from ..models.markingevent import MarkingReport
    user_marking_reports = {}
    for record in records:
        mr = (
            db.session.query(MarkingReport)
            .join(MarkingReport.role)
            .filter(
                SubmissionRole.submission_id == record.id,
                SubmissionRole.user_id == current_user.id,
                SubmissionRole.role.in_([
                    SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
                    SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
                ]),
            )
            .first()
        )
        if mr is not None:
            user_marking_reports[record.id] = mr

    return render_template_context(
        "faculty/my_students.html",
        records=records,
        pending_approval_count=pending_approval_count,
        available_pclasses=available_pclasses,
        available_years=available_years,
        pclass_filter=pclass_filter,
        year_filter=year_filter,
        year_order=year_order,
        search_q=search_q,
        show_pending=show_pending,
        user_marking_reports=user_marking_reports,
        pane="my_students",
    )
```

### 2. Approval action routes

Add two more short routes to handle supervisor Approve/Decline/Revoke POSTs:

```python
@faculty.route("/consent_approve/<int:record_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def consent_approve(record_id):
    """Approve exemplar use for a SubmissionRecord."""
    from datetime import datetime
    from ..models import ConsentAuditEvent, SubmissionRecord, SubmissionRole
    from ..models.submissions import SubmissionRoleTypesMixin

    record: SubmissionRecord = SubmissionRecord.query.get_or_404(record_id)

    # Verify current user holds a supervisor role on this record
    role = SubmissionRole.query.filter(
        SubmissionRole.submission_id == record_id,
        SubmissionRole.user_id == current_user.id,
        SubmissionRole.role.in_([
            SubmissionRoleTypesMixin.ROLE_SUPERVISOR,
            SubmissionRoleTypesMixin.ROLE_RESPONSIBLE_SUPERVISOR,
        ]),
    ).first()
    if role is None:
        abort(403)

    now = datetime.utcnow()
    record.exemplar_supervisor_approved = True
    record.exemplar_supervisor_actioned_at = now
    db.session.add(ConsentAuditEvent(
        record_id=record.id,
        actor_id=current_user.id,
        event_type=ConsentAuditEvent.EXEMPLAR_SUPERVISOR_APPROVED,
        timestamp=now,
        ip_address=request.remote_addr,
    ))
    try:
        log_db_commit(
            f"Approved exemplar use for submission record #{record.id}",
            user=current_user,
        )
        flash("Exemplar use approved.", "success")
    except Exception as e:
        db.session.rollback()
        flash("An error occurred saving your decision.", "danger")

    return redirect(url_for("faculty.my_students"))


@faculty.route("/consent_decline/<int:record_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def consent_decline(record_id):
    """Decline exemplar use for a SubmissionRecord."""
    # Identical structure to consent_approve but sets approved=False
    # and uses ConsentAuditEvent.EXEMPLAR_SUPERVISOR_DECLINED.
    # Implementation follows the same pattern — omitted here for brevity
    # but must be written in full.
    pass


@faculty.route("/consent_revoke/<int:record_id>", methods=["POST"])
@roles_accepted("faculty", "admin", "root")
def consent_revoke(record_id):
    """Revoke a previously given supervisor approval."""
    # Sets exemplar_supervisor_approved=None (resets to unapproved state)
    # Uses ConsentAuditEvent.EXEMPLAR_SUPERVISOR_REVOKED.
    pass
```

Write `consent_decline` and `consent_revoke` in full, following the same
structure as `consent_approve`.

### 3. New template: `app/templates/faculty/my_students.html`

Create `app/templates/faculty/my_students.html`. It extends
`base_app.html` and adds "My students" as a pill tab in the faculty dashboard
navigation. Key structural requirements:

**Pill tab:** Add to the `{% block pillblock %}` in `dashboard.html` —
a "My students" tab that links to `url_for('faculty.my_students')`.
Show a badge with `pending_approval_count` if > 0, using `bg-warning text-dark`
colouring. This pill should always be visible (not conditional on having records).

**Alert banner:** At the top of the page body, if `pending_approval_count > 0`:

```html

<div class="alert alert-warning d-flex align-items-center gap-2">
    <i class="fas fa-clock fa-fw"></i>
    <span>
    <strong>{{ pending_approval_count }} project{{ pending_approval_count|pluralize }}</strong>
    have student consent for exemplar use and are awaiting your approval.
  </span>
</div>
```

**Toolbar:** Search input + project class pills + year dropdown + "Awaiting
approval" toggle pill, all in one `<div class="d-flex flex-wrap gap-2 align-items-center mb-3">`.

- Search:
  `<input type="text" name="q" value="{{ search_q }}" placeholder="Search by name or project title…" class="form-control form-control-sm" style="max-width: 240px">`
- Project class pills: "All" pill (active when `pclass_filter` is None) plus
  one pill per `available_pclasses`. Use the pill pattern from `template-ui-patterns.md`.
- Year dropdown: renders "All years ↓ newest first", "All years ↑ oldest first",
  then one option per `available_years`. Submits via JS `onchange` or a submit
  button.
- "Awaiting approval" pill: active when `show_pending=1`, links to
  `url_for('faculty.my_students', pending=1)`.

All filter controls submit as GET parameters to `url_for('faculty.my_students')`.
Wrap the toolbar in a `<form method="GET">` so search + filters compose correctly.

**Card layout** (one card per record in `records`):

Each card uses `<div class="card mt-2 mb-2">` with this internal structure:

```
card-body
  ├── top row (d-flex gap-3)
  │     ├── thumbnail (64×64, only if record.report and thumbnail available)
  │     ├── student info column (flex-grow-1)
  │     │     ├── student name (User.name — anonymisation-safe)
  │     │     ├── meta: programme · cohort · pclass name · year
  │     │     ├── project title (italic, text-body-secondary)
  │     │     └── metrics strip (small chips)
  │     └── right column (flex-shrink-0, text-end)
  │           ├── grade badge (e.g. "78%")
  │           └── action buttons: Report download · My feedback (if applicable)
  ├── feedback panel (collapsed by default, toggled by "My feedback" button)
  ├── <hr>
  └── consent strip
        ├── "Permissions:" label
        ├── exemplar badge (colour-coded by state)
        ├── open day badge (colour-coded by state)
        └── "Review ▾" / "Manage ▾" button (only if action available or decision made)
              └── approval panel (expanded inline when clicked)
```

**Thumbnail:** Render as:

```jinja
{% if record.report and record.report.small_thumbnail and not record.report.small_thumbnail.lost %}
    <img src="{{ url_for('documents.serve_thumbnail', asset_type='submitted', asset_id=record.report_id, size='small') }}"
         alt="Report thumbnail"
         width="64" height="64"
         style="object-fit: cover; border-radius: 6px; border: 0.5px solid var(--bs-border-color)">
{% else %}
    <div style="width:64px;height:64px;border-radius:6px;border:0.5px solid var(--bs-border-color);
                background:var(--bs-tertiary-bg);display:flex;align-items:center;justify-content:center">
        <i class="fas fa-file-alt fa-lg text-body-secondary"></i>
    </div>
{% endif %}
```

**Metrics strip:** Render as small chips only when language analysis is
complete (`record.language_analysis_complete`). Parse `record.language_analysis`
JSON and surface only: `page_count`, `declared_word_count`, `measured_word_count`,
`estimated_reading_time_minutes`, `figure_count`, `table_count`. Do not surface
any lexical metrics, Mahalanobis distance, or AI classification fields.

**Consent strip badge states:**

| Condition                                                           | Badge classes                                                          | Label                               |
|---------------------------------------------------------------------|------------------------------------------------------------------------|-------------------------------------|
| `exemplar_consent_granted_at is None`                               | `bg-secondary-subtle text-secondary`                                   | `Exemplar — no consent`             |
| `exemplar_consent_active and exemplar_supervisor_approved is None`  | `bg-warning-subtle text-warning-emphasis border border-warning-subtle` | `Exemplar — awaiting your approval` |
| `exemplar_fully_approved`                                           | `bg-success-subtle text-success-emphasis border border-success-subtle` | `Exemplar — approved by you`        |
| `exemplar_consent_active and exemplar_supervisor_approved == False` | `bg-secondary-subtle text-secondary`                                   | `Exemplar — declined by you`        |
| `openday_consent_active`                                            | `bg-success-subtle text-success-emphasis border border-success-subtle` | `Open day — student consented`      |
| `not openday_consent_active`                                        | `bg-secondary-subtle text-secondary`                                   | `Open day — no consent`             |

**Approval panel** (inline, collapsed by default using Bootstrap collapse):

- Pending: amber `alert-warning`, explanatory text, "Approve" (POST to
  `faculty.consent_approve`) and "Decline" (POST to `faculty.consent_decline`) buttons.
- Approved: green `alert-success`, timestamp, "Withdraw approval" (POST to
  `faculty.consent_revoke`, styled `btn-outline-danger btn-sm`).
- Declined: neutral, "Reconsider" (POST to `faculty.consent_approve`).

Use Bootstrap's `collapse` component for the approval panel, triggered by the
"Review ▾" / "Manage ▾" button. Each collapse `id` must be unique:
`collapse-consent-{{ record.id }}`.

**Anonymisation safety:** Use `record.owner.student.user.name` for display
(the `name` property handles the anonymised case per the handoff doc). Suppress
the "My feedback" button for anonymised users (`user.is_anonymised`). The
thumbnail and report download still function via `SubmissionRole`-gated access.

### 4. Update "My projects" dropdown menu

Find where the faculty "My projects" dropdown menu is rendered (search for
`"Students"` in the faculty templates). Replace the existing stub with:

```jinja
<li>
    <a class="dropdown-item" href="{{ url_for('faculty.my_students') }}">
        <i class="fas fa-user-graduate fa-fw me-1"></i> My students…
    </a>
</li>
```

---

## Verification

```bash
# Routes registered
flask routes | grep "my_students\|consent_approve\|consent_decline\|consent_revoke"

# Template renders for a faculty user with supervised records
# (manual browser test)

# Approval action: POST to consent_approve updates the database
python3 -c "
from app import create_app
app = create_app()
with app.app_context():
    from app.models import SubmissionRecord
    # Find a record with exemplar_consent_granted_at set
    r = SubmissionRecord.query.filter(
        SubmissionRecord.exemplar_consent_granted_at.isnot(None)
    ).first()
    if r:
        print(f'Record #{r.id}: supervisor_approved={r.exemplar_supervisor_approved}')
    else:
        print('No consented records yet — create test data manually')
"
```