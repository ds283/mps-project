# Phase 4 recon output — staff-roles block, generic role iteration

## 1. `SubmissionRoleTypesMixin` — actual definition and constants

Defined in `app/models/model_mixins.py:1527`, not in `submissions.py`/`markingevent.py` (which
only reference it). `SubmissionRole` (`app/models/submissions.py:120`) inherits it.

```python
class SubmissionRoleTypesMixin:
    ROLE_SUPERVISOR = 0
    ROLE_MARKER = 1
    ROLE_PRESENTATION_ASSESSOR = 2
    ROLE_MODERATOR = 3
    ROLE_EXAM_BOARD = 4
    ROLE_EXTERNAL_EXAMINER = 5
    ROLE_RESPONSIBLE_SUPERVISOR = 6

    # ROLE_STUDENT is used only for PeriodAttachment access control; it is never the type of
    # an actual SubmissionRole instance
    ROLE_STUDENT = 7

    _MIN_ROLE = ROLE_SUPERVISOR
    _MAX_ROLE = ROLE_RESPONSIBLE_SUPERVISOR   # = 6

    _role_string = {
        ROLE_SUPERVISOR: "Supervisor",
        ROLE_MARKER: "Marker",
        ROLE_PRESENTATION_ASSESSOR: "Assessor",
        ROLE_MODERATOR: "Moderator",
        ROLE_EXAM_BOARD: "Exam board",
        ROLE_EXTERNAL_EXAMINER: "External",
        ROLE_RESPONSIBLE_SUPERVISOR: "Responsible supervisor",
    }
```

`role_choices` (used for WTForms dropdowns) exists too, but uses slightly different wording
("Presentation assessor", "Exam board member", "External examiner") than `_role_string`. Not
used by this phase — see §2.

## 2. Existing role→label convention

**Found, and it's exactly the property the brief asked about**: `SubmissionRole.role_as_str`
(`app/models/submissions.py:267-269`):

```python
@property
def role_as_str(self) -> str:
    return self._role_string.get(self.role, "Unknown")
```

`grep` confirms `role_as_str` is already used as the canonical per-role label in 15+ templates
(`marking_form.html`, `moderator_report_form.html`, `view_feedback.html`,
`assign_moderator.html`, `marking_reports_inspector.html`, `edit_roles.py`, etc.) — this is the
established, single point of truth for "what do we call this role type" and confirms
`ROLE_RESPONSIBLE_SUPERVISOR` ("Responsible supervisor") is indeed labelled distinctly from
`ROLE_SUPERVISOR` ("Supervisor").

**However**, the *block we're replacing* (current `archive/reports.py` "Roles" section, and the
legacy `submitters_v2.html` roles grid) does **not** use `role_as_str` at all. Both hardcode
plural English labels per a fixed, partial set of role types:

- `reports.py` (current AVD dashboard, pre-Phase-4): `role_list(record.supervisor_roles,
  'Supervisors')` / `role_list(record.marker_roles, 'Markers')` /
  `role_list(record.moderator_roles, 'Moderators')` — three hardcoded calls, plural labels
  invented ad hoc, not derived from `role_as_str`.
- `submitters_v2.html`: headers `"Supervisor"` (singular!), `"Markers"` (plural), `"Moderator"`
  (singular), `"Presentation"` — inconsistent pluralization, also ad hoc, also not derived from
  `role_as_str`.

Both of these go through `SubmissionRecord.supervisor_roles` / `.marker_roles` /
`.moderator_roles`, which call `get_roles()` (`submissions.py:1218`) — a **role_map dict
covering only 3 of the 7 role types** (`"supervisor"` bucket conflates `ROLE_SUPERVISOR` +
`ROLE_RESPONSIBLE_SUPERVISOR`; `"marker"` → `ROLE_MARKER`; `"moderator"` → `ROLE_MODERATOR`).
Calling `get_roles()` with `"assessor"`/`"exam_board"`/`"external_examiner"` raises `KeyError` —
this is the literal hardcoded if/elif-equivalent the brief tells us not to reuse, and it cannot
even represent 4 of the 7 role types as separate groups.

**Conclusion**: there is no existing *plural-label* convention to reuse — only the singular
`role_as_str`. Per the brief's instruction ("if none exists, say so explicitly and propose one
for review rather than picking silently"):

**Decision (flagged for review)**: use `role.role_as_str` as the group label, and pluralize
generically — append `"s"` whenever a group has more than one holder (`"Marker"` →
`"Markers"`, `"Supervisor"` → `"Supervisors"`, `"Responsible supervisor"` → `"Responsible
supervisors"`, etc.). This is a naive but fully generic transformation (no per-role-type
special-casing), and reuses the one canonical label that does exist. It will look slightly odd
for `"Exam board"` → `"Exam boards"` if that role type is ever multiply-held, but no better
generic alternative exists without hand-curating per-type plurals, which is exactly what the
brief asks us not to do.

