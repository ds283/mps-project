# Phase 4 — AVD dashboard: staff-roles block, generic role iteration

Shared context: `.prompts/avd-dashboard/recon.md` §6 (the three
independent marking-history signals: `convenor_intervention`,
`out_of_tolerance`, `moderator_reports`/`was_moderated`) and §10 (row
design — staff-roles block sits below the consent/flags area, the
moderator's line carries its outcome inline rather than a separate
badge). Also read `.prompts/avd-dashboard/phase3-recon-output.md` for the
current row template structure left by Phase 3.

Scope: list each `SubmissionRecord`'s `SubmissionRole`s generically
(supervisor/marker/moderator/etc., labelled by role type, not
hard-coded), with the moderator's line carrying the moderation outcome,
and the report-level `convenor_intervention` flag shown once. **No
details child-row, no feedback document links yet** — Phase 5. If you
find yourself building row-click expansion or linking to a feedback PDF,
stop.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase4-recon-output.md`, present before coding)

1. Locate `SubmissionRoleTypesMixin` (referenced in `submissions.py` and
   `markingevent.py` but not defined in either — find the actual
   definition, likely a mixins module) and copy out every `ROLE_*`
   constant it defines, verbatim, with values.
2. Find any existing role→human-label mapping already used anywhere in
   the app (the legacy archive view rendered "Supervisors:" / "Markers:"
   per role — check `submitters_v2.html` and any other template that
   lists `SubmissionRole`s for the established label convention; e.g. is
   `ROLE_RESPONSIBLE_SUPERVISOR` labelled differently from
   `ROLE_SUPERVISOR`, and is there an existing helper property like
   `role.label` or similar already on the model, or is label text built
   ad hoc in templates today?). Reuse whatever convention already exists
   rather than inventing new wording — if none exists, say so explicitly
   and propose one for review rather than picking silently.
3. Confirm the relationship from `SubmissionRecord` to its roles — `roles`
   appears to be a usable collection per `submissions.py` (`all_submission_
   roles = list(self.roles)`, `self.get_roles(role)`). Confirm whether
   `ROLE_STUDENT` rows also appear in this collection (per the docstring
   reference to `ROLE_STUDENT=7`) and should be excluded from the
   staff-roles block (the student is already named at the top of the row
   — listing them again under "staff roles" would be redundant).
4. Re-confirm the three marking-history signals from `recon.md` §6
   against current source (`SubmitterReport.convenor_intervention`,
   `.out_of_tolerance`, `.moderator_reports` backref,
   `.accepted_moderator_report`) — these may have shifted since the
   original recon pass; quote current definitions verbatim.
5. Confirm how to get from a `SubmissionRecord` to its relevant
   `SubmitterReport`(s) — per `recon.md` §6's caveat, a record can in
   principle have more than one `SubmitterReport` across re-marking
   events. Given Phase 2 already rooted the dashboard query on individual
   `SubmissionRecord`s (one row per record/period, per §12), confirm
   whether there's a natural "the current/latest SubmitterReport for this
   record" accessor, or whether this phase needs to pick one explicitly
   (e.g. most recent by some timestamp) and state the reasoning.
6. Copy the current row template block verbatim so this phase's addition
   is additive (new block below the existing consent/flags area), not a
   rewrite.

## Step 1 — Generic staff-roles list

- Iterate the record's `SubmissionRole`s (excluding `ROLE_STUDENT` per
  Step 0.3), grouped or listed by role type using whatever label
  convention Step 0.2 established, each showing the role-holder's name.
  Multiple holders of the same role type (e.g. co-supervision, multiple
  markers) should group under one label line — match the legacy
  "Markers: A B" multi-name-per-line style from `submitters_v2.html`/the
  old archive view rather than one line per person.
- This must be **generic over role type** — do not hard-code a fixed list
  of "Supervisor/Marker/Moderator" labels with an if/elif chain. Iterate
  whatever role types are actually present on the record and label each
  using the Step 0.2 convention, so a role type added to the system later
  appears automatically without a template change. (The moderator role's
  *outcome* line in Step 2 is a special case on top of this generic list,
  not a replacement for it — moderator still appears in the generic
  iteration too.)
- Include role-holder names in the server-side search index (per
  `recon.md` §10/Phase 4 note: "find reports supervised by X" should work
  via free-text search without a dedicated column or filter) — confirm
  this is wired into whatever `sortstring`/search-field mechanism the
  Report column already uses from Phase 1/2.

## Step 2 — Moderator outcome + convenor intervention

- For the moderator role specifically (if one exists on the record),
  append the outcome inline on that same line using the Step 0.4/0.5
  signals:
  - if `accepted_moderator_report` is set: "— grade accepted"
  - if `out_of_tolerance` is true but no moderator report has been
    accepted yet: "— out of tolerance, no moderator assigned yet" (or
    similar — confirm this state is actually reachable/distinguishable
    given Step 0.5's findings, and adjust wording if the real states
    don't map cleanly onto this)
  - if a `ModeratorReport` exists (`was_moderated`/`moderator_reports`
    non-empty) but isn't the accepted one: confirm what this state means
    in practice (a draft/rejected moderation?) and label it accordingly
- Show `convenor_intervention` once, at report level (not per-role), as a
  small distinct flag — per `recon.md` §6/§10, this is independent of
  whether moderation actually occurred (it can be true with zero
  `ModeratorReport`s, e.g. triggered by a risk flag) and must not be
  conflated with or hidden behind the moderator outcome line.
- Confirm these render correctly for the common case of a record with
  *no* intervention and *no* moderation — nothing extra should appear
  (consistent with Phase 3's "absence is the signal" convention; no "no
  intervention" placeholder).

## Step 3 — Verification

- Manually confirm (describe what you checked, against real data where
  possible):
  - a record with a single supervisor, single marker, no moderation shows
    a clean two-line staff block with no intervention/moderation noise
  - a record with co-supervision or multiple markers groups names
    correctly on one line per role type
  - a record with `convenor_intervention = True` and no `ModeratorReport`
    shows the intervention flag but no moderator line
  - a record with an accepted `ModeratorReport` shows the outcome inline
    on the moderator's role line
  - free-text search by a supervisor/marker name correctly filters rows
  - a role type not previously seen in testing (if you can find or
    construct one) still renders correctly via the generic iteration,
    confirming this isn't secretly hard-coded
- `grep` to confirm no hard-coded role-type if/elif chain was introduced
  where generic iteration was specified.

## Out of scope for this phase

- Details child-row, feedback document links, language-analysis stats,
  full risk-factor breakdown — Phase 5.
