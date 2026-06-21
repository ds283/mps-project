# Phase 5b recon — marking/moderator report access for data_dashboard_reports / data_dashboard_similarity

## Step 0.1 — The routes, verbatim

### `faculty.view_marking_report` (`app/faculty/views.py:3771-3838`)

```python
@faculty.route("/view_marking_report/<int:report_id>")
@roles_accepted("faculty", "admin", "root")
def view_marking_report(report_id):
    """
    Read-only view of a submitted MarkingReport — shows grade, field values, and feedback.
    Accessible to the role owner (after submission) and to convenors/admins/root.
    """
    import json as _json

    report: MarkingReport = MarkingReport.query.get_or_404(report_id)
    workflow = report.workflow
    scheme = workflow.scheme
    submitter_report = report.submitter_report
    record: SubmissionRecord = submitter_report.record
    period: SubmissionPeriodRecord = record.period
    pclass: ProjectClass = workflow.event.pclass

    from ..models.markingevent import marking_report_to_responsible_supervisors

    is_allowed, is_elevated = _can_access_marking_form(report)
    is_role_owner = report.role.user_id == current_user.id
    is_responsible_supervisor = (
        db.session.query(SubmissionRole)
        .join(
            marking_report_to_responsible_supervisors,
            marking_report_to_responsible_supervisors.c.submission_role_id == SubmissionRole.id,
        )
        .filter(
            marking_report_to_responsible_supervisors.c.marking_report_id == report.id,
            SubmissionRole.user_id == current_user.id,
        )
        .count()
        > 0
    )
    if not is_allowed and not (is_role_owner and report.report_submitted) and not is_responsible_supervisor:
        flash("You do not have permission to view this marking report.", "error")
        return redirect(redirect_url())

    url = request.args.get("url", url_for("faculty.dashboard"))

    schema = scheme.schema_as_dict if scheme else {}
    field_values = {}
    validation_failures = []

    if report.report and report.report != "{}":
        try:
            blob = _json.loads(report.report)
            field_values = blob.get("fields", {})
            validation_failures = blob.get("validation_failures", [])
        except Exception:
            pass

    return render_template_context(
        "faculty/view_marking_report.html",
        report=report,
        workflow=workflow,
        scheme=scheme,
        schema=schema,
        record=record,
        period=period,
        pclass=pclass,
        field_values=field_values,
        validation_failures=validation_failures,
        is_elevated=is_elevated,
        is_responsible_supervisor=is_responsible_supervisor,
        url=url,
        approve_form=ApproveMarkingReportForm(),
    )
```

Single `@faculty.route` with **no `methods=` argument** → GET/HEAD only. No POST handling anywhere in
the body. **Genuinely read-only at the route level.**

### `faculty.moderator_report_form` (`app/faculty/views.py:3914-4047`)

```python
@faculty.route("/moderator_report_form/<int:mod_report_id>", methods=["GET", "POST"])
@roles_accepted("faculty", "admin", "root")
def moderator_report_form(mod_report_id):
    """
    Display and process the moderator report form for a single ModeratorReport.
    Accessible only to the assigned moderator (or elevated users).
    """
    from datetime import datetime

    from flask_wtf import FlaskForm
    from wtforms import DecimalField, SubmitField, TextAreaField
    from wtforms.validators import InputRequired, NumberRange, Optional as WTFOptional

    from ..models.markingevent import SubmitterReportWorkflowStates

    mod_report: ModeratorReport = ModeratorReport.query.get_or_404(mod_report_id)
    sr = mod_report.submitter_report
    workflow = sr.workflow
    pclass = workflow.event.pclass
    record: SubmissionRecord = sr.record

    is_elevated = current_user.has_role("admin") or current_user.has_role("root") or (
        current_user.faculty_data is not None and current_user.faculty_data.is_convenor_for(pclass)
    )
    is_owner = mod_report.role.user_id == current_user.id

    if not is_elevated and not is_owner:
        flash("You do not have permission to access this moderator report.", "error")
        return redirect(redirect_url())

    is_editable = is_owner  # convenors may view but not submit

    url = request.args.get("url", url_for("faculty.dashboard_moderation"))

    class ModeratorReportForm(FlaskForm):
        grade = DecimalField(
            "Recommended grade (%)",
            places=1,
            validators=[InputRequired("Please enter a recommended grade."), NumberRange(min=0, max=100)],
        )
        report = TextAreaField(
            "Justification",
            validators=[WTFOptional()],
            description="Explain your recommended grade, noting any significant discrepancies between the markers.",
        )
        submit = SubmitField("Submit moderator report")

    form = ModeratorReportForm(request.form)

    if form.validate_on_submit() and is_editable:
        mod_report.grade = form.grade.data
        mod_report.report = form.report.data
        mod_report.report_submitted = True
        mod_report.submitted_timestamp = datetime.now()

        if sr.grade is None:
            sr.grade = mod_report.grade
            sr.grade_generated_by_id = current_user.id
            sr.grade_generated_timestamp = datetime.now()
            sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
            sr.accepted_moderator_report_id = mod_report.id
            sr.moderator_accepted_id = mod_report.role_id
            sr.moderator_accepted_timestamp = datetime.now()
        else:
            sr.workflow_state = SubmitterReportWorkflowStates.REQUIRES_CONVENOR_INTERVENTION
            sr.convenor_intervention = True

        try:
            log_db_commit(
                f"Moderator {current_user.name} submitted moderator report for SubmitterReport #{sr.id} "
                f"(workflow: {workflow.name}, student: {sr.student.user.name}, grade: {mod_report.grade})",
                user=current_user,
                project_classes=pclass,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not submit moderator report due to a database error.", "error")
            return redirect(url_for("faculty.moderator_report_form", mod_report_id=mod_report_id))

        return redirect(url_for("faculty.thankyou_moderator_report"))

    # Pre-populate grade if already set
    if request.method == "GET" and mod_report.grade is not None:
        form.grade.data = mod_report.grade
        form.report.data = mod_report.report

    import json

    marking_reports = sr.marking_reports.all()
    sorted_reports = sorted(marking_reports, key=lambda r: r.id)
    ... (builds report_data / submitted_grades / grade_spread / marker_labels / scheme / schema /
         filtered_attachments, then renders faculty/moderator_report_form.html)
```