Group **ordering**: sort by the raw `role.role` integer value (0=Supervisor … 6=Responsible
supervisor) via Jinja's `groupby` filter, which sorts before grouping. This is the most
defensibly generic ordering — it requires no knowledge of which role types exist, and any role
type added later sorts in automatically wherever its ID places it.

## 3. `SubmissionRecord` → roles relationship; `ROLE_STUDENT` exclusion

`SubmissionRole.submission` relationship has `backref=db.backref("roles", lazy="dynamic")`
(`submissions.py:139-144`) — so `record.roles` is a dynamic query; `record.roles.all()` is the
usable collection, confirming the brief's `submissions.py` references (`get_roles()`,
`all_submission_roles = list(self.roles)`).

**`ROLE_STUDENT` exclusion is moot, not just empirically true**: the mixin's own comment says
"never the type of an actual SubmissionRole instance", and this is structurally enforced —
`SubmissionRole._validate_role` (`submissions.py:172-180`) clamps any assigned `role` value
above `_MAX_ROLE` (=6) down to 6. Since `ROLE_STUDENT=7 > _MAX_ROLE`, it is **impossible** for a
persisted `SubmissionRole.role` to equal 7. No filtering code is needed or added; the generic
iteration over `record.roles.all()` can never encounter it. (Noted, not defended with a redundant
runtime check, per the project's "don't validate what can't happen" convention.)

## 4. Marking-history signals — re-confirmed against current source

`SubmitterReport` (`app/models/markingevent.py:1024`):

```python
out_of_tolerance = db.Column(db.Boolean(), default=False, nullable=False)
convenor_intervention = db.Column(db.Boolean(), default=False, nullable=False)
accepted_moderator_report_id = db.Column(..., db.ForeignKey("moderator_reports.id", ...), nullable=True)
accepted_moderator_report = db.relationship("ModeratorReport", foreign_keys=[accepted_moderator_report_id], uselist=False)
moderator_accepted_id = db.Column(db.Integer(), db.ForeignKey("submission_roles.id"), nullable=True)
moderator_accepted_by = db.relationship("SubmissionRole", foreign_keys=[moderator_accepted_id], uselist=False)
```

Unchanged from `recon.md` §6 — definitions match verbatim. `was_moderated` (recommended by
`recon.md` but **not yet added**) has now been added to `SubmitterReport`:

```python
@property
def was_moderated(self) -> bool:
    """True if at least one ModeratorReport was ever produced for this report,
    whether or not it was the one ultimately accepted."""
    return self.moderator_reports.first() is not None
```

**Important clarification not in `recon.md`**: there are **two distinct** `moderator_reports`
dynamic backrefs, both named identically but on different owning models:

- `SubmissionRole.moderator_reports` — backref from `ModeratorReport.role` (per-*role-holder*).
- `SubmitterReport.moderator_reports` — backref from `ModeratorReport.submitter_report`
  (per-*report*, i.e. across however many moderator roles got involved).

`was_moderated` uses the **`SubmitterReport`-level** one, matching `recon.md` §6.

## 5. Picking "the" `SubmitterReport`, and full state-machine trace for the moderator outcome

No "current/latest" accessor exists. Added a module-level helper in `app/ajax/archive/reports.py`
(display-layer judgement call, not a model property, since "most recent" is specific to how this
dashboard wants to summarise marking history):

```python
def _latest_submitter_report(record: SubmissionRecord) -> Optional[SubmitterReport]:
    return record.submitter_reports.order_by(
        SubmitterReport.creation_timestamp.desc(), SubmitterReport.id.desc()
    ).first()
```

`creation_timestamp` is always set explicitly (`datetime.now()`) at `SubmitterReport` creation
(`tasks/markingevent.py:585`), so ordering by it is reliable; `.id.desc()` breaks ties
deterministically.

**State-machine trace** (`app/models/markingevent.py:840-919` docstring +
`tasks/markingevent.py:296-409`, `convenor/markingevent.py:5746-5861`), to check the brief's
proposed wording against what's actually reachable:

- `_check_tolerance_and_grade()`: when grades disagree beyond tolerance for the first time,
  `out_of_tolerance = True` is set, and:
  - if a `ROLE_MODERATOR` `SubmissionRole` **already exists** on the record, one is chosen at
    random and `_assign_moderator()` is called on it **immediately, in the same code path** —
    this creates a `ModeratorReport` tied to that role and advances to
    `AWAITING_MODERATOR_REPORT`.
  - if **no** `ROLE_MODERATOR` role exists at all, state becomes `NEEDS_MODERATOR_ASSIGNED` (5)
    — no `SubmissionRole`, no `ModeratorReport`. The convenor's `assign_moderator` view
    (`convenor/markingevent.py:5746`) is the only way out: it creates a **brand-new**
    `SubmissionRole(role=ROLE_MODERATOR)` and a `ModeratorReport` together, atomically.
  - `accepted_moderator_report_id` is set **only** by the explicit `accept_moderator_grade`
    convenor action (`convenor/markingevent.py:5822-5843`) — never automatically. It does **not**
    clear `out_of_tolerance`, which is sticky from this point on (the only place that clears it
    is the in-tolerance branch of `_check_tolerance_and_grade`, which cannot run again after the
    SR has advanced past the tolerance check).

**Consequence — the brief's literal wording is unreachable as specified**: "out of tolerance, no
moderator assigned yet" was proposed as text on *the moderator's role line*. But:
- If no `ROLE_MODERATOR` role exists on the record, there is no moderator line to attach it to
  (this is exactly `NEEDS_MODERATOR_ASSIGNED`).
- If a `ROLE_MODERATOR` role *does* exist, a `ModeratorReport` already exists for whichever role
  was chosen (created in the same transaction that set `out_of_tolerance = True`) — so "no
  moderator assigned" is never true on an existing role's line.
- The only way a `ROLE_MODERATOR` role can exist with **no** `ModeratorReport` is a second,
  unchosen moderator role on a record with more than one moderator (rare, but generic iteration
  must not break on it) — that role simply has nothing to report.

**Resolution (deviates from `recon.md` §10's exact wording, flagged for review)**:

1. On a moderator role-group's line, append outcome text derived from the record's latest
   `SubmitterReport` (not literally "no moderator assigned yet" — that can't occur on a line that
   exists at all):
   - `accepted_moderator_report_id` set → `"grade accepted"`
   - else `was_moderated` (a `ModeratorReport` exists for this report, not yet accepted) →
     `"moderator report submitted, awaiting acceptance"` if any of `sr.moderator_reports` has
     `report_submitted=True`, else `"awaiting moderator's report"` (still drafting).
   - else → nothing (covers both "tolerance never breached" and "unchosen second moderator").
2. **Separately**, for the genuinely unreachable-via-role-line case — `out_of_tolerance=True` and
   **no** `ROLE_MODERATOR` role exists on the record at all (`NEEDS_MODERATOR_ASSIGNED`) — surface
   a small standalone flag next to `convenor_intervention` (not on a role line, since none exists
   to host it): `"Out of tolerance — moderator not yet assigned"`.

This keeps every reachable state visible somewhere on the row, without inventing UI for a state
that cannot occur on the line the brief proposed.

## 6. Current row template block (verbatim, before this phase's edit)

`app/ajax/archive/reports.py`, `_report` string template, the block this phase's edit is additive
to / replaces (the "Roles" sub-block specifically is **replaced**, since it's the exact
non-generic pattern this phase exists to fix; everything else is untouched):

```jinja2
{# Supervision / presentation grades #}
{% if supervision_grade is not none or presentation_grade is not none %}
    <div class="small text-muted mt-1"> ... </div>
{% endif %}

{# Roles #}
{% set supervisor_roles = record.supervisor_roles %}
{% set marker_roles = record.marker_roles %}
{% set moderator_roles = record.moderator_roles %}
<div class="mt-1 d-flex flex-column justify-content-start align-items-start gap-1">
    {{ role_list(supervisor_roles, 'Supervisors') }}
    {{ role_list(marker_roles, 'Markers') }}
    {{ role_list(moderator_roles, 'Moderators') }}
</div>

{# Turnitin data #}
{{ turnitin_info(record) }}
```

`role_list(roles, label)` macro (also replaced) hardcoded the label as a parameter rather than
deriving it from `role_as_str` — exactly the ad hoc pattern from §2.

## Implementation plan (Steps 1–2)

- Replace the "Roles" block with a generic `staff_roles(roles, moderation_outcome)` macro,
  grouping a **pre-fetched** `record.roles.all()` list (passed in from Python, alongside
  `moderation_outcome` and a `convenor_intervention`/`out_of_tolerance_unassigned` flags block) —
  this also removes 3 separate dynamic-relationship queries per row (`supervisor_roles`,
  `marker_roles`, `moderator_roles`, each its own query) in favour of 1.
- Add a `report_flags(convenor_intervention, out_of_tolerance_unassigned)` macro rendering small
  Bootstrap 5.3 subtle-token badges, placed between consent badges and the staff-roles block,
  shown only when at least one flag is true (no "not flagged" placeholder).
- Wire role-holder names into the AVD dashboard's free-text search: add a `"records"` entry to
  the `columns` dict in `avd_dashboard_ajax()` (`app/dashboards/views.py`) using
  `ServerSideSQLHandler`'s `search_collection` **callable** form (not the plain-relationship
  `.any()` form, which only supports a one-hop relationship — role-holder names are two hops away,
  `SubmissionRecord.roles → SubmissionRole.user → User.first_name/last_name`):

  ```python
  def _role_holder_search_filter(search_expr):
      return SubmissionRecord.roles.any(SubmissionRole.user.has(search_expr))

  records_col = {
      "search": func.concat(User.first_name, " ", User.last_name),
      "search_collection": _role_holder_search_filter,
      "search_collation": "utf8_general_ci",
  }
  ```

  Verified with a standalone SQLAlchemy compile test (no DB) that the nested
  `roles.any(user.has(...))` produces a correctly-scoped nested `EXISTS` — confirmed it does
  **not** collide with the outer query's separate join to `User` for the student (each `EXISTS`
  subquery has its own independent FROM-scope in the compiled SQL; this is standard self-join-via-
  correlated-subquery behaviour, not something specific to this schema).

