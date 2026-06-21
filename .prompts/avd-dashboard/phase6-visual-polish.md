# Phase 6 — AVD dashboard: visual polish, staff-role ordering, AI declaration/compliance grouping, filter bar compactness

Shared context: `.prompts/avd-dashboard/recon.md` (full history of design
decisions to date), the Phase 4b/5/5b recon outputs for current file/
function names, and the mockup iterations from this conversation
(referenced inline below — ask if you need the rendered images
re-described, they are not separate files). This is a **visual/structural
polish phase on existing content** — every field already exists and is
already correctly computed (grades, consent, roles, risk factors, stats,
summary, embargo). This phase only touches how it's laid out and styled,
plus one small ordering/relabelling fix and one genuine content-grouping
correction (AI declaration vs. AI-flagged, detailed below — read that
section carefully, it is not just a styling note).

Do not change any underlying query, filter logic, or data computation
except where explicitly instructed (role ordering, AI declaration/
compliance regrouping). If you find yourself touching
`avd_dashboard_ajax()`'s filter/sort logic beyond what's specified, stop —
that's not this phase.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase6-recon-output.md`, present before coding)

1. Locate `metric_tile()` in
   `app/templates/convenor/dashboard/overview_cards/_metric_tile.html` —
   copy verbatim, confirm its macro signature
   (`value, label, variant='secondary', denominator=none, zero_variant=none,
   nonzero_variant=none, value_ok=none`) and confirm how it's imported/
   called from at least one existing call site, so the new call sites in
   this phase follow the same import pattern.
2. Copy verbatim the current row template (`_report`/`identity_line()`/
   `flags_line()`/`staff_roles()`/`report_flags()` macros, per Phase 4b/5
   recon outputs) and the current `_details` template/`_details_context()`
   builder from Phase 5.
3. Confirm `SubmissionRoleTypesMixin`'s `ROLE_*` constants and the
   existing `role_as_str` label convention (per Phase 4 recon) — needed
   for Step 2's ordering and the "Assessor" → "Presentation assessor"
   relabel below.
4. Confirm `risk_factors_ui_summary()`'s exact factor keys and labels
   again (per `recon.md` §8) — specifically the AI-compliance factor's
   actual label string (used literally in Step 4 below; do not invent
   different wording for it — e.g. if the prior recon work logged it as
   "AI compliance statement," keep that exact label, not a paraphrase).
5. Confirm the current filter-bar template structure (the seven filter
   sections: tenant/pclass/year/group/grade/AVD-consent/exemplar-consent)
   to scope Step 5's consolidation precisely.

## Step 1 — Report statistics: use `metric_tile()`

- Replace the current report-statistics rendering in `_details` with four
  calls to `metric_tile()` (words, pages, figures, tables), `variant='secondary'`
  for all four (these are plain counts, not semantically good/bad on
  their own — don't invent a colour-coding scheme for them).
- Keep the stated-word-count line and its discrepancy badge as free-form
  content below the tile row (per the mockup — `metric_tile()` isn't the
  right shape for "value + inline qualifier badge").

## Step 2 — Staff-roles block: visual container, correct order, clickable names

- Wrap the staff-roles content in its own visually distinct container
  (per the mockup: small-caps "Staff" label, subtle background, rounded
  corners) rather than plain stacked text in the row panel.
- **Ordering**: render role groups in this fixed order when present —
  Responsible supervisor, Supervisor, Marker, Presentation assessor,
  Moderator — followed by any other role types present on the record, in
  whatever order they're naturally returned (don't invent a sort for the
  long tail — e.g. Exam board, External examiner). Implement this as an
  explicit priority list the generic iteration from Phase 4 sorts against
  (role type not in the list sorts after all listed types), not a
  hard-coded if/elif chain that abandons the Phase 4 generic-iteration
  property — the genericness (any role type renders automatically) must
  be preserved, only the *order* changes.
- **Relabel**: "Assessor" → "Presentation assessor" wherever it's
  rendered as a role-group label (confirm via Step 0.3 whether this means
  changing `role_as_str`'s output directly — which would affect every
  other template using it — or applying an AVD-dashboard-local label
  override. If `role_as_str` is used elsewhere with the shorter label and
  changing it globally would be a wider behavioural change than this
  phase intends, use a local override map in the AVD dashboard's template
  only, and say so explicitly in your recon output rather than silently
  picking the broader change.)
- **Make role-holder names clickable**, linking to that role's
  `MarkingReport` (or `ModeratorReport` for the moderator) using the
  Phase 5b-fixed read-only routes — the same links that currently live in
  the details panel's "marking & moderation reports" list.
- **Remove** the details panel's separate "marking & moderation reports"
  list entirely (per the mockup) — its content is now fully covered by
  the staff-roles block's clickable names. The moderator's outcome text
  ("— grade accepted", per Phase 4) stays on the moderator's line in the
  staff block, it does not move anywhere else.

## Step 3 — Disclosure control: full-width footer bar

- Replace the current plain-link disclosure trigger with a full-width
  button/bar beneath the row's main content (per the mockup): subtle
  background tint, top border separating it from the content above,
  centered text + chevron icon that flips direction (down when
  collapsed, up when expanded) and label text that swaps between "Show
  full marking & report details" / "Hide full marking & report details".