`methods=["GET", "POST"]`, with a real `FlaskForm` and a real write path
(`mod_report.grade = ...`, `sr.grade = ...`, `log_db_commit(...)`). **Not read-only at the route
level** — there is a write surface on this exact endpoint.

## Step 0.2 — Read-only vs write, and a refinement that changes the answer

- `view_marking_report`: genuinely read-only. Confirmed.
- `moderator_report_form`: has a write surface (the central question's literal answer is "yes, it's
  combined"). **But** the write surface's gate is *structurally independent* of the route's role
  decorator: `is_editable = is_owner`, and `is_owner = mod_report.role.user_id == current_user.id`
  — a literal, single-row, no-tenant-or-role-involved fact about who the assigned moderator is.
  Critically, **`is_editable` does not consult `is_elevated` at all** — that's why the comment says
  "convenors may view but not submit": today, even a convenor/admin/root hitting this route only
  ever gets `is_editable=True` if they happen to literally be `mod_report.role.user_id`, which contradicts
  "convenor" in the normal case. So widening *who can reach the route* does not, by itself, widen
  *who can write through it* — that's gated by a completely separate fact this phase isn't touching.

  This matters for Step 1 but doesn't settle it by itself — see the Option B writeup below for why
  the literal future-maintenance risk still favours not reusing this combined route.

## Step 0.3 — Per-object permission narrowing beyond the role decorator

### `view_marking_report` (and its siblings `marking_form` / `edit_marking_feedback`, which share `_can_access_marking_form`)

```python
def _can_access_marking_form(report: MarkingReport) -> tuple:
    """
    Returns (is_allowed, is_elevated) where is_elevated means the user is a convenor/admin/root
    who can access the form even when the normal access window has closed.
    """
    from ..models.markingevent import SubmitterReportWorkflowStates
    from ..shared.validators import validate_is_convenor

    if report.submitter_report.workflow_state == SubmitterReportWorkflowStates.DROPPED:
        return False, False

    pclass = report.workflow.event.pclass
    is_elevated = validate_is_convenor(pclass, message=False)
    is_role_owner = report.role.user_id == current_user.id

    if is_elevated:
        return True, True
    if is_role_owner:
        return report.marking_form_is_open, False
    return False, False
```

`view_marking_report` additionally allows `is_role_owner and report.report_submitted`, and
`is_responsible_supervisor` (a join through `marking_report_to_responsible_supervisors`). None of
these three paths (`is_elevated` via `validate_is_convenor`, `is_role_owner`, `is_responsible_supervisor`)
would ever be true for a `data_dashboard_reports`/`data_dashboard_similarity`-only user — they are not
a convenor for the pclass, not the report's role owner, not a responsible supervisor. **So merely
adding the two roles to `@roles_accepted(...)` is not sufficient — they would clear the decorator and
then immediately hit the internal `flash(...); return redirect(...)` and bounce straight back out.**
Both the decorator *and* the internal gate need to change together.

`validate_is_convenor` (`app/shared/validators.py:43-91`) already has exactly the tenant-scoping
mechanism this phase needs, **and it is already the established codebase pattern for "let this
specific non-convenor role view convenor-ish material, tenant-scoped"** — `app/convenor/markingevent.py`
calls it with `allow_roles=["office", "external_examiner", "exam_board"]` at 18 call sites:

```python
def validate_is_convenor(
    pclass: ProjectClass, message: bool = True, allow_roles: Optional[List[str]] = None
):
    # root users can always access
    if current_user.has_role("root"):
        return True

    # admin users can access if they belong to the same tenant as the project class
    if current_user.has_role("admin"):
        if pclass.tenant_id is None:
            return True
        if pclass.tenant is not None and any(
                [t.id == pclass.tenant_id for t in current_user.tenants]
        ):
            return True

    # convenor for this pclass is ok
    if pclass.is_convenor(current_user.id):
        return True

    # if the current user has any of the specified roles, check tenancy and allow access
    if allow_roles is not None:
        for role in allow_roles:
            if current_user.has_role(role):
                # for external_examiner and exam_board roles, check tenancy
                if role in ["external_examiner", "exam_board"]:
                    if pclass.tenant_id is None:
                        return True
                    if pclass.tenant is not None and any(
                            [t.id == pclass.tenant_id for t in current_user.tenants]
                    ):
                        return True
                else:
                    return True   # <-- NB: "office" goes through here UNSCOPED. Pre-existing, unrelated.

    if message:
        flash(...)
    return False
```

**Important wrinkle found while reading this**: the `else: return True` branch grants *unscoped*
(no tenant check) access for any role in `allow_roles` that isn't literally `"external_examiner"` or
`"exam_board"` — that's how `"office"` already gets blanket cross-tenant access through this helper
today (pre-existing, not something this phase touches). If I add `data_dashboard_reports` /
`data_dashboard_similarity` to `allow_roles` at a call site, **I must also add them to the
`role in [...]` tenant-scoped list** (alongside `external_examiner`/`exam_board`), otherwise they'd
silently fall into the unscoped branch and get exactly the blanket cross-tenant access Step 0.3 of
the prompt warns against. This is a one-line, purely additive change to that list — no existing
caller passes these two role names today, so no existing call site's behaviour changes.

### `moderator_report_form`

No tenant narrowing at all beyond `is_elevated`/`is_owner` as shown above; `is_elevated`'s convenor
branch (`is_convenor_for(pclass)`) is itself implicitly tenant-correct (a convenor only convenes
pclasses in their own tenant), but there's no equivalent "non-convenor read access" branch to extend
the way `validate_is_convenor`'s `allow_roles` does for the marking-report routes.

## Step 0.4 — Existing read-only surface elsewhere?

- For `MarkingReport`: **yes** — `view_marking_report` itself already *is* that surface (this is
  exactly why Phase 5 linked to it rather than `marking_form`). No separate read-only/print/PDF view
  exists or is needed.
- For `ModeratorReport`: **no.** `moderator_report_form` is the only route that renders a
  `ModeratorReport`'s content. No print/PDF/external-examiner read view of a `ModeratorReport`
  exists anywhere in the app (grepped `moderator_report_form`, `ModeratorReport` across templates
  and views — only the one route, one template).

## Step 0.5 — Does the Similarity dashboard hit the same route(s)?

Confirmed by grep: `similarity_concern_detail.html` only ever links `faculty.view_marking_report`
(two call sites, lines 256 and 487, one for each side of the concern pair) — **same route as AVD**.
It **never** links `moderator_report_form` or any `ModeratorReport` at all. This isn't an oversight
to fix — it's structural: the staff list loop iterates `role.marking_reports` for every role
(including the moderator role, since `_included_roles = [0, 1, 3, 6]` includes `ROLE_MODERATOR=3`),
but a moderator role's reports live in `role.moderator_reports`, not `role.marking_reports`, so that
loop is always empty for a moderator row. There is no "click through to the moderator's report" path
on the Similarity dashboard today, full stop.

**Net effect: the ModeratorReport part of this phase (Option B below) is AVD-only.** The
MarkingReport part (Option A below) is genuinely shared and fixes both dashboards via the same route.

### A second, more subtle gap on the Similarity dashboard that Step 0.5 surfaced

The two `view_marking_report` links in `similarity_concern_detail.html` are themselves wrapped in:

```jinja2
{% if is_faculty or is_admin or is_root %}
    {% for mr in role.marking_reports %}
        <a href="{{ url_for('faculty.view_marking_report', ...) }}">...</a>
    {% endfor %}
{% endif %}
```

(lines 254–267 and 485–498, identical condition both times). `is_data_dashboard_similarity` is
**not** in that condition. So today, a `data_dashboard_similarity`-only user doesn't hit a 403 when
clicking this link — **the link is never rendered for them in the first place.** This is a quieter
version of the same underlying gap (the route access problem still exists if they constructed the
URL by hand), but the AVD framing of "renders, then 403s" doesn't literally describe what happens on
the Similarity dashboard today. Fixing only the route, without this template condition, would leave
the Similarity dashboard's link permanently invisible to its own `data_dashboard_similarity` audience
— so this template change is a necessary part of "fixing the gap" for that dashboard, not optional
polish.

## Step 1 — Proposed fix

> **Correction after user review** (applies throughout this section): the original proposal below
> reused `validate_is_convenor`'s `allow_roles` mechanism for the two new dashboard roles. The user
> rejected this: `validate_is_convenor` must only ever mean "is a convenor" — it's called as a
> convenor-equivalence check at 18+ other sites in `app/convenor/markingevent.py`, and folding a
> read-only audit role into its `allow_roles` branch (even tenant-scoped) blurs that contract and
> risks a future caller treating "passed validate_is_convenor" as license for something write-capable.
> **What actually shipped instead**: a new, standalone `validate_data_dashboard_access(pclass, roles,
> message=False)` in `app/shared/validators.py`, completely separate from `validate_is_convenor`
> (which is untouched — confirmed by `git diff` showing zero changes to that function). Every
> `validate_is_convenor(allow_roles=["data_dashboard_reports", ...])` call shown in the diffs below
> was replaced with `validate_data_dashboard_access(pclass, [...], message=False)`. See the
> "Implemented" and "Risk flag" sections near the end of this document for the corrected, final code.
> Left the rest of this section as-written below since it's the historical record of the
> investigation that led to Option A/B — the choice of *route* and *option* per report type didn't
> change, only the *mechanism* for the tenant-scoped permission check itself.

### MarkingReport → `view_marking_report`: **Option A**

Genuinely read-only route (Step 0.1/0.2), so widen the decorator. To make that actually work (Step
0.3), the internal allow-check needs a third path alongside `is_allowed` (`_can_access_marking_form`)
and the owner/responsible-supervisor checks — reusing `validate_is_convenor`'s existing tenant-scoped
`allow_roles` mechanism rather than inventing a parallel tenant check.

**Exact diff:**

1. `app/shared/validators.py:75` — add the two new roles to the tenant-scoped branch:
   ```python
   if role in ["external_examiner", "exam_board", "data_dashboard_reports", "data_dashboard_similarity"]:
   ```
   (Purely additive — no existing caller passes these role names in `allow_roles` today, so no
   existing call site's behaviour changes.)

2. `app/faculty/views.py:3771-3772` — widen the decorator:
   ```python
   @faculty.route("/view_marking_report/<int:report_id>")
   @roles_accepted("faculty", "admin", "root", "data_dashboard_reports", "data_dashboard_similarity")
   def view_marking_report(report_id):
   ```

3. `app/faculty/views.py`, inside `view_marking_report`, add a fourth allow-path that does **not**
   touch `is_elevated` (so the template's `is_elevated`-gated "Edit report" button — which links to
   the still-locked-down `marking_form` route — stays hidden for these roles, not just inert):
   ```python
   is_allowed, is_elevated = _can_access_marking_form(report)
   is_role_owner = report.role.user_id == current_user.id
   is_responsible_supervisor = (...)  # unchanged
   is_dashboard_viewer = validate_is_convenor(
       pclass, message=False, allow_roles=["data_dashboard_reports", "data_dashboard_similarity"]
   )
   if not is_allowed and not (is_role_owner and report.report_submitted) and not is_responsible_supervisor and not is_dashboard_viewer:
       flash("You do not have permission to view this marking report.", "error")
       return redirect(redirect_url())
   ```
   (`validate_is_convenor` is already imported inside `_can_access_marking_form` via a local import;
   `view_marking_report` will need its own local `from ..shared.validators import validate_is_convenor`.)

4. `app/ajax/archive/reports.py`, `_role_report_links()` — pass an explicit `url=` so the rendered
   page's "Return" button doesn't default to `faculty.dashboard` (`@roles_required("faculty")` —
   would itself 403 a `data_dashboard_reports`/`data_dashboard_similarity`-only viewer who has no
   `faculty` role). This is necessary for the fix to actually be usable end-to-end, not just "doesn't
   403 on the initial click":
   ```python
   "url": url_for("faculty.view_marking_report", report_id=report.id, url=url_for("dashboards.avd_dashboard")),
   ```

5. `app/templates/dashboards/similarity_concern_detail.html:254` and `:485` — add the missing
   visibility condition so `data_dashboard_similarity` users actually see the link Step 0.5 found is
   currently hidden from them:
   ```jinja2
   {% if is_faculty or is_admin or is_root or is_data_dashboard_similarity %}
   ```
   (`is_data_dashboard_similarity` is already a global template context variable — `app/shared/context/global_context.py:116, 141`.)

No template/route change needed for the AVD dashboard's `_details` panel rendering itself — it has
no analogous role gate around `role_reports` (`app/ajax/archive/reports.py:353-356`), so once the
route accepts the role, the existing link "just works."

### ModeratorReport → `moderator_report_form`: **Option B**

Despite the Step 0.2 refinement (the write gate is already structurally decoupled from role), I'm
proposing **not** to reuse this route, for three reasons:

1. The prompt's own Step 0.2 framing is binary on a literal fact (does this *endpoint* have a write
   surface) — it does, and the decoupling is an implementation detail of today's code, not a
   contract. A later change to `is_editable` (e.g. "let convenors override the moderator's grade
   too" — a very plausible future feature in a marking-event tool) could easily fold `is_elevated`
   into `is_editable`'s computation without anyone noticing that `is_elevated`-equivalent dashboard
   roles were sitting on the other side of the same `if` block. Keeping new roles on a route that
   has zero `methods=["POST"]` capability at the URL-routing level is strictly safer and doesn't rely
   on remembering *why* `is_editable` happens to be safe today.
2. `moderator_report_form` is the live moderation workflow surface — linked from the moderator's own
   "submit your report" dashboard pane, the convenor's marking-event inspector, and the
   "please submit your moderation report" email task (`app/tasks/markingevent.py:183`). A new route
   keeps the AVD dashboard's archival/read-only link completely outside that surface's blast radius;
   any future change to the live workflow route can't accidentally affect the archive viewer, and
   vice versa.
3. It's AVD-only (Step 0.5) — there's no parallel Similarity-dashboard call site to keep in sync,
   so a second route doesn't create the kind of drift risk it would if both dashboards needed it.

**Exact diff:**

1. `app/faculty/views.py` — hoist the inline `ModeratorReportForm` class (currently defined inside
   `moderator_report_form`, lines 3948-3959) to module scope (with its three local imports moved up
   alongside it) so both the existing write route and the new read-only route render identical fields
   without duplicating label/description/validator text:
   ```python
   from flask_wtf import FlaskForm
   from wtforms import DecimalField, SubmitField, TextAreaField
   from wtforms.validators import InputRequired, NumberRange, Optional as WTFOptional

   class ModeratorReportForm(FlaskForm):
       grade = DecimalField(
           "Recommended grade (%)",
           places=1,
           validators=[InputRequired("Please enter a recommended grade."), NumberRange(min=0, max=100)],
       )
       report = TextAreaField(
           "Justification",
           validators=[WTFOptional()],
           description="Explain your recommended grade, noting any significant discrepancies between the markers.",
       )
       submit = SubmitField("Submit moderator report")
   ```
   `moderator_report_form` itself drops its local copy and uses the module-level class — behaviourally
   identical, just de-duplicated.

2. `app/faculty/views.py` — new route, **GET only** (no `methods=` argument at all, so Flask 405s any
   POST before the view body ever runs — the write path doesn't exist at the URL-routing level, not
   just at the application-logic level):
   ```python
   @faculty.route("/view_moderator_report/<int:mod_report_id>")
   @roles_accepted("data_dashboard_reports", "admin", "root")
   def view_moderator_report(mod_report_id):
       """
       Read-only view of a ModeratorReport for the AVD dashboard's archive links.
       No POST method — unlike faculty.moderator_report_form (the live workflow route
       actual moderators use to submit their report), there is no write surface here
       at all. admin/root get unconditional access; data_dashboard_reports is scoped
       to their accessible tenants, matching the AVD dashboard's own tenant-scoping
       (Phase 1) via the same validate_is_convenor(allow_roles=...) mechanism used for
       view_marking_report above.
       """
       from ..shared.validators import validate_is_convenor

       mod_report: ModeratorReport = ModeratorReport.query.get_or_404(mod_report_id)
       sr = mod_report.submitter_report
       workflow = sr.workflow
       pclass = workflow.event.pclass
       record: SubmissionRecord = sr.record

       if not validate_is_convenor(pclass, message=False, allow_roles=["data_dashboard_reports"]):
           flash("You do not have permission to view this moderator report.", "error")
           return redirect(redirect_url())

       url = request.args.get("url", url_for("dashboards.avd_dashboard"))

       form = ModeratorReportForm()
       form.grade.data = mod_report.grade
       form.report.data = mod_report.report

       marking_reports = sr.marking_reports.all()
       sorted_reports = sorted(marking_reports, key=lambda r: r.id)
       # ... identical report_data / submitted_grades / grade_spread / marker_labels /
       #     scheme / schema / filtered_attachments construction, copied verbatim from
       #     moderator_report_form (the read-only-relevant half of that function only —
       #     no form.validate_on_submit() call exists in this function at all).

       return render_template_context(
           "faculty/moderator_report_form.html",
           form=form,
           mod_report=mod_report,
           sr=sr,
           workflow=workflow,
           pclass=pclass,
           record=record,
           sorted_reports=sorted_reports,
           report_data=report_data,
           marker_labels=marker_labels,
           scheme=scheme,
           schema=schema,
           filtered_attachments=filtered_attachments,
           is_editable=False,
           grade_spread=grade_spread,
           url=url,
       )
   ```
   Reuses `faculty/moderator_report_form.html` as-is — that template already has a complete
   `is_editable=False` rendering path (`<fieldset disabled>`, submit/cancel buttons replaced by a
   single "Return" link at lines 144/162-171 of the template), built for exactly this purpose
   already (it's how admin/root/convenors already view it today without being able to submit). No
   template change needed for this half of the fix. (`is_elevated` is accepted by the existing route
   but not actually referenced anywhere in the template — confirmed by grep — so the new route
   doesn't need to compute or pass it.)

   `data_dashboard_similarity` is deliberately **not** in this route's decorator — Step 0.5 found no
   exposed ModeratorReport link on the Similarity dashboard to fix, so adding it here would be
   unused, untested surface area.

3. `app/ajax/archive/reports.py`, `_role_report_links()` — branch the URL on viewer, so admin/root
   keep using the existing live route exactly as before (zero behaviour change for them) and only
   a non-admin/root viewer (i.e. `data_dashboard_reports`, the only other role that can reach the AVD
   dashboard at all) gets the new read-only route:
   ```python
   if role.role == SubmissionRole.ROLE_MODERATOR:
       report = role.moderator_reports.order_by(ModeratorReport.creation_timestamp.desc(), ModeratorReport.id.desc()).first()
       if report is not None:
           if current_user.has_role("admin") or current_user.has_role("root"):
               report_url = url_for("faculty.moderator_report_form", mod_report_id=report.id, url=url_for("dashboards.avd_dashboard"))
           else:
               report_url = url_for("faculty.view_moderator_report", mod_report_id=report.id, url=url_for("dashboards.avd_dashboard"))
           links.append({"label": role.role_as_str, "user_name": role.user.name, "url": report_url})
   ```
   (Requires adding `from flask_login import current_user` to this file's imports — not currently
   imported there.)

## Step 2 — Implemented

All five diffs from Step 1 were applied as proposed, with one pure-refactor addition discovered
while implementing Option B: `moderator_report_form`'s inline `ModeratorReportForm` class and its
~25-line "marker reference panel" context construction (`sorted_reports`/`report_data`/
`grade_spread`/`marker_labels`/`scheme`/`schema`/`filtered_attachments`) were extracted to module
scope (`ModeratorReportForm`) and a shared helper (`_moderator_report_reference_data(sr, workflow)`)
respectively, so `view_moderator_report` reuses both instead of duplicating field labels/validators
or the reference-panel logic. `moderator_report_form`'s own behaviour is unchanged — confirmed by
diff: only the class/data-construction moved, the write path, form validation, and redirects are
byte-for-byte identical.

Files touched:
- `app/shared/validators.py` — **`validate_is_convenor` is untouched** (reverted to its original
  form after user review — see the correction note above Step 1). Added a new, standalone
  `validate_data_dashboard_access(pclass, roles, message=True)`: loops over the given
  `data_dashboard_*` role names, and for any the user holds, applies the same
  tenant-scoping test (`pclass.tenant_id is None or any(t.id == pclass.tenant_id for t in
  current_user.tenants)`) used by `validate_is_convenor`'s admin branch — duplicated rather than
  shared, specifically so this function has zero code path in common with convenor validation.
- `app/faculty/views.py` — `view_marking_report` decorator + `is_dashboard_viewer` gate (now calling
  `validate_data_dashboard_access`, not `validate_is_convenor`); new `view_moderator_report` route
  (GET-only) with its own `is_elevated = has_role("admin") or has_role("root")` plus
  `is_dashboard_viewer = validate_data_dashboard_access(pclass, ["data_dashboard_reports"], message=False)`;
  `ModeratorReportForm` + `_moderator_report_reference_data` hoisted to module scope;
  `moderator_report_form` updated to use the shared helper (no behaviour change).
  `validate_data_dashboard_access` added to the module's existing `from ..shared.validators import (...)`
  block (no new per-function local imports needed).
- `app/ajax/archive/reports.py` — `_role_report_links()` now passes an explicit `url=` for both
  link types, and branches the ModeratorReport link between the existing `moderator_report_form`
  (admin/root) and the new `view_moderator_report` (everyone else reaching the AVD dashboard, i.e.
  `data_dashboard_reports`).
- `app/templates/dashboards/similarity_concern_detail.html` — `is_data_dashboard_similarity` added
  to both copies of the "Marking record" link's visibility condition.

All four files compile cleanly (`python3 -m py_compile`), and `git diff app/shared/validators.py`
shows `validate_is_convenor` itself with zero changes — only a new, separate function added above it.

## Step 3 — Verification (static code trace; live browser/DB check not performed — consistent with
how Phase 5's own Step 4 verification was done in this same project, and with prior guidance to ask
before spinning up the dev stack for UI verification)

- [x] **`data_dashboard_reports`-only user can open both link types from the AVD dashboard.**
      `_can_access_avd_dashboard()` already accepted this role, so the dashboard itself and the
      (ungated) `role_reports` rendering in `app/ajax/archive/reports.py:353-356` are unaffected.
      `view_marking_report`'s decorator now lists `data_dashboard_reports`; its internal gate's new
      `is_dashboard_viewer = validate_data_dashboard_access(pclass, ["data_dashboard_reports", "data_dashboard_similarity"], message=False)`
      evaluates True for a same-tenant pclass (this user holds `data_dashboard_reports`, and the
      record's pclass is within the AVD dashboard's own already-tenant-filtered result set, so the
      tenant check inside `validate_data_dashboard_access` passes). For a moderator-role link,
      `_role_report_links()` now sends this user to `view_moderator_report`, whose decorator accepts
      `data_dashboard_reports` and whose gate is `is_elevated = has_role("admin") or has_role("root")`
      (False here) `or is_dashboard_viewer = validate_data_dashboard_access(pclass, ["data_dashboard_reports"], message=False)`
      (True). Both links now also carry an explicit `url=url_for("dashboards.avd_dashboard")`, so
      "Return" goes back to the dashboard rather than to `faculty.dashboard`/`faculty.dashboard_moderation`
      (both `@roles_required("faculty")`/role-gated routes this user may not hold — confirmed this
      would otherwise have been a second, self-inflicted 403 on the way back out).
- [x] **`data_dashboard_similarity`-only user can open the equivalent link from the Similarity
      dashboard.** Before this phase, the "Marking record" link in `similarity_concern_detail.html`
      was wrapped in `{% if is_faculty or is_admin or is_root %}` — invisible to this role, not just
      403-prone. Added `or is_data_dashboard_similarity` (a pre-existing global-context boolean) to
      both copies of that condition. Once visible, the link hits the same `view_marking_report` route
      and the same `is_dashboard_viewer` check above (which already lists `data_dashboard_similarity`).
      Confirmed structurally that no `ModeratorReport` link is expected on this dashboard: the staff
      list loop reads `role.marking_reports`, which is empty for a `ROLE_MODERATOR` row (that role's
      reports live in `role.moderator_reports` instead) — so `view_moderator_report` deliberately
      does not accept `data_dashboard_similarity` (its decorator: `roles_accepted("data_dashboard_reports", "admin", "root")` only) and nothing regresses by that omission.
- [x] **Neither role gained write capability.** Traced every write-capable destination reachable
      from the pages these roles can now see:
      - `marking_form`, `edit_marking_feedback`, `approve_marking_report` decorators are untouched
        (`@roles_accepted("faculty", "admin", "root")` — Flask-Security rejects the request at the
        decorator before any view code runs for a `data_dashboard_reports`/`data_dashboard_similarity`-
        only caller, regardless of what the unconditional "Edit feedback" button or the
        `is_elevated`-gated "Edit report" button render in the template). `is_elevated` itself is
        computed by the **unmodified** `_can_access_marking_form()` call (no `allow_roles`), so it
        stays False for both new roles — the "Edit report" button does not even render for them in
        the normal case, and even in the edge case where `report.marking_form_is_open` happens to be
        True independent of viewer (AVD-dashboard records are from closed periods, so in practice
        this property is reliably False — `distributed` would be long-settled and
        `grade_submitted_timestamp` more than a day old), the destination is still decorator-locked.
      - `moderator_report_form`'s write path (`mod_report.grade = ...`, `sr.grade = ...`,
        `log_db_commit(...)`) is gated by `is_editable = is_owner`, completely unmodified, and
        unreachable by these roles anyway since `_role_report_links()` no longer sends them to this
        route at all (only admin/root use it, exactly as before).
      - `view_moderator_report` has no `methods=` argument at all → Flask returns 405 on any POST
        before the view body runs; `is_editable=False` is hard-coded (not derived from any role
        check), so even the template's existing read-only rendering path is the only one this route
        can produce.
- [x] **Tenant isolation against a hand-crafted URL.** For a `data_dashboard_reports` user scoped to
      tenant A hand-crafting a `view_marking_report`/`view_moderator_report` URL for a `report_id`/
      `mod_report_id` whose `pclass.tenant_id` is tenant B: inside `validate_data_dashboard_access`,
      the user holds the role, so the loop body runs; `pclass.tenant_id is None` is False (tenant B
      pclasses have a tenant), and `any(t.id == pclass.tenant_id for t in current_user.tenants)` is
      False (tenant A user, tenant B pclass) → no role in the list satisfies the tenant check →
      falls through to `return False`. Combined with the other allow-paths also being False for this
      user (not convenor/owner/supervisor for a tenant-B record, not admin/root) → permission-denied
      flash + redirect, not the report. (The one pre-existing-pattern, unrelated bypass —
      `pclass.tenant_id is None` for legacy no-tenant pclasses — mirrors `validate_is_convenor`'s own
      admin-branch backwards-compatibility behaviour; deliberately copied for consistency, not a new
      loophole.)
- [x] **Existing `faculty`/`admin`/`root` access unaffected.** `view_marking_report`'s decorator only
      gained roles, lost none; its three original allow-paths (`is_allowed`, owner+submitted,
      responsible-supervisor) are untouched, just OR'd with the new fourth path.
      `moderator_report_form` is behaviourally identical (diff confirms only a class/helper-function
      extraction, not a logic change) — admin/root continue to reach it exactly as before, just with
      an added `url=` query param on the AVD dashboard's link to it (a strict improvement: previously
      defaulted to `faculty.dashboard_moderation`, which a non-faculty admin/root account could also
      have 403'd against on Return).
- [x] **No cross-grant between the two roles.** `_can_access_avd_dashboard()` and
      `_can_access_similarity_dashboard()` are both untouched by this phase and don't reference the
      other dashboard's role. The only shared surface, `view_marking_report`, lists both role names
      explicitly (in both the decorator and the `allow_roles` list) rather than via a generic "any
      data-dashboard role" check, so holding one role doesn't imply passing the other's check there
      or anywhere else. `view_moderator_report` accepts only `data_dashboard_reports` — a
      `data_dashboard_similarity`-only user fails both its decorator and its internal gate.

## Risk flag for future maintainers (per the prompt's closing instruction)

`view_marking_report`'s `is_dashboard_viewer` path and the new `view_moderator_report` route both
grant **read-only** access via the dedicated `validate_data_dashboard_access()` — deliberately not
`validate_is_convenor()`, which must continue to mean "is a convenor" everywhere else it's called
(18+ sites in `app/convenor/markingevent.py`). If a future change ever makes
`_can_access_marking_form`'s `is_elevated` or `moderator_report_form`'s `is_editable` derive from
`validate_data_dashboard_access(...)` directly (rather than the current hand-rolled
`is_elevated`/`is_owner` checks), **do not** wire it into a write-capable check — both
`data_dashboard_reports` and `data_dashboard_similarity` are intentionally read-only everywhere in
this app. Explicit code comments to this effect are in place: `validate_data_dashboard_access`'s own
docstring, the inline comment above `is_dashboard_viewer` in `view_marking_report`, and the docstring
of `view_moderator_report`.

---

**Implemented and statically verified.** Approved by the user (Option A for MarkingReport, Option B
— a new GET-only `view_moderator_report` route — for ModeratorReport) before Step 2 began. After the
first implementation pass, the user flagged that reusing `validate_is_convenor`'s `allow_roles`
mechanism conflated "read-only dashboard role" with "is a convenor" — corrected by reverting
`validate_is_convenor` to its original form and adding a standalone `validate_data_dashboard_access()`
instead (see the correction note above Step 1, and the updated Step 2/3 above). No live browser/DB
verification was performed; see Step 3 for the static-trace verification in lieu of that.
