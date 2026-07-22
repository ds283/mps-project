# Reconcile the "New ticket" (compose) view

> Working plan for the compose-view reconciliation task. Written for execution in a fresh context.
> Cross-refs: `PLAN.md` (phase history), `TODO.md` (live board), `reference/` (Claude Design spec).

## Context

The ticket-system compose screen (`tickets/compose.html`, design screens 2b/3b) has landed
functionally but diverges from the polished Claude Design reference in two ways that are real
defects, plus several cosmetic gaps:

1. **Wrong chrome.** Compose extends `base_app.html` directly, so it renders only the top navbar
   with no surface sub-nav/pill context. The ticket *detail* view already solves this: its
   `_detail_template()` (`app/tickets/detail.py:410`) picks a per-surface wrapper
   (`tickets/convenor_detail.html`, `faculty/dashboard/faculty_detail.html`, or bare
   `tickets/detail.html`) from an `origin` query arg. Compose must do the same.
2. **Past students leak into the subject picker.** The faculty supervisee query and the office
   candidate query return `SubmittingStudent` / `SelectingStudent` instances from *retired* prior
   academic cycles. Instances whose `ProjectClassConfig.year < get_current_year()` should be hidden
   by default, with an opt-in "Show past students" toggle.
3. Cosmetic reconciliation with the reference (avatars, subtitles, Cancel button, linked
   breadcrumb, subscriber/routing card styling).

**Decisions taken with the user (2026-07-22):**
- **Keep the unified select2 subject picker** (handles office "any student/class" scope and mixed
  subjects; single-tenant already enforced) and *enrich* its rows — do **not** adopt the
  reference's two-mode segmented control.
- **Full visual reconciliation** (avatars + subtitles on picker rows, subscriber avatar chips,
  routing-card avatars/info tone, Cancel button, linked "Tickets" breadcrumb).
- **Office surface mirrors detail**: convenor + faculty get surface wrappers; office/admin/root
  fall back to bare `base_app` chrome (no office nav base exists — same as detail today).

Outcome: compose renders inside the same surface chrome as detail, never offers stale prior-cycle
students, and matches the reference's visual polish.

## Part 1 — Surface-correct chrome (mirror `_detail_template`)

### Template split (mirror the `_detail_body.html` pattern)
- Extract the current `{% block bodyblock %}` markup of `compose.html` into a new partial
  **`app/templates/tickets/_compose_body.html`**.
- Extract the `import_select2()` + compose `<script>` into
  **`app/templates/tickets/_compose_scripts.html`** (compose needs select2, unlike detail whose
  body is vanilla-JS-only — so wrappers must supply a `scripts` block).
- Rewrite the three wrappers, each identical in shape to `convenor_detail.html`/`faculty_detail.html`:
  ```jinja2
  {% extends "<surface base>" %}
  {% block title %}New ticket{% endblock %}
  {% block bodyblock %}{% include "tickets/_compose_body.html" %}{% endblock %}
  {% block scripts %}{{ super() }}{% include "tickets/_compose_scripts.html" %}{% endblock %}
  ```
  - `app/templates/tickets/compose.html` — extends `base_app.html` (bare / office fallback).
  - `app/templates/tickets/convenor_compose.html` — extends `convenor/dashboard/pclass_base.html`.
  - `app/templates/faculty/dashboard/faculty_compose.html` — extends `faculty/dashboard/nav.html`.

### View wiring (`app/tickets/compose.py`)
- Add a compose-local `_compose_template()` that mirrors `detail._detail_template()` but has **no
  ticket** to scope against:
  - `origin == "convenor"`: resolve `pclass` from `request.args` and confirm `current_user`
    convenes/co-convenes it (a `_origin_pclass_compose()` helper — same entitlement check as
    `detail._origin_pclass` minus the ticket-scope test); build `convenor_data` via
    `get_convenor_dashboard_data(pclass, config)` with `config = pclass.most_recent_config`.
  - `origin == "faculty"` and `current_user.has_role("faculty")`: `pane="tickets"` +
    `get_faculty_dashboard_data(current_user)` (+ `root_dash_data` for root), like detail.
  - else → `("tickets/compose.html", {})`.
- In `compose()`, replace all three `render_template_context("tickets/compose.html", …)` calls
  (GET, invalid-scope re-render, cross-tenant re-render) with
  `template, nav_ctx = _compose_template()` and `render_template_context(template, **nav_ctx, …)`.
- **Thread `origin`/`pclass` through POST → redirect** so chrome persists:
  - Read `origin = request.args.get("origin")` and `pclass_id = request.args.get("pclass", type=int)`.
  - Render the form `action` with those args, and pass them (plus a computed `cancel_url`) into the
    template so the body can build the form action, Cancel button, and breadcrumb link.
  - On success, redirect to `url_for("tickets.detail", ticket_id=ticket.id, origin=origin,
    pclass=pclass_id)` so the detail view lands with matching chrome.

### Entry-point links (thread `origin`)
- `app/templates/convenor/dashboard/tickets.html:28` — add `origin='convenor', pclass=pclass.id`.
- `app/templates/tickets/_inbox.html:44` — this partial is shared by the standalone inbox (bare)
  and the faculty dashboard pane. Add an `origin` param sourced from a `compose_origin` context
  var: set it to `'faculty'` where the faculty pane builds inbox context
  (`app/faculty/views.py:1952 dashboard_tickets` / `app/tickets/dashboard.py:build_inbox_context`),
  and leave it unset (bare) for the standalone `tickets.inbox` page.

