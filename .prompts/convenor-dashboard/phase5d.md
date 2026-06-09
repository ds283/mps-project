# Phase 5d — Retire `periods.html`, fix header ordering, clean up status.html

**Prerequisite: Phases 5a, 5b, and 5c are complete and verified.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

This phase closes four remaining issues identified in the implementation review:

1. Retire `convenor/dashboard/periods.html` and replace all inbound links
2. Fix the header/pill ordering in `pclass_base.html` (header currently renders above
   the pill navigation instead of below it)
3. Remove the superseded configuration accordion block from `status.html`
4. Add `id` anchor attributes to `edit_project_config.html` and `edit_period_record.html`
   section headings so the configuration tile deep-links function correctly

---

## Step 1 — Read before writing

Read these files in full:

- `app/templates/convenor/dashboard/pclass_base.html` — confirm the current ordering
  of the header strip and `{{ super() }}` call within `pillblock`
- `app/templates/convenor/dashboard/nav.html` — confirm the `pillblock` structure and
  where the `<ul class="nav nav-pills">` is rendered
- `app/templates/convenor/dashboard/status.html` — locate the configuration accordion
  block (marked `{# [D] CONFIGURATION ACCORDION #}` at approximately line 129) and
  confirm its extent
- `app/templates/convenor/dashboard/edit_project_config.html` — locate every
  `<p class="form-group-heading">` element; these are the anchor targets
- `app/templates/convenor/dashboard/edit_period_record.html` — same
- `app/templates/convenor/dashboard/periods.html` — confirm it has no POST handling
  and no side effects (read-only)
- `app/templates/macros.html` lines 405–420 — confirm the two inbound links to
  `convenor.periods` identified in the Phase 0b checklist
- `app/templates/convenor/dashboard/overview_nav.html` — confirm the
  "Submission periods" tab link

The Phase 0b reconnaissance identified 10 inbound links to `convenor.periods`. Read
that list before proceeding.

---

## Step 2 — Fix header/pill ordering in `pclass_base.html`

**Problem:** The persistent header strip currently renders before `{{ super() }}` in
`pclass_base.html`'s `pillblock` override, placing it above the pill navigation. The
correct order is: pill navigation first (from `nav.html` via `super()`), then the
persistent header strip below it.

**Fix:** In `pclass_base.html`, within the `{% block pillblock %}` override, move the
persistent header `<div>` to appear **after** `{{ super() }}`, not before it.

The corrected structure should be:

```jinja
{% block pillblock %}
    {# Pills row from nav.html — rendered first #}
    {{ super() }}
    {# Persistent project-class header strip — rendered below the pills #}
    <div class="container-fluid px-3 py-2 border-bottom" ...>
        ...
    </div>
{% endblock %}
```

Preserve the header div content exactly — only the position of `{{ super() }}` changes.

---

## Step 3 — Remove configuration accordion from `status.html`

**Problem:** The old configuration accordion block (the large collapsible section
containing the pclass name, Resources/Configure/Workflow log/Settings buttons, and the
multi-column Configuration + Lifecycle events cards) was marked `{# [D] CONFIGURATION
ACCORDION #}` but not removed. This creates a duplicate of functionality now available
in the new configuration tile surface.

Locate the block in `status.html` that begins at approximately line 129 with:

```jinja
{# [D] CONFIGURATION ACCORDION — collapsed by default #}
<div class="card mt-3 mb-3 card-body border-primary bg-well">
```

And ends with the closing `</div>` of that outermost card (before the `{# 60/40 split #}`
section begins).

**Remove this entire block.** Do not replace it with anything.

After removal, confirm:

- The actions panel (`{{ action_panel(action_items) }}`) is still present
- The lifecycle action card (the `{% if lifecycle == ... %}` block) is still present
- The 60/40 split (`<div class="row g-3">`) follows immediately after the lifecycle card

---

## Step 4 — Add anchor `id` attributes to edit forms

The configuration tile surface links to specific sections of the edit forms using fragment
URLs (e.g. `url_for('convenor.edit_project_config', pid=config.id) + '#canvas'`). These
anchors currently have no corresponding `id` attributes in the target forms.

### `edit_project_config.html`

Add `id` attributes to these `<p class="form-group-heading">` elements:

| Current text                           | Add `id=`                 |
|----------------------------------------|---------------------------|
| `Settings` (project selection section) | `id="selection"`          |
| `Canvas integration`                   | `id="canvas"`             |
| `AI grading`                           | `id="ai"`                 |
| `Supervision and assessment`           | `id="supervision"`        |
| `Faculty dashboards`                   | `id="faculty-dashboards"` |
| `Workload model support`               | `id="cats"`               |
| `Document limits`                      | `id="limits"`             |

