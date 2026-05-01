You are working in the MPS-Project Flask/SQLAlchemy application. This task adds a UI for managing `GradingRubric`,
`RubricBand`, and `RubricCriterion` instances. The underlying models were added in a previous step and already exist.

Read the following files in full before making any changes:

- `app/templates/convenor/dashboard/resources.html` — the resources grid; you will add a card here
- `app/templates/convenor/marking_schemes/inspector.html` — the pattern to follow for resource editor pages
- `app/templates/convenor/selectors/selector_bookmarks.html` — the SortableJS pattern to follow
- `app/models/language_pipeline.py` — to understand `GradingRubric`, `RubricBand`, `RubricCriterion`
- `app/views/convenor.py` — to understand routing conventions, how `pclass_id`, `url`, and `text` breadcrumb parameters
  are handled, and where to register new routes

---

## Part 1 — Resources grid

In `app/templates/convenor/dashboard/resources.html`, add a new `resource_card()` call inside the existing
`{% call resource_grid() %}` block:

- Icon: `fas fa-graduation-cap fa-fw text-primary`
- Title: `Grading rubric`
- Description: `Configure the AI grading rubric used to assess student reports.`
- URL:
  `url_for('convenor.grading_rubric', pclass_id=pclass.id, url=url_for('convenor.resources', pclass_id=pclass.id), text='Resources manager')`

Place it after the Feedback documents card. No other changes to this file.

---

## Part 2 — Templates

Create all new templates under `app/templates/convenor/language_analysis/`.

### `rubric_manager.html`

This is the landing page for the grading rubric. Model it structurally on
`app/templates/convenor/marking_schemes/inspector.html`: extend `base_app.html`, show an `alert-info` block at the top,
a back-navigation button using the `url`/`text` breadcrumb parameters, and a `card border-primary` containing the main
content.

Inside the card:

- If `pclass_config.grading_rubric` is `None`: show a short explanatory paragraph that no rubric is currently configured
  and that LLM grading will be skipped for this project class. Provide a single button: `+ Create rubric`, which POSTs
  to `convenor.create_grading_rubric`.
- If `pclass_config.grading_rubric` is not `None`: show the rubric editor inline (see below). Do not use a separate
  editor page — the editor lives directly in this template.

### Inline rubric editor (within `rubric_manager.html`)

The editor manages bands and criteria inline without page reloads, using SortableJS for reordering and standard form
submissions for text edits and deletions.

**Rubric label:** render an inline editable `<input>` for `grading_rubric.label` at the top of the card body, above the
bands. Changing this field and clicking Save submits a POST to `convenor.edit_grading_rubric_label`.

**Band list:** render each `RubricBand` (ordered by `position`) as a Bootstrap card nested inside the outer card. Each
band card has:

- A drag handle (`<i class="fas fa-bars drag-handle"></i>`) on the left of the card header
- An inline editable `<input>` for `band.label` in the card header
- A Save button for the band label that POSTs to `convenor.edit_rubric_band`
- A Delete button (danger, outline) in the card header that POSTs to `convenor.delete_rubric_band`; show only if the
  band has no criteria
- The criteria list in the card body (see below)
- An `+ Add criterion` button at the bottom of the card body that POSTs to `convenor.add_rubric_criterion`

**Criterion rows:** within each band card body, render each `RubricCriterion` (ordered by `position`) as a flex row
containing:

- A drag handle (`<i class="fas fa-bars drag-handle me-2"></i>`)
- A tag badge: a small `<span>` styled as a Bootstrap badge. Use `bg-secondary` for `plain`, `bg-danger` for `negative`,
  `bg-success` for `positive_floor`. Display text: `—`, `negative`, `positive floor` respectively.
- An inline editable `<input class="form-control form-control-sm">` for `criterion.text`
- A Save button (small, outline-primary) that POSTs to `convenor.edit_rubric_criterion`
- A cycle-tag button (small, outline-secondary, labelled `cycle tag`) that POSTs to
  `convenor.cycle_rubric_criterion_tag`
- A Delete button (small, outline-danger) that POSTs to `convenor.delete_rubric_criterion`

**Footer:** below the band list, two buttons:

- `+ Add band` — POSTs to `convenor.add_rubric_band`
- `Clone from another project class` — links to `convenor.clone_grading_rubric` (GET, opens a simple form page)

**Tag legend:** a small `<p class="text-body-secondary">` below the footer explaining the three tag values.

### `clone_rubric.html`

A simple form page (extend `base_app.html`, same card/breadcrumb skeleton). Contains a single `<select>` listing all
`ProjectClass` instances that have a `GradingRubric` configured, excluding the current one. On submit, POSTs to
`convenor.clone_grading_rubric`. Include a Cancel link back to `convenor.grading_rubric`.

---

## Part 3 — SortableJS reordering

Follow the pattern in `app/templates/convenor/selectors/selector_bookmarks.html` exactly, including the
`import_sortable()` macro, `$.ajaxSetup` CSRF header, debounced `sendAjax`, and `onEnd` early-exit guard.

Create **two** `Sortable` instances in `rubric_manager.html`:

1. **Band reordering** — on the container element wrapping all band cards. `onEnd` POSTs the ordered list of band
   `data-id` values to `convenor.reorder_rubric_bands`.
