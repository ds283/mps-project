# Phase 7 — AVD dashboard: grade capsule, details panel de-nesting, download button cleanup, processed-report fallback

Shared context: `.prompts/avd-dashboard/recon.md` and the Phase 4b/5/5b/6
recon outputs for current file/function names. This phase touches four
independent things — grade display, details-panel wrapper structure,
download button styling, and original/processed report download
behaviour. Treat each as its own step with its own verification; don't
let one bleed into another.

## Step 0 — Reconnaissance (write to
`.prompts/avd-dashboard/phase7-recon-output.md`, present before coding)

1. **Grade capsule**: locate `.sv2-metric-cap`/`.sv2-metric-cap-label`/
   `.sv2-metric-cap-body`/`.sv2-m-item`/`.sv2-m-lbl`/`.sv2-m-val`/
   `.sv2-m-sep` CSS (currently in `submitters_v2.html`'s own `<style>`
   block, per prior review — confirm). Determine whether this CSS is
   scoped to that one template or already available globally. If scoped
   locally, decide whether to (a) hoist the relevant rules into
   `common.css` so both templates share one definition (preferred, per
   the existing CSS-token-discipline convention — no divergent UI
   elements for the same concept), or (b) duplicate the minimal needed
   rules into the AVD dashboard's own template. State which and why
   before implementing — hoisting is preferred unless there's a concrete
   reason (e.g. the rules depend on other `submitters_v2.html`-local
   context) that makes duplication safer.
2. Confirm `SubmissionRecord.grade_display_data()`'s exact return shape
   (per its use in `submitters_v2.html` line ~661/818 and the Phase 2
   recon note that this method already governs grade-formatting
   convention) — list of `{label, grade}` items. Confirm it already
   includes Report/Supervision/Presentation in one call, or whether the
   AVD dashboard needs to filter/reshape it.
3. **Details panel wrapper**: copy verbatim the current `_details`
   template's outer markup (from Phase 5/6). Identify every nested
   bordered/backgrounded container from the outermost (DataTables child
   row) inward. Confirm which one is genuinely redundant — per the
   screenshot reviewed in this conversation, there appear to be two
   levels of box (an outer wrapper around the whole details panel, plus
   inner cards for report-summary/stats/risk-factors) where only the
   inner, content-specific cards (report summary callout, stat tiles,
   risk-factor cards) are doing real visual work; the outer wrapper
   around all of them is the suspected redundant one, since the
   DataTables child row already visually separates the panel from the
   row above.
4. **Download buttons**: copy verbatim the current Original/Processed
   button markup (main row) and the feedback-document Download button
   markup (details panel, per Phase 5). Identify the CSS classes used for
   each and confirm which convention is the "correct"/established one to
   standardise on (the brief in this conversation specifically said the
   feedback-document buttons look unstyled relative to the rest of the
   panel — compare against the Original/Processed buttons' classes as the
   likely correct reference).
5. **Original vs. processed availability**: find the current logic
   determining whether a processed version of a report exists (the
   condition currently driving whether both "Original" and "Processed"
   buttons render, vs. just "Original"). Quote it verbatim.
6. **Existing modal conventions**: search the codebase for existing
   Bootstrap modal usage (`data-bs-toggle="modal"` / `.modal` markup) to
   find the established pattern for confirmation dialogs — reuse it
   rather than hand-rolling new modal markup/JS. Note in particular how
   any existing confirmation-before-download or similar irreversible-
   action modal is structured, if one exists anywhere in the app.

## Step 1 — Grade capsule in the right-hand column

- Below (or beside, per spacing) the existing large sortable "Report
  grade" number in the right-hand column, add a `.sv2-metric-cap.grades`
  capsule (per Step 0.1's CSS-location decision) listing all available
  grades via `grade_display_data()` — Supervision, Report, Presentation —
  in the same label/value/separator format as `submitters_v2.html`. Yes,
  this means Report grade appears both as the large headline number
  *and* inside the capsule alongside Supervision/Presentation — that
  duplication is intentional (the headline number is the sort key /
  at-a-glance figure, the capsule is the complete picture), not an error;
  state this explicitly in your recon output so it's not "fixed" as
  perceived redundancy.
- Remove the current plain-text supervision/presentation grade mention
  from the identity line in the main report panel (left column) — it
  moves to the capsule, not duplicated in two places.

## Step 2 — De-nest the details panel

- Per Step 0.3's findings, remove the redundant outer wrapper, leaving
  the DataTables child row's own boundary as the only outer separation,
  with the existing inner cards (report summary callout, stat tiles,
  risk-factor cards, AI declaration/compliance block from Phase 6) sitting
  directly in the child row's content area rather than inside an
  additional wrapping box.
- Confirm spacing/padding still reads correctly once the outer wrapper's
  padding is gone — the child row container itself may need its own
  padding applied directly if it previously relied on the now-removed
  wrapper for that.

## Step 3 — Download button styling

- Apply the established button convention from Step 0.4 consistently to
  both the Original/Processed buttons (main row) and the feedback
  document Download button(s) (details panel), so all download-style
  actions in this dashboard look like one coherent set rather than two
  different button styles.

## Step 4 — Processed-report-only display, with confirmation modal for originals

This is a behaviour change, not just styling — go carefully.

- Where a processed version of the report exists (per Step 0.5's
  condition): show a single download button (label "Download report" or
  similar — confirm appropriate wording, not necessarily "Processed"
  since it's now the only option) linking directly to the processed file.
  Do not show a separate "Original" button in this case.
- Where no processed version exists (original only): show a single
  download button, but clicking it opens a Bootstrap modal (per Step
  0.6's established pattern) warning that the report has not been
  processed and may contain unredacted occurrences of the student's
  name, with a clear "Download anyway" / "Cancel" choice. Only the
  confirm action triggers the actual download.
- This logic applies to the main row's report-download button(s) — confirm
  with Step 0.5 whether "Original"/"Processed" in the main row and any
  similar original/processed distinction elsewhere in this dashboard
  (e.g. feedback documents, if those also have an original/processed
  distinction — check, don't assume they don't) need the same treatment,
  or whether this is specific to the report file itself.
- Embargo interaction: confirm this new download/modal logic still
  respects `is_report_restricted` (per `recon.md` §11) — a restricted
  report's download options should remain suppressed exactly as before,
  this phase doesn't change embargo behaviour, just the non-restricted
  download UX.

## Step 5 — Verification

- Manually confirm (describe what you checked):
  - grade capsule renders correctly with all three grades, correctly
    showing `—` for any missing grade (matching `submitters_v2.html`'s
    `sv2-mv-dim` convention for `none`)
  - the headline Report grade column still sorts correctly (Step 1
    doesn't touch sort logic, just adds a display element)
  - details panel has one fewer level of nesting, content still reads
    correctly with appropriate spacing
  - download buttons are visually consistent across Original/Processed
    and feedback-document contexts
  - a report with a processed version available shows exactly one
    download button, no modal, immediate download
  - a report with only an original version shows exactly one button,
    clicking it opens the warning modal, cancel does not download,
    confirm does
  - a restricted report's download UI is unaffected by this phase (still
    suppressed per existing embargo logic)
- `grep` to confirm no leftover dual Original/Processed button markup in
  cases where only one button should now render.

## Out of scope

- Any further filter-bar work, restricted-row grade visibility, or
  project-class colour-coding — all still deferred per prior phases.
