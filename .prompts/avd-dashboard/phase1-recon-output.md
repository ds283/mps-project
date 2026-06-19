# Phase 1 recon output

Status: investigation complete, no code changes made yet. Verified against
current source on `master` (HEAD `d944fe09`). This is the plan to review
before Step 1 proceeds.

## 1. Every reference to `archive_reports`

```
app/archive/views.py:38     @roles_accepted("root", "admin", "archive_reports")     [reports() decorator]
app/archive/views.py:45-46  session.get("archive_reports_pclass_filter") / read
app/archive/views.py:65     session["archive_reports_pclass_filter"] = ...          [write]
app/archive/views.py:70-71  session.get("archive_reports_year_filter") / read
app/archive/views.py:79     session["archive_reports_year_filter"] = ...            [write]
app/archive/views.py:84-85  session.get("archive_reports_group_filter") / read
app/archive/views.py:104    session["archive_reports_group_filter"] = ...           [write]
app/archive/views.py:198    @roles_accepted("root", "admin", "archive_reports")     [reports_ajax() decorator]

app/shared/context/global_context.py:107  is_archive = "archive_reports" in visible_roles
app/shared/context/global_context.py:108  is_archive_reports = "archive_reports" in visible_roles  (duplicate of 107)
app/shared/context/global_context.py:143  "is_archive_reports": is_archive_reports,   [context dict]

app/models/submissions.py:1927        allowed_roles = ["archive_reports"]            [_check_access_control_groups]
app/models/submissions.py:2039-2041   in_role_acl("archive_reports") / grant_role(...)  [maintenance(), report/processed-report path]
app/models/submissions.py:2079-2081   in_role_acl("archive_reports") / grant_role(...)  [maintenance(), attachment path]

app/templates/base.html:365  {% if is_archive_reports %}   [nav dropdown contents]
```

Not a hit, but related and must be touched at the same time:

- `app/shared/context/global_context.py:142` `"is_archive": is_archive,` — same
  underlying check as `is_archive_reports`, used only to gate the `Archive`
  dropdown wrapper (`base.html:360`). Since the dropdown is going away (see
  §6), both `is_archive` and `is_archive_reports` should be deleted, not
  renamed.
- **`app/shared/context/global_context.py:148-152`, the `can_view_dashboards`
  combined flag** — currently `is_root or is_admin or is_data_dashboard_AI or
  is_data_dashboard_marking or is_data_dashboard_similarity or (convenor
  clause)`. This flag (not `archive_reports`/`is_archive`) gates whether the
  **"Dashboards" nav link itself** renders (`base.html:351`). It does not
  contain `archive_reports` today because report-only users never had a
  Dashboards link — they reached `/archive/reports` straight from the
  `Archive` dropdown. Once that route moves under `/dashboards/avd`, a
  `data_dashboard_reports`-only user has **no way to navigate there** unless
  this flag also gains `is_data_dashboard_reports`. This is not a literal
  `archive_reports` string match, so a grep-only sweep would miss it, but
  it's required for Step 2 (relocate) and Step 4 (gate) to actually work
  end-to-end. I'll add it alongside the `overview()` OR-condition edit.

### Important non-Flask-Security usage found at `app/models/submissions.py`

The three hits in `submissions.py` are **not** `@roles_accepted`/`has_role`
checks — they're object-store ACL grants (`asset.grant_role(...)`,
`asset.in_role_acl(...)`) defined in `app/models/model_mixins.py:1037-1154`.
Tracing them: `_get_role(role: str)` resolves the string via
`db.session.query(Role).filter_by(name=role).first()` and `grant_role`
appends that `Role` row to `asset.access_control_roles` (a join table keyed
on `Role.id`, not `Role.name`). `has_role_access()` later checks
`user.has_role(role)` for each role object in that collection — so it
ultimately is gated by the same Flask-Security role membership, just
reached via a stored FK rather than a decorator string.

**Consequence for the rename**: because the FK is on `Role.id`, renaming
the `Role.name` column value in place (a single `UPDATE roles SET name =
'data_dashboard_reports' WHERE name = 'archive_reports'`) automatically
keeps every existing asset ACL grant and every existing `roles_users`
membership row intact — no join-table data migration needed, just the one
`Role.name` UPDATE. But the **code constant** strings in `submissions.py`
(lines 1927, 2040, 2080) must still be updated to `"data_dashboard_reports"`
— if left as `"archive_reports"` after the Role row is renamed,
`_get_role("archive_reports")` returns `None` (`Role.query.filter_by(...)`
finds nothing), and `grant_role(None)`/`in_role_acl` then silently
no-ops/returns `False` forever — a silent breakage of `maintenance()`'s
access-control consistency check, not a crash. This is the one spot in the
rename where a half-renamed state is actively dangerous, so it's worth
calling out explicitly rather than just "grep and replace."

