# Phase 3 — AVD dashboard: consent badges and filters

Shared context: `.prompts/avd-dashboard/recon.md` (§4 for consent field
semantics, §10 for the row/badge design, §11–12 for the embargo property
and base-query shape established in Phase 2 — this phase's rows are one
per `SubmissionRecord`, already confirmed). Also read
`.prompts/avd-dashboard/phase2-recon-output.md` for the actual current
file/function names: `app/dashboards/views.py::avd_dashboard_ajax()`,
`app/ajax/archive/reports.py::avd_dashboard_rows()`,
`app/templates/dashboards/avd_dashboard.html`.

Scope: two consent badge clusters (AVD, exemplar) in the row panel, plus
filter buttons for each. **No staff-roles block, no details child-row,
no feedback document links yet** — Phases 4 and 5. If you find yourself
iterating `SubmissionRole`s or building a child-row, stop.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase3-recon-output.md`, present before coding)

1. Confirm the exact field names and semantics on `SubmissionRecord` for
   both consent types — copy verbatim from `app/models/submissions.py`:
   - AVD: `openday_consent_granted_at`, `openday_consent_withdrawn`,
     `openday_consent_active` property (per `recon.md` §4)
   - Exemplar: `exemplar_consent_granted_at`, `exemplar_consent_withdrawn`,
     `exemplar_consent_active` property, `exemplar_supervisor_approved`
     (tri-state — confirm `None`/`True`/`False` semantics, don't assume)
   - Shared invitation tracking: `consent_invitation_sent_at`,
     `consent_reminder_sent_at` — confirm (per `recon.md` §4's open
     question) whether these are genuinely shared across both consent
     types or whether Phase 1/2 changes revealed separate fields. State
     which.
2. Look at `submitters_v2.html`'s existing consent UI (the convenor
   "submitters" inspector, mentioned in the original brief) for the
   established visual/badge convention for consent status — reuse its
   class names and wording style where sensible rather than inventing a
   parallel convention, but adapt for the AVD-dominant/exemplar-secondary
   weighting from `recon.md` §10 (this view's badge hierarchy is
   intentionally different: AVD is the solid/dominant pill, exemplar is
   muted text — don't just copy the convenor view's treatment wholesale
   if it weights both consent types equally).
3. Confirm `common.css`'s teal token ramp (`--db-teal-*`) added in Phase 1
   — these badges should draw the AVD pill colour from that ramp, not a
   new ad hoc colour.
4. Copy the current row template block (panel cell) verbatim from
   `avd_dashboard.html`/`avd_dashboard_rows()` so this phase's edit is
   additive to the existing identity-line/grade-line structure from
   Phase 2, not a rewrite.

## Step 1 — AVD consent badge

- Render a small solid pill (teal background, per Step 0.3) when
  `openday_consent_active` is true: "AVD consent active" with an
  appropriate icon (e.g. a graduation-cap/school icon — check what's
  already available in whatever icon set the codebase uses, per
  `submitters_v2.html` or other existing templates, rather than
  introducing a new icon library).
- Per `recon.md` §10: **no badge at all** when consent was never
  requested (`openday_consent_granted_at is None` and no invitation
  sent) — this is the default, silent state, not a "not requested" badge.
- When an invitation has been sent but not yet responded to
  (`consent_invitation_sent_at is not None` and
  `openday_consent_granted_at is None`), show a muted "AVD: invited,
  awaiting response" text indicator — not the solid pill (that's reserved
  for active consent specifically).
- When withdrawn (`openday_consent_granted_at is not None` and
  `openday_consent_withdrawn` is true), show a distinct "AVD consent
  withdrawn" indicator — visually different from both "active" and
  "invited" (e.g. muted/warning tone, not the solid teal pill, so it
  can't be mistaken for active consent at a glance).

## Step 2 — Exemplar consent badges (student + supervisor, shown separately)

- Muted text style (not a solid pill), positioned beside or beneath the
  AVD badge per the Step 1.2/recon.md §10 visual hierarchy.
- Student side: same four states as Step 1 (silent/never-asked, invited,
  active, withdrawn) but driven by `exemplar_consent_active` /
  `exemplar_consent_granted_at` / `exemplar_consent_withdrawn`.
- Supervisor side: tri-state per Step 0.1 — confirm exact wording for
  each of the three states (e.g. "pending" / "approved" / "declined") and
  whether supervisor approval is even meaningful before student consent
  exists (i.e. should "supervisor: —" render when
  `exemplar_consent_active` is false, since there's nothing for the
  supervisor to approve yet? Decide and state the reasoning in your
  recon output, don't silently pick one without explanation).
- Render as a single combined text fragment, e.g. "Exemplar: student
  active, supervisor pending" — per the mockup in this conversation —
  rather than two separate badge elements, to keep this secondary to the
  AVD pill.

## Step 3 — Filter buttons

- Add filter buttons for AVD consent state (e.g. "Any / Active /
  Withdrawn / Not requested") alongside the existing tenant/pclass/year/
  group/has-grade buttons from Phases 1–2, same visual style and same
  session-key persistence pattern already established for those.
- Add a parallel filter for exemplar consent — decide whether this needs
  to be one combined filter (since student + supervisor are two
  sub-states) or two separate filters, and state the reasoning. Lean
  toward simplicity: a single "Exemplar: Any / Active / Withdrawn / Not
  requested" filter keyed on student consent (the supervisor sub-state is
  visible in the row but probably doesn't need its own filter button,
  since "fully approved for exemplar use" isn't likely to be a common
  search compared to "consented at all") — but flag this as a judgement
  call for review rather than treating it as settled.
- Wire both filters into `avd_dashboard_ajax()`'s query the same way the
  Phase 2 "has grade" tri-state filter works.

## Step 4 — Verification

- Manually confirm (describe what you checked, against real data if
  possible):
  - a record with no consent activity at all shows neither badge (clean
    row, no placeholder text)
  - a record with active AVD consent only shows the solid pill and no
    exemplar text
  - a record with active exemplar consent (student) but pending
    supervisor approval shows the combined exemplar text correctly
  - a withdrawn-consent record is visually distinguishable from an
    active one at a glance, not just by reading the text
  - each new filter button correctly narrows the result set, including
    in combination with Phase 1's tenant filter and Phase 2's has-grade
    filter (i.e. filters compose, not just work individually)
- `grep` for the consent field names to confirm there's no duplicated/
  inline re-derivation of the active/withdrawn/invited logic outside the
  model properties — the badge-state decision should be made once
  (preferably as small helper properties or a template macro), not
  recomputed separately in the AVD-badge code and the exemplar-badge code.

## Out of scope for this phase

- Staff-roles block (generic `SubmissionRole` iteration), details
  child-row, feedback document links — Phases 4 and 5.
