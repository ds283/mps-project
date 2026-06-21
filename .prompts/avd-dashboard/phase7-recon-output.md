# Phase 7 — AVD dashboard: Recon output

## Step 0.1 — Grade capsule CSS location and decision

**Location:** `app/templates/convenor/dashboard/submitters_v2.html`, lines 122–143, inside a
`<style>` block scoped to that template.

**Rules in scope:**
```
.sv2-metrics-row           — flex row container for capsule group
.sv2-metric-cap            — outer capsule shell (border-radius, overflow, border)
.sv2-metric-cap.attendance — attendance-variant border colour
.sv2-metric-cap.grades     — grades-variant border colour
.sv2-metric-cap-label      — header label strip (font, padding)
.sv2-metric-cap.attendance .sv2-metric-cap-label — info tokens
.sv2-metric-cap.grades .sv2-metric-cap-label     — success tokens
.sv2-metric-cap-body       — flex row for items
.sv2-metric-cap.attendance .sv2-metric-cap-body  — info bg
.sv2-metric-cap.grades .sv2-metric-cap-body      — success bg
.sv2-m-item                — individual metric cell (padding, text-align)
.sv2-m-sep                 — 1px separator between cells
.sv2-metric-cap.attendance .sv2-m-sep — info border colour
.sv2-metric-cap.grades .sv2-m-sep     — success border colour
.sv2-m-lbl                 — label text (tiny, uppercase)
.sv2-metric-cap.attendance .sv2-m-lbl — info colour
.sv2-metric-cap.grades .sv2-m-lbl     — success colour
.sv2-m-val                 — value text (large, semibold)
.sv2-mv-ok                 — success-emphasis colour
.sv2-mv-warn               — danger-emphasis colour
.sv2-mv-dim                — border-color (for "—" placeholder)
```

All rules use Bootstrap 5.3 CSS custom property tokens only — no hardcoded hex values, no
submitters_v2-local context or variables.

**Decision: Hoist to `common.css`.** These rules are purely token-driven and have no
dependency on anything local to `submitters_v2.html`. Sharing one definition across both
templates is correct per the existing CSS-token-discipline convention (no divergent UI
elements for the same concept). After hoisting, remove the block from `submitters_v2.html`.

## Step 0.2 — `grade_display_data()` return shape

**Location:** `app/models/submissions.py:2297`.

Returns a list of dicts:
```python
[
  {"label": "Supervision", "grade": float|None, "event_name": str|None, "event_timestamp": datetime|None},
  {"label": "Report",      "grade": float|None, ...},
  {"label": "Presentation","grade": float|None, ...},
]
```

Each entry is **always included** (not omitted when grade is None) — the template renders
`sv2-mv-dim` with `&mdash;` for None values. Entries are gated by
`period.supervision_grade_available` / `report_grade_available` / `presentation_grade_available`,
so a period that doesn't have a presentation component will omit that entry. All three included
in one call, no reshaping needed.

**Intentional duplication**: Report grade will appear both as the large headline number in the
right-hand column header (the sort key / at-a-glance figure) *and* inside the capsule
alongside Supervision/Presentation (the complete picture). This is by design, not a redundancy
to "fix".

## Step 0.3 — Details panel wrapper (current structure)

`_details` (reports.py line 325) opens with:
```html
<div class="p-3" style="background: var(--bs-tertiary-bg); border-radius: 6px; border: 1px solid var(--bs-border-color)">
    ...all content...
</div>
```

This outer coloured/bordered box wraps the entire details panel. Inside it are:
- The report-summary callout div (its own `background: var(--bs-info-bg-subtle)`, border)
- A `<div class="row g-4">` two-column layout containing:
  - Left col: metric tiles, AI declaration box (each with their own bg/border)
  - Right col: risk-factor cards (each with their own bg/border), feedback links

The DataTables child row already provides the visual separation row from the parent row above.
The outer wrapper is redundant — all real visual work is done by the inner cards.