## Step 3 — verification

- **Single supervisor + single marker, no moderation**: rendered a fake row with
  `roles=[Role(SUPERVISOR), Role(MARKER)]`, no moderation outcome, both flags `False`. Output
  contains `"Supervisor:"` / `"Marker:"` (singular, one holder each) and neither
  `"Convenor intervention"` nor `"Out of tolerance"` — clean two-line block, no noise. ✓
- **Co-supervision / multiple markers**: two supervisors + two markers in one `roles` list.
  Output groups them onto one `"Supervisors:"` line and one `"Markers:"` line (pluralized, both
  names present once each) rather than one line per person. ✓
- **`convenor_intervention=True`, no `ModeratorReport`**: flag renders (`"Convenor
  intervention"`), no `"Moderator"` line appears (no `ROLE_MODERATOR` role on the record). ✓
- **Accepted `ModeratorReport`**: `moderation_outcome="grade accepted"` with a `ROLE_MODERATOR`
  role present renders `"Moderator: ... — grade accepted"` inline on that role's line, not a
  separate badge. ✓
- **Out of tolerance, no moderator role at all** (`NEEDS_MODERATOR_ASSIGNED`):
  `out_of_tolerance_unassigned=True`, no moderator role in `roles`. Renders the standalone
  `"Out of tolerance — moderator not yet assigned"` flag; no moderator line (none exists). ✓