## Part 2 — Hide past-cycle students by default

Filter **only the candidate-listing paths**, never `_authorized()` or `_available_tenants()` — a
retired student already attached to an existing ticket must still validate.

- `app/tickets/compose.py`:
  - `_office_candidates` / `_student_results`: add an `include_past=False` param; when false add
    `.filter(ProjectClassConfig.year >= get_current_year())` (the join to `ProjectClassConfig`
    already exists in `_student_results`). Import `get_current_year` from `app/shared/utils.py`.
  - `_faculty_candidates`: for the supervisee rows, join `ProjectClassConfig` on
    `SubmittingStudent.config_id` (as `_available_tenants` already does) and apply the same
    `year >= current_year` filter unless `include_past`. Classes are not year-scoped — leave them.
  - `compose_people`: read `include_past = bool(request.args.get("include_past", type=int))` and
    forward it to the candidate builders.
- Picker UI (`_compose_body.html` + `_compose_scripts.html`): add a small **"Show past students"**
  checkbox beside the subject picker. On change, include `include_past=1` in the select2 `ajax.data`
  (alongside the existing `tenant_id`) and clear current picks + re-query — same mechanism already
  used for the tenant selector. (A checkbox *inside* the select2 dropdown is impractical with a
  remote/ajax data source; an adjacent labelled checkbox is the pragmatic equivalent.)

## Part 3 — Full visual reconciliation

- **Picker rows** (`_compose_scripts.html`): have `compose_people` include `initials`
  (from `user.initials` — never computed ad hoc, per repo rule) and a `subtitle`
  (e.g. "Submitter · <class>", "supervised by you") on each student result; render them with
  select2 `templateResult`/`templateSelection` as an avatar circle (initials) + name + muted
  subtitle. Classes use a `layer-group` icon instead of an avatar.
- **Subscribers card** (`_compose_body.html`): render avatar chips for `current_user` and the
  in-scope convenors (reuse the routing endpoint's convenor set / initials) instead of plain text.
- **Routing card**: adopt the reference's info tone + a small convenor avatar; keep the existing
  single-vs-multi (success/warning) semantics.
- **Cancel button**: add next to "Create ticket", linking to `cancel_url` (convenor →
  `convenor.tickets_tab`, faculty → `faculty.dashboard_tickets`, else `tickets.inbox` — same
  fallback logic as `detail._breadcrumb`).
- **Breadcrumb "Tickets"**: make it a link to the same `cancel_url`/origin target (currently inert).

All colours must use Bootstrap 5.3 / app semantic tokens per `.claude/rules/template-colours.md`
(the current `.tk-*` styles already comply — extend in the same idiom).

## Rejected reference elements (deliberate divergences)
- **Two-mode segmented control** ("A specific student" / "General / whole class"): rejected. The
  unified select2 picker is more capable for office multi-subject/mixed tickets, and single-tenant
  is already enforced server-side. The reference split is student-centric faculty framing.
- **Inline label chips + "+ add"**: rejected — keep select2 for labels (consistent with the app;
  inline label creation was already ruled out, see TODO Labels section).

## Critical files
- `app/tickets/compose.py` — `_compose_template()`, `_origin_pclass_compose()`, `compose()` wiring,
  candidate-query year filter, `compose_people` `include_past`.
- `app/templates/tickets/compose.html` (→ bare wrapper) + new `_compose_body.html`,
  `_compose_scripts.html`, `convenor_compose.html`, `faculty/dashboard/faculty_compose.html`.
- `app/templates/convenor/dashboard/tickets.html`, `app/templates/tickets/_inbox.html` — link origin.
- `app/faculty/views.py` / `app/tickets/dashboard.py` — supply `compose_origin='faculty'`.
- Reuse: `get_convenor_dashboard_data`, `get_faculty_dashboard_data`, `get_root_dashboard_data`,
  `get_current_year`, `User.initials`, existing `_faculty_supervisee_query`/`home_class`.

## Verification
1. `ruff check .` clean on touched files.
2. Run the app (`python serve.py`) and, as a faculty user, open **New ticket** from:
   - the faculty dashboard Tickets pane → confirm faculty pill chrome renders;
   - a convenor ledger (`?origin=convenor&pclass=…`) → confirm convenor pclass chrome
     (breadcrumb, lifecycle chip, pills) renders;
   - the standalone inbox / as office → confirm bare chrome (no crash, office falls back cleanly).
3. Confirm the subject picker shows only current-cycle supervisees/students; tick **Show past
   students** → prior-cycle (retired, `config.year < current_year`) instances appear.
4. Verify an already-attached retired subject still validates on submit (authorization unfiltered).
5. Submit a ticket → lands on detail with the **same** surface chrome (origin/pclass carried).
6. Visual: avatars + subtitles on rows, subscriber avatar chips, Cancel button, linked breadcrumb;
   check light + dark themes.

## Commit
Single phase, committed as `ticket-system: reconcile compose view chrome + scope filter` after
verification (per the per-phase-commit convention). Update `TODO.md` when it lands.