**Fix**: replace the outer `<div class="p-3" style="...">` with a plain `<div class="p-3">`
(padding only, no background or border). Content spacing still reads correctly because each
inner section has its own visual container; the `p-3` padding ensures content doesn't touch
the DataTables child-row boundary.

## Step 0.4 — Download button classes and convention

Main row (`_report` template, lines 257–268):
- **Original**: `class="btn btn-xs btn-outline-primary"` + `fa-file-download` icon
- **Processed**: `class="btn btn-xs btn-outline-secondary"` + `fa-file-pdf` icon

Details panel (`_details` template, line 453):
- **Feedback docs**: `class="btn btn-xs btn-outline-primary"` + `fa-file-pdf` icon

Original and feedback both use `btn-outline-primary`; Processed uses `btn-outline-secondary`.
After Step 4 consolidates to a single report-download button, the convention to standardise on
is `btn btn-xs btn-outline-secondary` for all download actions — downloading is a secondary
action and `btn-outline-secondary` is less visually prominent than `btn-outline-primary`, which
reserves the "primary" emphasis for navigation / open-page actions.

## Step 0.5 — Original vs processed availability condition

In `_report` template (lines 251–273), the current logic:
```jinja2
{% if record.report_secret %}
    {# secret restriction message #}
{% elif record.is_report_restricted %}
    {# embargo restriction message #}
{% else %}
    {% if record.report is not none %}
        {# Original button #}
    {% endif %}
    {% if record.processed_report is not none %}
        {# Processed button #}
    {% endif %}
    {% if record.report is none and record.processed_report is none %}
        {# No report badge #}
    {% endif %}
{% endif %}
```

Condition for "processed version exists": `record.processed_report is not none`.

**New behaviour (Step 4)**:
- `record.processed_report is not none` → single "Download report" button → direct link to
  processed file, no modal
- `record.processed_report is none and record.report is not none` → single "Download report"
  button → triggers `#avdUnprocessedReportModal` warning modal; confirm link href set via JS
- Both None → "No report" badge
- `record.report_secret` or `record.is_report_restricted` → restriction messages as before
  (unaffected by this phase)

**Feedback documents**: `_feedback_links()` returns only generated asset links (already
processed PDFs). No original/processed distinction exists for feedback documents; no modal
needed there.

**Embargo interaction**: the `{% if record.report_secret %} / {% elif record.is_report_restricted %}`
guard at the top of the download-button block remains unchanged. A restricted report's download
UI continues to be fully suppressed by that guard — Step 4 only changes the non-restricted
branch.

## Step 0.6 — Bootstrap modal conventions

From `marking_reports_inspector.html` (line 337):
```html
<div class="modal fade" id="someModal" tabindex="-1"
     aria-labelledby="someModalLabel" aria-hidden="true">
    <div class="modal-dialog">
        <div class="modal-content">
            <div class="modal-header bg-warning">
                <h5 class="modal-title" id="someModalLabel">...</h5>
                <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">...</div>
            <div class="modal-footer">
                <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                <form method="POST" ...>{{ form.hidden_tag() }}<button type="submit">Action</button></form>
            </div>
        </div>
    </div>
</div>
```

Trigger buttons use `data-bs-toggle="modal" data-bs-target="#modalId"`. For this phase, the
confirm action is a GET (file download), so the confirm button is an `<a>` styled as a button
with `data-bs-dismiss="modal"` — no POST form needed.

**Strategy for per-row download modal**: the `_report` string template is compiled and rendered
per row in AJAX responses, so the modal HTML cannot live there. Instead:
1. A single `#avdUnprocessedReportModal` lives in `avd_dashboard.html`
2. Trigger buttons in the row template carry `data-download-url="..."` attributes
3. `avd_dashboard.html`'s `document.ready` JS listens for `show.bs.modal` on
   `#avdUnprocessedReportModal` and sets the confirm `<a>`'s href from the triggering
   button's `data-download-url`