- **Unrecognised/future role type**: a role with `role=99` (no entry in `_role_string`) still
  renders generically via `role_as_str`'s own `"Unknown"` fallback — group header reads
  `"Unknown:"` with the holder's name still listed, confirming the iteration is driven entirely
  by whatever `role.role` values are present, not by a hardcoded list. ✓

All five rendered via a standalone Jinja parse/render harness (`jinja2.Environment().from_string()`
against the extracted `_report` template string, fake `record`/`role` objects, no Flask app or DB)
— `python3 -m py_compile` on all three edited `.py` files, plus a `jinja2.Environment().parse()`
syntax check on the full `_report` template string, both passed.

- **`grep` for a hardcoded role-type if/elif chain**: `grep -n
  "ROLE_SUPERVISOR\|ROLE_MARKER\|ROLE_MODERATOR\|ROLE_RESPONSIBLE" app/ajax/archive/reports.py
  app/dashboards/views.py` returns exactly two hits, both `SubmissionRole.ROLE_MODERATOR` used as
  a single equality comparison (computing `has_moderator_role` and passing `moderator_role_id` to
  the template) — the moderator-outcome special case explicitly permitted by the brief, not an
  if/elif chain over role types. No other role constant appears in either file.
- **Search-filter SQL shape**: verified with a standalone SQLAlchemy compile (no DB connection,
  separate throwaway declarative models reproducing the same `SubmissionRecord
  -roles-> SubmissionRole -user-> User` relationship shape) that
  `SubmissionRecord.roles.any(SubmissionRole.user.has(search_expr))` compiles to a correctly
  double-nested `EXISTS`, and that this does **not** collide with the outer query's separate
  `JOIN ... users` for the student even when both are present in the same compiled statement
  (each `EXISTS` subquery has its own independent FROM-scope).

**Not done, flagged rather than assumed** (matches the gap Phase 3 left open): live
browser/DB verification — confirming the generic role block, moderator-outcome wording, and
free-text role-holder search actually behave correctly against real data. This needs the Docker
dev stack running; per established working practice on this project (see Phase 3's recon output),
that should be confirmed with David before restarting/probing rather than done unilaterally. The
local model is also missing the `html2text` package, so even a no-DB import-only compile check of
the real `app` package isn't currently possible outside the container — the verification above
substitutes standalone reconstructions of the exact relationship/template shapes instead.

## Out of scope, confirmed unaffected

Feedback document links, full risk-factor breakdown, per-role `MarkingReport` links — untouched,
deferred to Phase 5 per the brief.