- Preserve the existing DataTables `row().child()` expand/collapse
  mechanism from Phase 5 — this is a styling/element change to the
  trigger, not a new expansion mechanism.

## Step 4 — Report summary: promote to top, and regroup AI declaration with its compliance verdict

- Move the LLM `report_summary` content to the **top** of the expanded
  details panel, above the report-statistics tiles, in a bordered/tinted
  callout (per the mockup: light info-coloured border, small label "AI
  report summary" with a leading icon, prose below — not inside a code
  block or anything implying raw data).
- **AI declaration vs. AI-flagged — read this carefully, it's a content
  correction, not just styling**: these are two unrelated signals that
  must not be visually conflated.
  - The "AI flagged" badge (main row) and its full risk-factor card are
    the stylometric anomaly signal (large Mahalanobis distance from the
    pre-LLM baseline) — a genuine advisory risk flag. This stays exactly
    as styled (warning/amber when unresolved, resolved-green once
    actioned) — **no change** to this one.
  - The **AI declaration** (the student's own statement of what
    generative AI use, if any, they made) is informational, not a
    warning. A declaration being present is normal and expected, not
    itself concerning. **Restyle the AI declaration box to neutral
    styling** — secondary/muted background, a plain info icon (not an
    alert triangle), no warning colour.
  - The **AI compliance statement** risk factor (the convenor's judgement
    on whether the *declared* AI use was acceptable, from
    `risk_factors_ui_summary()`, exact label per Step 0.4) is currently
    grouped with the other risk factors (word count discrepancy,
    similarity concern) in the right-hand column. **Move it out of that
    column and attach it directly beneath the AI declaration box** — same
    bordered container, two sections divided by an internal rule:
    declaration text on top (neutral styling per above), compliance
    verdict below (resolved-state styling — check icon, resolver name,
    date, annotation — matching the other risk-factor cards' internal
    layout, just relocated and visually attached to the declaration it
    judges rather than floating alongside unrelated factors).
  - The right-hand Risk factors column now contains only the factors
    *not* tied to the declaration (word count discrepancy, similarity
    concern, and any other non-AI-declaration factors present).
  - If a record has no AI declaration at all (the common case — absence
    of a declaration means no AI use), the AI-compliance risk factor
    presumably also shouldn't be present (per `recon.md`/Phase 5: a
    declaration's presence is what *triggers* the compliance review, per
    the original brief). Confirm this relationship holds in the actual
    data/logic (`risk_factors_ui_summary()` shouldn't surface a
    compliance factor with no declaration behind it) rather than assuming
    it — if it doesn't hold cleanly, flag it rather than silently coding
    around an inconsistency.
- Restyle the remaining risk-factor cards (word count discrepancy,
  similarity concern) as bounded cards per the mockup — factor name +
  icon on top, resolver/date as a smaller muted line beneath, annotation
  text below that — rather than the current plain stacked text.

## Step 5 — Filter bar compactness

- Merge "Filter by AVD consent" and "Filter by exemplar consent" under
  one heading ("Filter by consent") with two adjacent button groups
  (labelled "AVD" / "Exemplar" inline) rather than two full sections each
  with their own heading — saves one heading + spacing block's worth of
  vertical space.
- Beyond that single merge, do not restructure the other five filter
  sections (tenant/pclass/year/group/grade) in this phase — a more
  significant filter-bar redesign (e.g. collapsible/accordion) is a
  separate decision not yet made; this step is the one concrete merge
  agreed so far.

## Step 6 — Verification

- Manually confirm (describe what you checked):
  - `metric_tile()` renders correctly for all four stat tiles, with
    correct values, no console/template errors
  - staff-roles block renders in the correct fixed order for a record
    with all five standard role types present, and correctly appends an
    unlisted role type (e.g. Exam board) after them without needing a
    template change
  - role-holder names in the staff block are clickable and link to the
    correct individual report (re-verify against Phase 5b's read-only
    routes, for both `data_dashboard_reports` and
    `data_dashboard_similarity` test users)
  - the details panel's old separate marking/moderation report list is
    gone, with no loss of functionality (every link that used to live
    there is now reachable from the staff block)
  - disclosure bar expands/collapses correctly, chevron and label text
    both flip state correctly, existing DataTables sort/search/pagination
    still unaffected
  - report summary appears at the top of the expanded panel
  - a record with an AI declaration shows the declaration (neutral
    styling) with its compliance verdict directly attached beneath it,
    and the Risk factors column does *not* duplicate that factor
  - a record with no AI declaration shows no declaration box and no
    compliance-verdict attachment (confirm this is genuinely absent, not
    just visually hidden)
  - the "AI flagged" stylometric badge/risk-factor card is unchanged in
    styling and is not confused with the declaration anywhere
  - filter bar: AVD and exemplar consent filters now sit under one
    "Filter by consent" heading and both still filter correctly,
    independently, in combination with every other existing filter
- `grep` to confirm `role_as_str` wasn't changed globally unless that was
  the explicitly chosen approach per Step 2's relabel decision.

## Explicitly out of scope

- The restricted/embargoed-report row treatment (whether the grade itself
  should be hidden, flagged in the previous review as an open question,
  not yet resolved) — do not touch this in this phase.
- Any further filter-bar restructuring beyond the single consent-filter
  merge in Step 5.
- Project-class colour-coding (sidebar accent) — still deferred per
  `recon.md` §13.