Change format: `<p class="form-group-heading">Settings</p>` →
`<p class="form-group-heading" id="selection">Settings</p>`

### `edit_period_record.html`

Add `id` attributes to the section structure. Since `edit_period_record.html` uses `<hr>`
dividers rather than heading elements, add a visually-hidden `<span>` anchor before each
logical section:

Before the date fields block:

```html
<span id="dates" class="visually-hidden"></span>
```

Before the `number_markers` / `uses_supervision_grade` fields:

```html
<span id="markers" class="visually-hidden"></span>
```

Before the Canvas integration section (guarded by `{% if config.main_config.enable_canvas_sync %}`):

```html
<span id="canvas" class="visually-hidden"></span>
```

Before the presentation-related fields (if present):

```html
<span id="presentation" class="visually-hidden"></span>
```

Read `edit_period_record.html` carefully to confirm the field order and section boundaries
before placing anchors.

---

## Step 5 — Retire `periods.html`

### 5a — Update all inbound links

Replace every occurrence of `url_for('convenor.periods', id=pclass.id)` (and variants)
with `url_for('convenor.status', id=pclass.id)` throughout templates and Python files.

The 10 locations identified in Phase 0b are:

1. `app/convenor/marking_feedback.py:545` — redirect after editing period record
2. `app/convenor/marking_feedback.py:592` — redirect after editing period presentation
3. `app/convenor/markingevent.py:3252` — default fallback URL argument
4. `app/convenor/markingevent.py:3281` — default fallback URL argument
5. `app/templates/macros.html:410` — return URL for `projecthub.edit_submission_period_articles`
6. `app/templates/macros.html:414` — return URL for `convenor.submission_period_documents`
7. `app/templates/convenor/dashboard/overview_nav.html:15` — "Submission periods" tab link
8. `app/templates/convenor/dashboard/status.html` — link in compact period table
9. `app/templates/convenor/dashboard/overview_cards/submitter_card.html:43`
10. `app/templates/convenor/dashboard/overview_cards/period_settings.html:72`

For item 7 (`overview_nav.html`): the "Submission periods" tab currently links to
`url_for('convenor.periods', id=pclass.id)`. Change it to
`url_for('convenor.status', id=pclass.id)`. The tab can be renamed to "Submission periods"
but it now navigates to the status page where the period cards live. Alternatively, if
the Status and Submission periods tabs now show the same content, consider whether
`overview_nav.html` should remove the "Submission periods" tab entirely. Make a note of
this decision but default to updating the link rather than removing the tab — tab removal
is a separate UX decision.

### 5b — Remove the `periods` view function

In `app/convenor/dashboard.py`, remove the `periods` view function and its route
decorator entirely. Confirm it has no POST handling before deleting.

### 5c — Delete the template

Delete `app/templates/convenor/dashboard/periods.html`.

---

## Step 6 — Verification

1. **Header ordering**: Load (or mentally render) a dashboard page and confirm `{{ super() }}`
   appears before the header `<div>` in `pclass_base.html`'s `pillblock`. The pill `<ul>`
   from `nav.html` must render first in the HTML output.

2. **Accordion removed**: Grep `status.html` for `dashboard-project-title` and for
   `config-detail-panel`. Both should return zero results — these are class names unique
   to the removed accordion.

3. **Anchor IDs present**: Grep `edit_project_config.html` for `id="canvas"`,
   `id="cats"`, `id="supervision"`, `id="selection"`, `id="ai"`, `id="limits"`. All six
   must be present.

4. **Period record anchors present**: Grep `edit_period_record.html` for
   `id="dates"`, `id="markers"`, `id="canvas"`, `id="presentation"`. All four must
   be present.

5. **`periods` view gone**: Grep `app/convenor/dashboard.py` for `def periods`. Must
   return zero results.

6. **`periods.html` gone**: Confirm
   `app/templates/convenor/dashboard/periods.html` does not exist.

7. **No remaining `convenor.periods` references**: Grep the entire `app/` directory for
   `convenor.periods`. Must return zero results. Any remaining result is a broken link
   that must be fixed before finishing.

8. **`status.html` structure intact**: Confirm in order:
    - `{{ action_panel(action_items) }}` is present
    - The lifecycle action card `{% if lifecycle == ... %}` block is present
    - The 60/40 split `<div class="row g-3">` follows
    - No `dashboard-project-title` or `config-detail-panel` references remain

Report the result of each check. Fix any failures before finishing.