### Session keys (`archive_reports_pclass_filter` etc.)

These three session keys are **not** role checks, so they're outside the
literal scope of "Step 1 — Role rename." But they're named after the old
route and are being relocated in Step 2, so leaving them as
`archive_reports_pclass_filter` after the route becomes `avd_dashboard`
would be a stale, confusing leftover. I'll rename them to
`avd_dashboard_pclass_filter` / `_year_filter` / `_group_filter` as part of
Step 2 (route relocation), not Step 1. Flagging this now so it isn't missed
as "out of scope" by accident — it's a same-request rename, not a new
feature.

## 2. Every reference to `archive.reports` / `archive.reports_ajax`

```
app/templates/base.html:367              url_for('archive.reports')
app/templates/archive/reports.html:95    url_for('archive.reports', pclass_filter='all', ...)
app/templates/archive/reports.html:100   url_for('archive.reports', pclass_filter=pclass.id, ...)
app/templates/archive/reports.html:119   url_for('archive.reports', pclass_filter=pclass_filter, year_filter='all', ...)
app/templates/archive/reports.html:124   url_for('archive.reports', pclass_filter=pclass_filter, year_filter=year, ...)
app/templates/archive/reports.html:143   url_for('archive.reports', pclass_filter=pclass_filter, year_filter=year_filter, group_filter='all')
app/templates/archive/reports.html:148   url_for('archive.reports', pclass_filter=pclass_filter, year_filter=year_filter, group_filter=group.id)
app/templates/archive/reports.html:36    raw string '/archive/reports_ajax?pclass_filter=...' (NOT a url_for — DataTables ajax.url, built by string concatenation with $SCRIPT_ROOT)
```

No Python file calls `url_for('archive.reports...)` or
`url_for("archive.reports...)`. No test directory references either route
(repo has no test suite for app code — `test_pdf.py` and
`lexical-pipeline-validation/test_language_analysis.py` are unrelated). No
fixture/seed data references these endpoint names.

The `archive/reports.html` raw-string ajax URL is the one place that won't
show up under an `archive.reports_ajax` (dotted endpoint) grep, since it's
a hand-built path string, not a Flask endpoint reference — worth calling
out since the Step 6 verification greps are endpoint-name greps and
wouldn't catch a stray `/archive/reports_ajax` path string if I missed
updating it.

## 3. Exact current `overview()` access-control condition

`app/dashboards/views.py:951-964`, copied verbatim:

```python
    if not (
        current_user.has_role("root")
        or current_user.has_role("admin")
        or current_user.has_role("data_dashboard_AI")
        or current_user.has_role("data_dashboard_marking")
        or current_user.has_role("data_dashboard_similarity")
        or (
            current_user.has_role("faculty")
            and current_user.faculty_data is not None
            and current_user.faculty_data.is_convenor
        )
    ):
        flash("You do not have permission to access the dashboards.", "error")
        return redirect(url_for("home.homepage"))
```

Step 4 edit will add `or current_user.has_role("data_dashboard_reports")`
as a new line in this OR-chain.

## 4. Exact current AI Risk card markup (template for the new AVD card)

`app/templates/dashboards/overview.html:60-100`, copied verbatim:

```jinja2
            {# ---- AI Data Dashboard card ---- #}
            {% if is_root or is_admin or is_data_dashboard_AI or is_convenor %}
            {% call(slot) dashboard_card(
                icon_class="fas fa-robot fa-2x text-primary",
                icon_bg_style="background-color: var(--db-blue-50);",
                title="AI Risk Dashboard",
                description="Lexical diversity metrics, LLM-assessed grade bands, and AI risk indicators for submitted reports. Distributions across cohorts and academic cycles.",
                open_url=url_for('dashboards.ai_dashboard'),
                open_label="Open dashboard",
                open_btn_class="btn-db-blue"
            ) %}
                {% if slot == 'badges' %}
                    {% if summary.n_tenants > 1 %}
                        <span class="badge bg-secondary">
                            <i class="fas fa-building me-1"></i>{{ summary.n_tenants }} tenants
                        </span>
                    {% endif %}
                    {% if summary.n_pclasses > 1 %}
                        <span class="badge bg-secondary">
                            <i class="fas fa-graduation-cap me-1"></i>{{ summary.n_pclasses }} project classes
                        </span>
                    {% elif summary.n_pclasses == 1 %}
                        <span class="badge bg-secondary">
                            <i class="fas fa-graduation-cap me-1"></i>1 project class
                        </span>
                    {% endif %}
                    {% if summary.n_cycles > 1 %}
                        <span class="badge bg-secondary">
                            <i class="fas fa-calendar-alt me-1"></i>{{ summary.n_cycles }} cycles
                        </span>
                    {% elif summary.n_cycles == 1 %}
                        <span class="badge bg-secondary">
                            <i class="fas fa-calendar-alt me-1"></i>1 cycle
                        </span>
                    {% endif %}
                    {% if summary.n_cycles == 0 %}
                        <span class="badge bg-secondary text-body-secondary">No data available</span>
                    {% endif %}
                {% endif %}
            {% endcall %}
            {% endif %}
```

The shared `dashboard_card` macro (lines 21-45) takes `icon_class`,
`icon_bg_style`, `title`, `description`, `open_url`, `open_label`,
`open_btn_class`, and a `badges` caller-slot. The new AVD card will call
this same macro — no macro changes needed, just a fourth `{% if %}` block
following the same shape, gated on
`is_root or is_admin or is_data_dashboard_reports`.

**Confirmed independent gating** (resolves the open question in
`recon.md` §3 / Decision 3): each of the three existing cards already has
its own `{% if %}` gate (AI: line 61, Similarity: line 103, Marking: line

133) — none of them is gated only by the page-level `overview()` check.
     A `data_dashboard_reports`-only user reaching `overview()` would see *none*
     of the three existing cards today, because none of their gates include
     `data_dashboard_reports`. So there is **no pre-existing gap to flag** —
     adding a fourth, independently-gated card is sufficient and consistent
     with how the others already behave.

## 5. `_get_accessible_tenants` / `_get_default_tenant_id` reusability

Both are plain module-level functions in `app/dashboards/views.py:203-217`,
no closures, no decoration:

```python
def _get_accessible_tenants() -> List[Tenant]:
    if current_user.has_role("root"):
        return db.session.query(Tenant).order_by(Tenant.name).all()
    return current_user.tenants.order_by(Tenant.name).all()


def _get_default_tenant_id(accessible_tenants: List[Tenant]) -> int:
    user_first = current_user.tenants.order_by(Tenant.name).first()
    if user_first is not None:
        return user_first.id
    return accessible_tenants[0].id
```

**Decision: keep `avd_dashboard()` / `avd_dashboard_ajax()` directly in
`app/dashboards/views.py`**, not a new sibling module. Reasoning:

- They're called identically and un-exported from `ai_dashboard()`,
  `marking_dashboard()`, `similarity_dashboard()`, all of which already
  live in this same 3623-line file — there's no existing precedent in this
  codebase for splitting a dashboard's view function out into its own
  module while still calling back into shared private helpers in
  `views.py`. Doing that would require either exporting the `_`-prefixed
  helpers (breaking the "private to this module" naming convention) or
  duplicating them.
- The file's existing organisation interleaves a dashboard's own
  access-control helpers immediately before its route (see
  `_can_access_similarity_dashboard()` at line 2585, immediately before
  `similarity_dashboard()` at line 2856). I'll follow the same placement:
  new `_can_access_avd_dashboard()`, `_get_accessible_pclasses_for_avd()`,
  `_avd_dashboard_summary_for_user()` placed immediately before
  `avd_dashboard()`/`avd_dashboard_ajax()`, inserted after the Marking
  dashboard's last route (`export_marking_excel`, ends ~line 2584) and
  before the Similarity dashboard's helpers — keeping each dashboard's
  helpers+routes grouped together, matching the Marking/Similarity
  precedent rather than the earlier AI-dashboard section (which has its
  helpers front-loaded near the top of the file, an older/less consistent
  layout).

## 6. Collision check: does `data_dashboard_reports` already exist?

