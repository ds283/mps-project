# Phase 3 recon output — consent badges and filters

## 1. Consent field names and semantics (`app/models/submissions.py`, `SubmissionRecord`)

Copied verbatim from the model (lines 855–893, properties at 1136–1158):

```python
# --- Exemplar consent ---
exemplar_consent_granted_at = db.Column(db.DateTime(), default=None, nullable=True)
exemplar_consent_withdrawn = db.Column(db.Boolean(), default=False, nullable=False)
exemplar_consent_withdrawn_at = db.Column(db.DateTime(), default=None, nullable=True)
exemplar_supervisor_approved = db.Column(db.Boolean(), default=None, nullable=True)
exemplar_supervisor_actioned_at = db.Column(db.DateTime(), default=None, nullable=True)

# --- Open day consent --- (parallel structure; no supervisor approval step)
openday_consent_granted_at = db.Column(db.DateTime(), default=None, nullable=True)
openday_consent_withdrawn = db.Column(db.Boolean(), default=False, nullable=False)
openday_consent_withdrawn_at = db.Column(db.DateTime(), default=None, nullable=True)

# --- Invitation tracking ---
consent_invitation_sent_at = db.Column(db.DateTime(), default=None, nullable=True)
consent_reminder_sent_at = db.Column(db.DateTime(), default=None, nullable=True)

@property
def exemplar_consent_active(self) -> bool:
    return self.exemplar_consent_granted_at is not None and not self.exemplar_consent_withdrawn

@property
def openday_consent_active(self) -> bool:
    return self.openday_consent_granted_at is not None and not self.openday_consent_withdrawn

@property
def exemplar_fully_approved(self) -> bool:
    return self.exemplar_consent_active and self.exemplar_supervisor_approved is True
```

`exemplar_supervisor_approved` is confirmed tri-state from its own column comment: "None = not
yet actioned (or not yet requested because student has never consented). True = approved.
False = declined." Not reset on withdraw/re-grant cycles.