2. **Criterion reordering within each band** — one `Sortable` instance per band card body, initialised in a loop over
   `document.querySelectorAll('.criterion-list')`. Use SortableJS `group` option with the same group name (e.g.
   `'criteria'`) on all criterion lists to allow drag-across-bands. `onEnd` POSTs the ordered list of criterion
   `data-id` values and the destination `band_id` (read from the container's `data-band-id` attribute) to
   `convenor.reorder_rubric_criteria`.

Use separate debounce timers for band reordering and criterion reordering (`_bandSaveTimer`, `_critSaveTimer`).

All drag handles use class `drag-handle`. SortableJS `handle` option should be set to `'.drag-handle'`.

---

## Part 4 — Routes and view functions

Add the following routes to `app/views/convenor.py`. Follow existing routing conventions precisely (decorator style,
`pclass_id` parameter, `url`/`text` breadcrumb passthrough, `login_required`, role checks).

All POST endpoints that mutate data should:

- Validate the CSRF token via `$.ajaxSetup` (already handled client-side via `X-CSRFToken` header; use
  `flask_wtf.csrf.validate_csrf` server-side for the JSON endpoints, or an empty `FlaskForm` for form POST endpoints)
- Return appropriate redirects or JSON `{"status": "ok"}` responses as fits the request type
- Use `db.session.commit()` after mutations
- Flash an error and redirect cleanly on validation failure

### Routes

`GET convenor.grading_rubric(pclass_id, url, text)`

- Loads `ProjectClass` by `pclass_id`; finds the active `ProjectClassConfig`; passes `pclass`, `pclass_config`, `url`,
  `text` to `rubric_manager.html`
- Also pass `form=ReorderForm()` for CSRF token

`POST convenor.create_grading_rubric(pclass_id)`

- Creates a new empty `GradingRubric` with `label="Default"` attached to the active `ProjectClass`
- Redirects to `convenor.grading_rubric`

`POST convenor.edit_grading_rubric_label(rubric_id)`

- Updates `GradingRubric.label`; redirects back

`POST convenor.add_rubric_band(rubric_id)`

- Appends a new `RubricBand` with `label="New band"` and `position` = current max + 1
- Redirects back

`POST convenor.edit_rubric_band(band_id)`

- Updates `RubricBand.label`; redirects back

`POST convenor.delete_rubric_band(band_id)`

- Deletes band only if it has no criteria; flashes error otherwise; redirects back

`POST convenor.reorder_rubric_bands(rubric_id)` — JSON endpoint

- Accepts `{"ranking": ["12", "7", "3"]}` (bare integer strings, no prefix)
- Updates `RubricBand.position` for each band using a single `CASE` expression (see below); returns `{"status": "ok"}`

`POST convenor.add_rubric_criterion(band_id)`

- Appends a new `RubricCriterion` with `text="New criterion"`, `tag="plain"`, `position` = current max + 1
- Redirects back

`POST convenor.edit_rubric_criterion(criterion_id)`

- Updates `RubricCriterion.text`; redirects back

`POST convenor.delete_rubric_criterion(criterion_id)`

- Deletes criterion; redirects back

`POST convenor.cycle_rubric_criterion_tag(criterion_id)`

- Cycles `tag` through `plain` → `negative` → `positive_floor` → `plain`; redirects back

`POST convenor.reorder_rubric_criteria(band_id)` — JSON endpoint

- Accepts `{"ranking": ["5", "2", "8"], "band_id": "3"}`
- Reassigns `criterion.band_id` to `band_id` for all listed criteria (supports cross-band drops)
- Updates `RubricCriterion.position` using a single `CASE` expression; returns `{"status": "ok"}`

`GET/POST convenor.clone_grading_rubric(pclass_id)`

- GET: renders `clone_rubric.html` with list of `ProjectClass` instances that have a rubric configured
- POST: calls `source_rubric.clone_to(target_pclass_config)`, commits, redirects to `convenor.grading_rubric`

### Bulk position update pattern

For both reorder endpoints, update positions using a `CASE` expression rather than a per-row loop, to avoid any
transient uniqueness issues:

```python
from sqlalchemy import case

cases = [when(Model.id == int(pk), then=i) for i, pk in enumerate(ordered_ids)]
db.session.execute(
    update(Model).where(Model.id.in_([int(pk) for pk in ordered_ids]))
    .values(position=case(*cases))
)
db.session.commit()
```

---

## Constraints

- Do not modify any existing routes, templates, or models beyond the specific additions described above.
- Do not add JavaScript beyond what is described; no inline React, no fetch-based dynamic rendering.
- All new templates must extend `base_app.html` and follow the existing Bootstrap 5 / Font Awesome conventions visible
  in the reference templates.
- The `import_sortable()` macro is already defined in `sortable.html`; use it, do not inline the CDN script tag.
- The `ReorderForm` empty `FlaskForm` subclass should be placed in the appropriate forms file following existing
  conventions; check whether it already exists before creating it.

## Verification

After making all changes:

1. Confirm the new `resource_card` appears in `resources.html` and the `url_for` target matches the new route name
   exactly.
2. Confirm every route referenced in templates with `url_for` has a corresponding registered view function.
3. Confirm both `Sortable` instances use `handle: '.drag-handle'` and `onEnd` with an `oldIndex === newIndex` early-exit
   guard.
4. Confirm neither reorder endpoint uses a per-row update loop.
5. Confirm `clone_to` is called on the source `GradingRubric` instance, not reimplemented inline.