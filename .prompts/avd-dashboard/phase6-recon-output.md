# Phase 6 — AVD dashboard visual polish: Recon output

## Step 0.1 — `metric_tile()` macro

**Location:** `app/templates/convenor/dashboard/overview_cards/_metric_tile.html`

**Signature:**
```jinja2
{% macro metric_tile(value, label, variant='secondary', denominator=none,
                     zero_variant=none, nonzero_variant=none, value_ok=none) %}
```

Renders a small rounded tile with a value (bold), optional denominator, and a label (10px muted text
below). Variant `'secondary'` uses `var(--bs-secondary-bg)` / `var(--bs-border-color)` tokens (the
non-subtle pair); other variants use `var(--bs-{variant}-bg-subtle)` / `var(--bs-{variant}-border-subtle)`.

**Import pattern used in file templates:**
```jinja2
{% from "convenor/dashboard/overview_cards/_metric_tile.html" import metric_tile %}
```

**For the inline string template in `reports.py`:** The `_details` string template is compiled with
`env.from_string(_details)` using the same Jinja2 environment as the rest of the app. The environment
has the app's template loader set up, so `{% from "convenor/dashboard/overview_cards/_metric_tile.html"
import metric_tile %}` at the top of the `_details` string should work. This is the approach used (no
need to inline the macro body).

## Step 0.2 — Current template/function inventory

**`_report` string** (`reports.py:27`): Jinja2 macros defined:
- `turnitin_chips(r)` — renders Turnitin score badge
- `identity_line(parts)` — renders the muted metadata dot-separated line
- `consent_badges(record)` — renders AVD / exemplar consent pills
- `flags_line(record, convenor_intervention, out_of_tolerance_unassigned, ai_risk)` — renders flag badges
- `staff_roles(roles, moderator_role_id, moderation_outcome)` — renders staff role groups

Main template body: thumbnail | content-column (student name + project, identity line, consent badges,
flags, staff roles, expand trigger link).

**`_details` string** (`reports.py:268`): Jinja2 macros defined:
- `stat_chip(label, value)` — renders a label+value pair (being replaced by `metric_tile`)

Main template body (2-col layout):
- Left col: report stats (stat_chip calls), stated-word-count+discrepancy, AI declaration, report summary
- Right col: risk factors, marking/moderation report links, feedback document links

**`_details_context(record, roles)`** (`reports.py:537`): Python function building the template context
dict. Extracts metrics, AI declaration, report summary, risk factors, role report links, feedback links.
Passes `rf` (full risk factor dict from `risk_factors_ui_summary()`), `role_reports` (list of dicts),
and `feedback_links` (list of dicts).

## Step 0.3 — ROLE_* constants and `role_as_str`

`SubmissionRoleTypesMixin` in `app/models/model_mixins.py:1527`:
```
ROLE_SUPERVISOR           = 0  → _role_string: "Supervisor"
ROLE_MARKER               = 1  → "Marker"
ROLE_PRESENTATION_ASSESSOR= 2  → "Assessor"   ← the short label
ROLE_MODERATOR            = 3  → "Moderator"
ROLE_EXAM_BOARD           = 4  → "Exam board"
ROLE_EXTERNAL_EXAMINER    = 5  → "External"
ROLE_RESPONSIBLE_SUPERVISOR=6  → "Responsible supervisor"
```

`role_as_str` is a `@property` on `SubmissionRole`, `MatchingRole`, etc. (defined in multiple
models) — it returns `_role_string[self.role]`.

**Relabel decision: LOCAL override in AVD dashboard template only.**

`role_as_str` with the short "Assessor" label is used in ≥15 templates across faculty, convenor,
projecthub, and task-log contexts (`faculty/marking_form.html`, `faculty/view_marking_report.html`,
`convenor/markingevent/*`, `projecthub/event/*`, `similarity_concern_detail.html`, tasks, etc.).
Changing `_role_string[ROLE_PRESENTATION_ASSESSOR]` to "Presentation assessor" globally would rename
it everywhere — broader than this phase intends. The AVD dashboard will apply a `_local_labels` dict
override in the `staff_roles` macro only: `{2: 'Presentation assessor'}` (key is the integer constant).
`role_as_str` is NOT changed globally.

Confirmed: `grep -n "role_as_str"` returns no hit in `avd_dashboard.html` or `reports.py`
template body (only used in `_role_report_links` which returns dicts, not template access).

## Step 0.4 — `risk_factors_ui_summary()` factor keys and labels

Exact labels from `SubmissionRecord.RISK_FACTOR_LABELS` (`submissions.py:2238`):
```
RISK_AI_COMPLIANCE        = "ai_compliance"       → "AI compliance statement"
RISK_AI_USE               = "ai_use"              → "AI use metrics"
RISK_WORD_COUNT_DISCREPANCY = "word_count_discrepancy" → "Word count discrepancy"
```
(Additional types: `RISK_TURNITIN`, `RISK_DOCUMENT_LENGTH`, `RISK_SIMILARITY`, `RISK_CHUNK_FAILURE` — all
remain in the right-hand risk factors column unchanged.)

**AI compliance ↔ declaration relationship (confirmed):**
`RISK_AI_COMPLIANCE` is set present only when `genai_statement_found == True`
(`submissions.py:2640–2649`). `genai_status` in `_details_context()` is also set from the same
`genai_statement_found` flag. They are perfectly correlated: a compliance factor is present iff a
declaration was detected. No inconsistency to code around.

One subtlety: `genai_status` is suppressed when `restricted=True` (content embargo), but
`RISK_AI_COMPLIANCE` is not suppressed in `risk_factors_ui_summary()`. The template will gate the
AI declaration section with `{% if not restricted and genai_status is not none %}`, and the compliance
factor display will be nested inside that — so a restricted record won't show either the declaration
or the attached compliance verdict in the UI (the risk factor card moves to the right column where it
can still show without the declaration text). This matches the existing design intent.

## Step 0.5 — Current filter-bar structure

Seven sections in `avd_dashboard.html`, in order:
1. Tenant filter — conditional (`accessible_tenants|length > 1`)
2. Project class filter — conditional (`pclasses|length > 0`)
3. Academic year filter — conditional (`years|length > 0`)
4. Research group filter — conditional (`groups|length > 0`)
5. Report grade filter — always present
6. AVD consent filter — always present (4 buttons: Any/Active/Withdrawn/Not requested)
7. Exemplar consent filter — always present (4 buttons: Any/Active/Withdrawn/Not requested)

Sections 6 and 7 are currently two separate rows each with their own `<p class="mb-1">` heading and
`d-flex` button group, separated by an `<hr class="intro-divider">`. Step 5 merges them under one
"Filter by consent" heading with two adjacent labelled button groups ("AVD:" and "Exemplar:").

## Implementation plan

### Python changes (`reports.py`)

- **New helper `_role_report_url_map(roles)`**: returns `Dict[int, str]` mapping `SubmissionRole.id →
  report URL`. Same logic as `_role_report_links()` but dict-keyed — for use in the `_report` template.
  Old `_role_report_links()` is removed (its caller in `_details_context` is replaced).

- **New helper `_group_and_sort_roles(roles)`**: groups roles by type, then sorts by a priority dict:
  `{ROLE_RESPONSIBLE_SUPERVISOR: 0, ROLE_SUPERVISOR: 1, ROLE_MARKER: 2, ROLE_PRESENTATION_ASSESSOR: 3,
  ROLE_MODERATOR: 4}` with unknown types defaulting to priority 5 (sort after named types). Returns
  `List[Tuple[int, List[SubmissionRole]]]`.

- **`_details_context()` changes**:
  - Split `rf["factors"]` into `ai_compliance_factor` (RISK_AI_COMPLIANCE factor dict or None) and
    `other_rf_factors` (all other factors).
  - Pass both to the context separately.
  - Remove `role_reports` from the context (list is removed; links are now in the staff-roles block).
  - Update `has_details` to remove `role_reports` from its condition.

- **`avd_dashboard_rows()` changes**:
  - Call `_group_and_sort_roles(roles)` → `grouped_roles`; call `_role_report_url_map(roles)` → `role_report_urls`
  - Pass both to `_report` template, replacing the old `roles` variable
  - `_details_context()` now only needs `record` (roles used for feedback links, not role_reports)
    Actually: keep roles param for feedback_links continuity; just don't build role_reports inside.

### Template string changes

**`_report`:**
- `staff_roles` macro: signature changes to `(grouped_roles, role_report_urls, moderator_role_id,
  moderation_outcome)`. Iterates pre-sorted `grouped_roles` directly (no Jinja2 `|groupby`). Uses
  `_local_labels` dict `{2: 'Presentation assessor'}` for role-type label lookup. Names rendered as
  `<a href="...">` if URL present in `role_report_urls`, else plain text. Wrapped in visual container
  (small-caps "Staff" label, `var(--bs-tertiary-bg)` background, rounded border).
- Expand trigger: old `<a href="...">Show full details</a>` replaced by a full-width footer bar
  `<div class="avd-details-toggle avd-footer-toggle">` inside the `bg-light` content column, below
  all content, with `border-top: 1px solid var(--bs-border-color)` separator and centered
  icon+label.

**`_details`:**
- Add `{% from "convenor/dashboard/overview_cards/_metric_tile.html" import metric_tile %}` at top.
- New top section: `report_summary` callout (info-tinted border, "AI report summary" label + icon,
  prose text) — above the 2-col layout.
- Left col: 4 `metric_tile()` calls (measured words, pages, figures, tables), `variant='secondary'`.
  Appendix word count as small supplementary text below tiles. Stated word count + discrepancy badge
  unchanged. AI declaration box: neutral style (`var(--bs-secondary-bg)` background, `fa-info-circle`
  icon, no warning colour). AI compliance factor attached beneath it (internal `<hr>`, resolved/
  unresolved styling matching risk-factor card layout) — gated on `not restricted and genai_status`.
- Right col: `other_rf_factors` only (RISK_AI_COMPLIANCE removed). Remaining risk factors as bounded
  cards (factor name + icon header, resolver/date muted line, annotation below). Feedback document
  links unchanged. `role_reports` list **removed**.

### Filter bar changes (`avd_dashboard.html`)

Sections 6 and 7 merged under one "Filter by consent" heading with two inline groups:
```
Filter by consent
  AVD: [Any] [Active] [Withdrawn] [Not requested]    Exemplar: [Any] [Active] [Withdrawn] [Not requested]
```
HR separator before the merged section; no HR between AVD and exemplar groups.

### JS changes (`avd_dashboard.html`)

Update the `.avd-details-toggle` click handler to update the footer bar's `.avd-toggle-icon` and
`.avd-toggle-label` spans instead of the old `toggles.filter('a')` approach. The AI-flagged badge
and note icon remain `<span>/<i>` elements and are not updated (they have no label text to flip).