**`consent_invitation_sent_at` / `consent_reminder_sent_at` are genuinely shared, single-flow
fields** — there is only one pair of columns, no per-type split, and the column comment confirms
this is intentional ("the convenor UI uses this to distinguish 'eligible but uninvited' from
'invited, awaiting response'" — written generically, not per consent type). This is also how
the existing convenor UI already consumes it (see §2 below): the same `r.consent_invitation_sent_at`
value drives the "invited" state for *both* the exemplar badge and the open-day badge
independently. So Phase 1/2 did not introduce a split — Phase 3 should keep using the single
shared field for both badge clusters, exactly as `submitters_v2.html` already does.

## 2. Existing convenor consent UI (`app/templates/convenor/dashboard/submitters_v2.html`)

Established badge convention (`.sv2-cbadge` + state modifier classes, lines 166–178):

```css
.sv2-cbadge { display: inline-flex; ...; padding: 1px 6px; border-radius: 20px; font-weight: 500; }
.sv2-cb-uninvited { background: var(--bs-secondary-bg); color: var(--bs-secondary-color); border: 1px solid var(--bs-border-color); }
.sv2-cb-invited   { background: var(--bs-secondary-bg); color: var(--bs-secondary-color); border: 1px dashed var(--bs-border-color); }
.sv2-cb-pending   { background: var(--bs-warning-bg-subtle); color: var(--bs-warning-text-emphasis); border: 1px solid var(--bs-warning-border-subtle); }
.sv2-cb-approved  { background: var(--bs-success-bg-subtle); color: var(--bs-success-text-emphasis); border: 1px solid var(--bs-success-border-subtle); }
.sv2-cb-declined  { background: var(--bs-secondary-bg); color: var(--bs-secondary-color); border: 1px solid var(--bs-border-color); }
.sv2-cb-withdrawn { background: var(--bs-secondary-bg); color: var(--bs-secondary-color); border: 1px solid var(--bs-border-color); text-decoration: line-through; }
```

Key difference from this phase's brief, **deliberately not copied wholesale**: `submitters_v2`
always renders a badge for both consent types on every eligible record, including explicit
"not invited" / "uninvited" pills — there is no silent default state. Per `recon.md` §10 and
this phase's brief, the AVD dashboard wants the opposite for the never-asked case: **no badge at
all**, and a single dominant solid pill only for the *active* AVD/open-day state (the other three
sv2 states — uninvited/invited/declined/withdrawn — collapse to muted text or nothing here).
Wording style and the four-state shape (never-asked / invited / active / withdrawn, plus the
tri-state supervisor wording "approved"/"declined"/"pending" used at submitters_v2.html:988,993,998)
are reused; the always-visible-pill visual treatment is not.

## 3. Teal token ramp (`app/static/css/common.css`, confirmed present from Phase 1)

```css
--db-teal-50: #E6F5F4;
--db-teal-100: #B8E2DF;
--db-teal-200: #8ACECA;
--db-teal-400: #2EA39C;
--db-teal-600: #1A8A8A;
--db-teal-800: #0F5252;
```

`.btn-db-teal` already exists (background `--db-teal-400`, hardcoded `#fff` text, border
`--db-teal-600`) but no badge/pill class exists yet for this ramp. Added a new
`.badge-db-teal` class (background `--db-teal-400`, text `var(--bs-white)` per
`template-colours.md`'s allowed-token list) for the solid AVD pill — reuses the ramp's existing
"400 = interactive/button" stop convention from `dashboard-colours.md` rather than inventing a
new stop usage.

## 4. Current row template block (`app/ajax/archive/reports.py`, `_report`, before this phase)

Verbatim identity-line block this phase's edit is additive to (lines 136–164 before edit):

```jinja2
<div class="flex-grow-1 bg-light p-2 rounded">
    <div class="d-flex flex-row justify-content-between align-items-start gap-2">
        <div class="flex-grow-1">
            <div class="d-flex flex-row flex-swap justify-content-start align-items-baseline gap-2">
                {% if record.project is not none %}
                    <div class="fw-semibold small">{{ record.project.name }}</div>
                    {% if record.project.group is not none %}
                        <div class="mt-1">{{ simple_label(record.project.group.make_label()) }}</div>
                    {% endif %}
                {% else %}
                    <div class="small text-muted fst-italic">No project assigned</div>
                {% endif %}
                {% if period is not none %}
                    <div class="small text-muted">{{ period.display_name }}</div>
                {% endif %}
            </div>

            {# Supervision / presentation grades #}
            {% if supervision_grade is not none or presentation_grade is not none %}
                <div class="small text-muted mt-1"> ... </div>
            {% endif %}

            {# Roles #}
            ...
            {# Turnitin data #}
            {{ turnitin_info(record) }}
        </div>
        ...
```

Consent badges are inserted as a new block immediately after the identity-line `</div>` and
before the supervision/presentation grades block, matching `recon.md` §10's stated row order
(identity line → consent badges → flags/roles/turnitin). No other part of the template is
restructured.

## 5. Badge-state derivation — single source of truth

Per `recon.md` §10's closing instruction ("the badge-state decision should be made once"), added
two small helper properties on `SubmissionRecord` (`app/models/submissions.py`, immediately after
`exemplar_fully_approved`) rather than re-deriving the four-state logic inline in the template:

```python
@property
def openday_consent_badge_state(self) -> Optional[str]:
    """One of 'active' / 'invited' / 'withdrawn', or None if open day consent has
    never been requested (no invitation sent, no consent ever granted)."""
    if self.openday_consent_active:
        return "active"
    if self.openday_consent_granted_at is not None and self.openday_consent_withdrawn:
        return "withdrawn"
    if self.consent_invitation_sent_at is not None:
        return "invited"
    return None

@property
def exemplar_consent_badge_state(self) -> Optional[str]:
    """Same shape as openday_consent_badge_state, for exemplar consent."""
    if self.exemplar_consent_active:
        return "active"
    if self.exemplar_consent_granted_at is not None and self.exemplar_consent_withdrawn:
        return "withdrawn"
    if self.consent_invitation_sent_at is not None:
        return "invited"
    return None
```

These four states are mutually exclusive and exhaustive: for a single consent type, exactly one
of `{granted_at is None and invitation never sent}` / `{granted_at is None and invited}` /
`{granted_at not None and not withdrawn}` / `{granted_at not None and withdrawn}` holds at any
time (withdrawal can only happen after a grant, so "withdrawn" can never coincide with "invited"
or "never asked"). Both the AVD badge and the exemplar badge/text in the template, and the new
filter logic in `avd_dashboard_ajax()`, read these two properties — no inline re-derivation
anywhere else (confirmed by `grep`, see §8 of the implementation below).

## 6. Supervisor-approval wording and gating decision

Decision: **supervisor wording is only shown when `exemplar_consent_badge_state == 'active'`.**
Reasoning: `exemplar_supervisor_approved` is contractually meaningless before the student has
active consent — the column comment itself says supervisor approval is "not yet requested
because student has never consented" while `None`. Showing "supervisor: pending" on a row where
the student was merely *invited* (or has withdrawn) would imply a supervisor decision is
outstanding when in fact nothing has been requested of the supervisor at all. So:

- `exemplar_consent_badge_state == 'active'` → `"Exemplar: student active, supervisor
  {approved|declined|pending}"` (tri-state wording exactly as submitters_v2 uses: `True` →
  "approved", `False` → "declined", `None` → "pending").
- `'invited'` → `"Exemplar: invited, awaiting response"` (no supervisor clause).
- `'withdrawn'` → `"Exemplar: withdrawn"` (no supervisor clause — consistent with the same
  reasoning; supervisor approval is frozen/stale once the student withdraws, so restating it
  would be misleading at a glance).
- `None` (never asked) → nothing rendered, per the brief.

## 7. Filter button design — judgement call, flagged for review

Implemented as **two single filters** (not split sub-filters), one per consent type, each
tri-state-plus-all: `Any / Active / Withdrawn / Not requested`, exactly matching the brief's
suggested shape and the existing `grade_filter` tri-state pattern/session-key convention.

**Judgement call**: the badge has *four* display states (never-asked / invited / active /
withdrawn) but the filter only exposes *three* non-"Any" buckets. "Not requested" is defined at
the query level as `granted_at IS NULL` — i.e. it deliberately **folds "invited, awaiting
response" into "Not requested"** rather than giving "invited" its own button. Reasoning: the
three filter buckets (`active` / `withdrawn` / `granted_at IS NULL`) are a complete, non-overlapping
partition of every record, so every row appears under exactly one non-"Any" filter. Giving
"invited" its own button (making 4 non-"Any" buckets matching the badge states 1:1) was
considered and rejected for this phase: it would either (a) leave a gap where "not requested"
meant only "never invited at all" and an invited-but-unresponded row would match *none* of
Active/Withdrawn/Not-requested, or (b) require a 5th button, which the brief's own example list
(`Any / Active / Withdrawn / Not requested`) doesn't ask for. This is a judgement call, not a
settled design — flagging for review per the brief's instruction.

Exemplar consent filter: implemented as a **single** filter keyed on student consent
(`exemplar_consent_granted_at` / `exemplar_consent_withdrawn`), not two separate filters for
student vs. supervisor sub-state — per the brief's own lean-toward-simplicity steer. The
supervisor sub-state remains visible in the row text but has no filter button.

## 8. Verification

- `grep -n "openday_consent_active\|openday_consent_withdrawn\|openday_consent_granted_at\|exemplar_consent_active\|exemplar_consent_withdrawn\|exemplar_consent_granted_at\|consent_invitation_sent_at" app/ajax/archive/reports.py app/templates/dashboards/avd_dashboard.html app/dashboards/views.py` — confirmed the template files (`_report` macro, `avd_dashboard.html`) never reference the raw consent columns directly; only `app/models/submissions.py` (the two new badge-state properties) and `avd_dashboard_ajax()`'s filter-application block do. The latter is necessary, not a duplication: `ServerSideSQLHandler` filters must be SQL column expressions, not Python `@property` accessors, so the SQL-level filter and the Python-level badge-state property are two different layers reading the same columns for two different purposes (querying vs. display), not two independent re-derivations of the same display decision.
- Verified the four badge states and the three-way filter partition with a standalone logic
  simulation (no DB access) mirroring the exact property bodies: all four expected states
  (never-asked → `None`, invited → `"invited"`, active → `"active"`, withdrawn → `"withdrawn"`)
  resolved correctly, and for every combination of `granted_at`/`withdrawn` exactly one of the
  three filter buckets (`active` / `withdrawn` / `not_requested`) matched — confirming the §7
  partition claim holds, not just in argument.
- Verified the supervisor tri-state wording mapping (`True`→"approved", `False`→"declined",
  `None`→"pending") directly.
- Jinja parsed both edited templates (`_report` string template, `avd_dashboard.html`) with
  `jinja2.Environment.parse()` to catch syntax errors; `ast.parse()` on all three edited Python
  files to catch syntax errors. Confirmed the diff is scoped to the five intended files only
  (`git diff --stat`).
- **Not done, and flagged rather than assumed**: live verification against real data (rendering
  the dashboard in a browser, confirming a record with no consent activity shows no badge, an
  active-AVD-only record shows the solid pill with no exemplar text, an active-exemplar/pending-
  supervisor record shows the combined text, a withdrawn record is visually distinct, and the new
  filters compose correctly with Phase 1's tenant filter and Phase 2's grade filter in the running
  app). This needs the Docker dev stack (or a DB with real consent data) running, which per
  established working practice on this project should be confirmed with David before restarting/
  probing rather than done unilaterally. The query-level reasoning (filters are additional
  `.filter()` calls appended to the same `base_query`, exactly like the existing grade filter) and
  the logic simulation above are the available substitute for this phase; recommend a live
  smoke-test pass once the stack is up.