No. `grep -rn "data_dashboard_reports"` (excluding `.prompts/`) returns
nothing anywhere in the codebase today. The three existing dashboard roles
(`data_dashboard_AI`, `data_dashboard_marking`, `data_dashboard_similarity`)
are seeded idempotently via `_REQUIRED_ROLES` / `ensure_roles()` in
`initdb.py:453-505`, called on every app startup — **not** via an Alembic
migration. `archive_reports` itself is **not** in `_REQUIRED_ROLES` and
**not** created by any existing migration (`grep -rn "archive_reports"
migrations/` returns nothing) — it must have been created ad hoc through
the generic role-management UI (`app/manage_users/`), which manages
arbitrary `Role` rows rather than a hardcoded role list.

**Plan for Step 1**, given this:

1. Add a `data_dashboard_reports` entry to `_REQUIRED_ROLES` in
   `initdb.py`, matching the existing three entries' shape (`name`,
   `description`, `colour`) — so any fresh install (or any install that
   never had `archive_reports`) gets the role created automatically going
   forward.
2. Write a hand-crafted Alembic migration (down_revision
   `b7c8d9e0f1a2`, the current chain tip — confirmed via the `comm -23`
   command from `CLAUDE.md`, single line, chain not forked) whose `upgrade()`
   does exactly:
   ```python
   op.execute("UPDATE roles SET name = 'data_dashboard_reports' WHERE name = 'archive_reports'")
   ```
   and `downgrade()` reverses it. This single `UPDATE` is sufficient — see
   §1's tracing of `grant_role`/`in_role_acl`: because both `roles_users`
   (Flask-Security role membership) and the asset-ACL join table key on
   `Role.id`, renaming `Role.name` in place carries every existing holder
   and every existing asset grant across automatically. No need to touch
   either join table directly, and no need for a separate "re-grant"
   step.
    - Open question for review: should the migration also update
      `description`/`colour` to match the `_REQUIRED_ROLES` convention
      (e.g. a teal-ish colour consistent with the new dashboard's `--db-teal-*`
      token, parallel to how `data_dashboard_marking` is `#2d8a4e` green and
      `data_dashboard_similarity` is `#c05810` orange)? I'd recommend yes,
      for UI consistency in the admin role list, but it's cosmetic and easy
      to drop if you'd rather keep the migration to the bare rename.
    - If the `archive_reports` role row doesn't exist on a given install
      (e.g. fresh DB), the `UPDATE` simply affects 0 rows — harmless, and
      `ensure_roles()` will create `data_dashboard_reports` fresh on next
      startup per point 1. No special-casing needed in the migration.

## Step 2 implementation notes (route relocation specifics)

Confirmed by reading `app/dashboards/views.py`'s import block
(lines 11-78): `db`, `func`, `request`, `current_user`, `roles_accepted`,
`render_template_context`, `ProjectClass`, `ProjectClassConfig`,
`SubmissionRecord`, `SubmittingStudent`, `Tenant`, `ServerSideSQLHandler`
are already imported. Missing and needed when the route body moves over:

- `session` from `flask` (not currently imported in this file)
- `is_integer` from `..shared.conversions`
- `DegreeProgramme`, `ResearchGroup`, `LiveProject` from `..models`
- `retired_reports` from `..ajax.archive` (the original code does
  `import app.ajax as ajax` then calls `ajax.archive.retired_reports`; I'll
  use a direct `from ..ajax.archive import retired_reports` instead, for
  consistency with this file's existing relative-import style — purely a
  style choice, not a behaviour change, flagging in case you'd rather match
  the old file's import style exactly)
- **`User` aliasing gotcha**: `dashboards/views.py` already imports
  `from ..models.users import User as UserModel` (it needs the alias
  because something else in the file likely shadows `User`, or just by
  established convention — either way, the existing file never uses a bare
  `User` name). The moved `reports_ajax()` body references bare `User`
  (`User.first_name`, `User.last_name`, `User.id`) — these need rewriting
  to `UserModel` to match the file's existing convention, not a second,
  conflicting `User` import.

## Step 3 implementation notes (tenant scoping specifics)

- Original `reports()`'s pclass/year/group queries use three explicit
  conditions for pclass eligibility (`ProjectClass.active.is_(True)`,
  `.publish.is_(True)`, `.uses_submission.is_(True)`) — this is a
  *different* predicate from `_get_accessible_pclasses()`'s
  `_pclass_has_reports_subq()` (which additionally requires at least one
  uploaded report). Recon's "same shape as `_get_accessible_pclasses`"
  reads to me as "same access-control branching shape" (root/admin/role
  see everything in-tenant, no convenor branch) rather than "reuse the
  exact same eligibility predicate". **I plan to keep the original
  active+publish+uses_submission predicate**, not switch to the
  has-a-report predicate, since changing AVD's pclass-list semantics isn't
  asked for anywhere in the brief. Flagging this explicitly since it's a
  judgement call between two plausible readings.
- Because every caller of the new `_get_accessible_pclasses_for_avd(tenant_id)`
  /  `_get_accessible_years_for_avd(tenant_id)` / `_get_accessible_research_groups_for_avd(tenant_id)`
  helpers is already gated by `_can_access_avd_dashboard()` (root/admin/
  `data_dashboard_reports` only — no convenor path at all), there's no
  role branching left to do *inside* these helpers — they become flat,
  unconditional tenant-scoped queries. This is a simplification versus
  `_get_accessible_pclasses()` (which still branches for convenors) and
  versus the original `reports()` (which branched on `has_role("root")`
  to decide "all tenants" vs "my tenants" — that branch disappears because
  *everyone*, root included, now picks one tenant from the same selector).
- `avd_dashboard_ajax()`'s `tenant_id` request-arg handling will mirror
  `similarity_concerns_ajax()`'s exact pattern (`app/dashboards/views.py:3004`):
  ```python
  try:
      tenant_id = int(request.args.get("tenant_id", 0)) or None
  except (ValueError, TypeError):
      tenant_id = None
  ```
  then an unconditional `base_query.filter(ProjectClass.tenant_id == tenant_id)`
  (replacing today's `if not current_user.has_role("root"): filter(.in_(allowed_tenant_ids))`).

## Step 5 implementation notes (template / colour specifics)

- `common.css` (`app/static/css/common.css:18-49`) currently defines four
  ramps: `--db-blue-*` (AI), `--db-green-*` (Marking), `--db-purple-*`
  (AI-generated-content provenance, **not** a dashboard ramp — used by
  `.badge-ai-generated` only), `--db-orange-*` (Similarity). I'll add a
  fifth, `--db-teal-*`, with all six stops (50/100/200/400/600/800)
  following the existing hex-ramp style, plus `.btn-db-teal` /
  `.btn-db-teal:hover` mirroring `.btn-db-blue`/`.btn-db-green`/`.btn-db-orange`
  (lines 73-107).
- Note: `.claude/rules/dashboard-colours.md` itself is already stale — it
  documents only the blue/green ramps and doesn't mention orange/purple,
  which already exist in `common.css` and are already used in
  `overview.html`. Updating that rules file to also document teal (and
  backfilling orange, while I'm there) seems in scope for "no hardcoded hex
  values... reference the new named tokens" — flagging since the brief
  doesn't explicitly mention the rules file, but leaving it silently more
  stale didn't feel right either. Will keep this edit small (append a teal
  section, fix the missing orange one) unless you'd rather I leave the
  rules file alone this phase.
- New `_avd_dashboard_summary_for_user()` will follow `_marking_summary_for_user()`'s
  shape exactly (`app/dashboards/views.py:672-675`) — a small dict of cheap
  counts. Per the brief, I'll keep this to a tenant count and an eligible
  (active+publish+uses_submission) submitted-report count via a plain
  `SubmissionRecord` count query — no `openday_consent_active` aggregate in
  this phase (that's explicitly deferred to Phase 3 per the brief).

## Step 2 template relocation question (not explicitly settled by the brief)

The brief says "no template changes beyond the minimum needed to keep the
app working" and separately "do not touch `archive/reports.html`'s table
markup." It doesn't say whether the *file* should physically move. Two
options:

1. **Move** `app/templates/archive/reports.html` →
   `app/templates/dashboards/avd_dashboard.html`, updating only
   `render_template_context(...)`'s template-path argument, the raw ajax
   URL (→ `url_for('dashboards.avd_dashboard_ajax', tenant_id=..., ...)`,
   matching the `similarity_dashboard.html` pattern at
   `app/templates/dashboards/similarity_dashboard.html:86-103` rather than
   today's raw string concatenation), the `url_for('archive.reports', ...)`
   calls (→ `url_for('dashboards.avd_dashboard', ...)`), and adding the
   tenant filter button row. Table markup/columns/row-rendering left
   untouched.
2. **Leave the file in place** at `app/templates/archive/reports.html` and
   make the same string edits in place, even though `app/archive/` (the
   Python package) is being deleted. Templates aren't tied to a blueprint's
   package location unless a blueprint sets `template_folder` (this one
   doesn't), so this would technically keep working, just with a
   confusingly-named template path left behind after its blueprint is gone.

**Recommend option 1** (move it) — it's still a one-`mv`-plus-string-edits
change, not a markup rewrite, and avoids leaving a `templates/archive/`
directory with no corresponding `app/archive/` package once Step 2 is
done. Flagging because it's a slight extension of "don't touch the table
markup" into "do relocate the file," and I want that read before I do it.

## Tenant-selector UI shape for the relocated template

`archive/reports.html`'s existing pclass/year/group filters are `<a href>`
pill-ish buttons using the *old* `btn-sm btn-primary` / `btn-outline-secondary`
pattern (predating `.claude/rules/template-ui-patterns.md`'s newer
pill-button convention). Per that rule, "existing templates...do not need
immediate conversion; convert opportunistically when a template is touched
for another reason" — since this phase is explicitly Python/routing-only
plus minimum template upkeep, **I will add the tenant filter using the same
existing `btn-sm btn-primary`/`btn-outline-secondary` button style already
in this template**, not convert the whole filter row to the newer pill
pattern, and not adopt the `<form><select onchange="this.form.submit()">`
pattern used by `similarity_dashboard.html`. Full button-style modernisation
(if wanted) is a separate, later cleanup, not bundled into this move.

## Out-of-scope confirmation

`app/ajax/archive/` (containing `reports.py`'s `retired_reports` row
formatter, and `marking_events.py`, used by `app/convenor/markingevent.py`
via `from ..ajax.archive.marking_events import (...)`) is a **separate**
package from the `app.archive` Flask blueprint being removed — confirmed
it has no relation to the `archive` blueprint beyond sharing a directory
name, and `marking_events.py` is actively used elsewhere, so nothing under
`app/ajax/archive/` is touched in this phase, consistent with the brief.
`app/tasks/cloud_api_audit.py` and `app/tasks/backup.py`'s `archive.add()`/
`archive.close()` hits are unrelated stdlib `tarfile`/`zipfile` objects,
not the blueprint.

## Summary of planned file changes

1. `initdb.py` — add `data_dashboard_reports` to `_REQUIRED_ROLES`.
2. New migration (down_revision `b7c8d9e0f1a2`) — rename the `Role` row.
3. `app/dashboards/views.py` — add `_can_access_avd_dashboard()`,
   `_get_accessible_pclasses_for_avd()`, `_get_accessible_years_for_avd()`,
   `_get_accessible_research_groups_for_avd()`, `_avd_dashboard_summary_for_user()`,
   `avd_dashboard()`, `avd_dashboard_ajax()`; extend `overview()`'s OR-chain
   and its call to `_avd_dashboard_summary_for_user()`.
4. `app/archive/views.py` — delete `reports()`/`reports_ajax()` (file
   becomes empty; delete the file and the package).
5. `app/__init__.py` — remove the `archive` blueprint registration
   (lines 571, 573).
6. `app/templates/archive/reports.html` → moved to
   `app/templates/dashboards/avd_dashboard.html` with the string/URL edits
   and tenant filter button row described above.
7. `app/templates/dashboards/overview.html` — add the fourth AVD card.
8. `app/static/css/common.css` — add `--db-teal-*` tokens + `.btn-db-teal`.
9. `.claude/rules/dashboard-colours.md` — append teal (and backfill
   orange) documentation.
10. `app/shared/context/global_context.py` — remove `is_archive`/
    `is_archive_reports`; add `is_data_dashboard_reports`; add it to
    `can_view_dashboards`.
11. `app/templates/base.html` — remove the `Archive` nav dropdown
    (lines 360-373); no other base.html changes needed.
12. `app/models/submissions.py` — rename the three `"archive_reports"`
    string constants to `"data_dashboard_reports"`.

Open points where I made a judgement call rather than finding an explicit
instruction (flagging per your "stop and review" instruction rather than
silently picking one):

- Migration also updates `description`/`colour`, or bare rename only?
- Physically move the template file (recommended) vs. edit in place?
- Update the stale `dashboard-colours.md` rules file to also cover
  orange/teal, or leave it untouched this phase?
- Rename the three `archive_reports_*_filter` session keys to
  `avd_dashboard_*_filter` (recommended, bundled into Step 2) vs. leave
  them named after the old route?

Ready to proceed to Step 1 on your go-ahead, or adjust per your answers to
the above.
