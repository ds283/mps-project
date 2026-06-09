# Stream 2 Phase 0: Config-form Reconnaissance

## Scope

Replace the two monolithic edit forms (`EditProjectConfigForm` / `EditPeriodRecordForm`) and their
routes with focused per-tile forms, one route and template per tile. The goal is that each "Edit →"
button on `configure.html` opens a single-topic form instead of scrolling a long page.

---

## Source-file inventory

| Artefact                                                        | File                                                             | Lines     |
|-----------------------------------------------------------------|------------------------------------------------------------------|-----------|
| `EditProjectConfigFormFactory`                                  | `app/convenor/forms.py`                                          | 467–628   |
| `EditPeriodRecordFormFactory`                                   | `app/convenor/forms.py`                                          | 451–458   |
| `PeriodRecordMixinFactory`                                      | `app/convenor/forms.py`                                          | 378–448   |
| `edit_project_config` route                                     | `app/convenor/marking_feedback.py`                               | 374–470   |
| `edit_period_record` route                                      | `app/convenor/marking_feedback.py`                               | 524–575   |
| `edit_period_presentation` route *(existing — no change)*       | `app/convenor/marking_feedback.py`                               | 578–627   |
| `edit_project_config.html`                                      | `app/templates/convenor/dashboard/edit_project_config.html`      | 135 lines |
| `edit_period_record.html`                                       | `app/templates/convenor/dashboard/edit_period_record.html`       | 70 lines  |
| `edit_period_presentation.html` *(existing — pattern template)* | `app/templates/convenor/dashboard/edit_period_presentation.html` | 33 lines  |
| `configure.html`                                                | `app/templates/convenor/dashboard/configure.html`                | 375 lines |
| Form base template                                              | `app/templates/convenor/dashboard/pclass_form.html`              | 27 lines  |

---

## A. Field-to-tile mapping

### Cycle-level — `EditProjectConfigForm`

| Field                              | Tile                   |
|------------------------------------|------------------------|
| `uses_supervisor`                  | **Roles & assessment** |
| `uses_marker`                      | **Roles & assessment** |
| `uses_moderator`                   | **Roles & assessment** |
| `uses_presentations`               | **Roles & assessment** |
| `display_marker`                   | **Roles & assessment** |
| `display_presentations`            | **Roles & assessment** |
| `CATS_supervision`                 | **Workload & CATS**    |
| `CATS_marking`                     | **Workload & CATS**    |
| `CATS_moderation`                  | **Workload & CATS**    |
| `CATS_presentation`                | **Workload & CATS**    |
| `skip_matching`                    | **Project selection**  |
| `requests_skipped`                 | **Project selection**  |
| `full_CATS`                        | **Project selection**  |
| `canvas_module_id` *(conditional)* | **Canvas integration** |
| `canvas_login` *(conditional)*     | **Canvas integration** |
| `grading_rubric`                   | **AI grading rubric**  |
| `word_limit_enabled`               | **Document limits**    |
| `word_limit`                       | **Document limits**    |
| `page_limit_enabled`               | **Document limits**    |
| `page_limit`                       | **Document limits**    |
| `word_count_tolerance`             | **Document limits**    |

All 20 fields are assigned. No unassigned / legacy-only fields.

### Per-period — `EditPeriodRecordForm` (via `PeriodRecordMixinFactory`)

| Field                                  | Tile                       |
|----------------------------------------|----------------------------|
| `name`                                 | **Dates & deadlines**      |
| `start_date`                           | **Dates & deadlines**      |
| `hand_in_date`                         | **Dates & deadlines**      |
| `number_markers`                       | **Markers per submission** |
| `uses_supervision_grade`               | **Markers per submission** |
| `canvas_module_id` *(conditional)*     | **Canvas assignment**      |
| `canvas_assignment_id` *(conditional)* | **Canvas assignment**      |

All 7 fields (5 always-present + 2 conditional) are assigned.

**Presentation assessment** — already fully handled by the existing `edit_period_presentation`
route / `EditSubmissionPeriodRecordPresentationsForm`. No new form needed for that tile.

---

## B. New form classes

All factories should live in `app/convenor/forms.py` alongside the existing factories.

### Cycle-level

| Class name                               | Factory?                                      | Fields                                                                                                              | Notable validators / dependencies                                                                                                 |
|------------------------------------------|-----------------------------------------------|---------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------|
| `EditConfigRolesForm`                    | No (plain class)                              | `uses_supervisor`, `uses_marker`, `uses_moderator`, `uses_presentations`, `display_marker`, `display_presentations` | All `BooleanField` — no cross-field deps                                                                                          |
| `EditConfigCATSFormFactory(config)`      | Yes                                           | `CATS_supervision`, `CATS_marking`, `CATS_moderation`, `CATS_presentation`                                          | `NotOptionalIf` references role flags — **see Risk §F-1**; uses `show_default_field` macro                                        |
| `EditConfigSelectionFormFactory(config)` | Yes                                           | `skip_matching`, `requests_skipped`, `full_CATS`                                                                    | `full_CATS`: `Optional` + `NumberRange(min=0)`; `requests_skipped` write-back logic in route                                      |
| `EditConfigCanvasFormFactory(config)`    | Yes (conditional fields)                      | `canvas_module_id`, `canvas_login`                                                                                  | `canvas_login` uses `partial(GetCanvasEnabledConvenors, config)` + `BuildCanvasLoginUserName`; only created when `canvas_enabled` |
| `EditConfigAIRubricFormFactory(config)`  | Yes                                           | `grading_rubric`                                                                                                    | `QuerySelectField` with `query_factory=lambda: _pclass_rubrics`, `allow_blank=True`, `get_label="label"`                          |
| `EditConfigDocLimitsFormFactory(config)` | Yes (for `word_count_tolerance` % conversion) | `word_limit_enabled`, `word_limit`, `page_limit_enabled`, `page_limit`, `word_count_tolerance`                      | GET: multiply stored fraction × 100; POST: divide by 100 before saving; show/hide JS                                              |

### Per-period

| Class name                             | Factory?                      | Fields                                     | Notable validators / dependencies                                                                   |
|----------------------------------------|-------------------------------|--------------------------------------------|-----------------------------------------------------------------------------------------------------|
| `EditPeriodDatesFormFactory(config)`   | Yes (for `_config` injection) | `name`, `start_date`, `hand_in_date`       | `start_date` / `hand_in_date`: `DateTimeField`, `format="%d/%m/%Y"`, `Optional()`; needs datepicker |
| `EditPeriodMarkersFormFactory(config)` | Yes                           | `number_markers`, `uses_supervision_grade` | `validate_number_markers` accesses `form._config.uses_marker` — factory injects `_config = config`  |
| `EditPeriodCanvasFormFactory(config)`  | Yes (conditional)             | `canvas_module_id`, `canvas_assignment_id` | Only created when `config.main_config.enable_canvas_sync`; both `Optional()`                        |

---

## C. New routes

All new routes live in `app/convenor/marking_feedback.py`.

Back-link target after successful POST (all routes):

- Cycle-level: `url_for("convenor.status", id=config.project_class.id)`
- Per-period: `url_for("convenor.status", id=config.project_class.id)`

Object loaded: cycle-level routes load `ProjectClassConfig` by `pid`;
per-period routes load `SubmissionPeriodRecord` by `pid` and derive `config = record.config`.

Both `edit_project_config` and `edit_period_record` share validation helpers that should be
reused as-is:

- Cycle-level: inline checks at lines 381–393 (convenor check + rollover check)
- Per-period: `_validate_submission_period(record, config)` at line 473

### Cycle-level routes

| Route name               | URL                                 | Methods   | Notes                                                                                   |
|--------------------------|-------------------------------------|-----------|-----------------------------------------------------------------------------------------|
| `edit_config_roles`      | `/edit_config_roles/<int:pid>`      | GET, POST | Plain `EditConfigRolesForm`                                                             |
| `edit_config_cats`       | `/edit_config_cats/<int:pid>`       | GET, POST | `EditConfigCATSFormFactory(config)`                                                     |
| `edit_config_selection`  | `/edit_config_selection/<int:pid>`  | GET, POST | `EditConfigSelectionFormFactory(config)`; replicate `requests_skipped` timestamp logic  |
| `edit_config_canvas`     | `/edit_config_canvas/<int:pid>`     | GET, POST | `EditConfigCanvasFormFactory(config)`; redirect with flash if `canvas_enabled` is False |
| `edit_config_ai_rubric`  | `/edit_config_ai_rubric/<int:pid>`  | GET, POST | `EditConfigAIRubricFormFactory(config)`                                                 |
| `edit_config_doc_limits` | `/edit_config_doc_limits/<int:pid>` | GET, POST | `EditConfigDocLimitsFormFactory(config)`; % conversion in GET + POST                    |

### Per-period routes

| Route name            | URL                              | Methods   | Notes                                                                            |
|-----------------------|----------------------------------|-----------|----------------------------------------------------------------------------------|
| `edit_period_dates`   | `/edit_period_dates/<int:pid>`   | GET, POST | `EditPeriodDatesFormFactory(config)`                                             |
| `edit_period_markers` | `/edit_period_markers/<int:pid>` | GET, POST | `EditPeriodMarkersFormFactory(config)`                                           |
| `edit_period_canvas`  | `/edit_period_canvas/<int:pid>`  | GET, POST | `EditPeriodCanvasFormFactory(config)`; redirect with flash if canvas not enabled |

### Existing route (no change)

| Route name                 | URL                                   | Pattern source                              |
|----------------------------|---------------------------------------|---------------------------------------------|
| `edit_period_presentation` | `/edit_period_presentation/<int:pid>` | already exists in `marking_feedback.py:578` |

---

## D. New templates

All new templates should extend `convenor/dashboard/pclass_form.html`
(not `base_form.html`, which is what the old `edit_project_config.html` uses — the per-period
templates and `edit_period_presentation.html` already use `pclass_form.html` and that is the
correct pattern).

| Template path                                    | Special rendering requirements                                                                                                                             |
|--------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `convenor/dashboard/edit_config_roles.html`      | None — all BooleanField rows                                                                                                                               |
| `convenor/dashboard/edit_config_cats.html`       | Use `show_default_field` macro (import from `macros.html`)                                                                                                 |
| `convenor/dashboard/edit_config_selection.html`  | None                                                                                                                                                       |
| `convenor/dashboard/edit_config_canvas.html`     | Guard: render fields only when `config.main_config.enable_canvas_sync`; otherwise informational message                                                    |
| `convenor/dashboard/edit_config_ai_rubric.html`  | None                                                                                                                                                       |
| `convenor/dashboard/edit_config_doc_limits.html` | JS show/hide for `config-word-limit-field` / `config-page-limit-field` (copy from existing `edit_project_config.html:114–129`); `show_default_field` macro |
| `convenor/dashboard/edit_period_dates.html`      | Import datepicker (`datepicker.html`), init two pickers (`datetimepicker1`, `datetimepicker2`) — mirror `edit_period_record.html`                          |
| `convenor/dashboard/edit_period_markers.html`    | None                                                                                                                                                       |
| `convenor/dashboard/edit_period_canvas.html`     | Guard for canvas-not-enabled; otherwise two `IntegerField` rows                                                                                            |

---

## E. Files and references to remove / update in Phase 5

### Code to delete (do NOT delete the whole file — only these items)

| Item                                    | File                               | Lines   |
|-----------------------------------------|------------------------------------|---------|
| `PeriodRecordMixinFactory` function     | `app/convenor/forms.py`            | 378–448 |
| `EditPeriodRecordFormFactory` function  | `app/convenor/forms.py`            | 451–458 |
| `EditProjectConfigFormFactory` function | `app/convenor/forms.py`            | 467–628 |
| `edit_project_config` route function    | `app/convenor/marking_feedback.py` | 374–470 |
| `edit_period_record` route function     | `app/convenor/marking_feedback.py` | 524–575 |

### Templates to delete

- `app/templates/convenor/dashboard/edit_project_config.html`
- `app/templates/convenor/dashboard/edit_period_record.html`

### `configure.html` link updates

| Current line | Current target                       | New target                                       |
|--------------|--------------------------------------|--------------------------------------------------|
| 9            | `edit_project_config` (escape hatch) | **Remove** this button (tiles make it redundant) |
| 51           | `edit_project_config#supervision`    | `edit_config_roles`                              |
| 79           | `edit_project_config#cats`           | `edit_config_cats`                               |
| 104          | `edit_project_config#selection`      | `edit_config_selection`                          |
| 127          | `edit_project_config#canvas`         | `edit_config_canvas`                             |
| 148          | `edit_project_config#ai`             | `edit_config_ai_rubric`                          |
| 174          | `edit_project_config#limits`         | `edit_config_doc_limits`                         |
| 294          | `edit_period_record#dates`           | `edit_period_dates`                              |
| 314          | `edit_period_record#markers`         | `edit_period_markers`                            |
| 339          | `edit_period_record#presentation`    | `edit_period_presentation` *(existing route)*    |
| 362          | `edit_period_record#canvas`          | `edit_period_canvas`                             |

### `macros.html` updates (lines 388–419 — `submission_period_configure_button` macro)

| Current line | Current target                                     | New target                      |
|--------------|----------------------------------------------------|---------------------------------|
| 392          | `edit_period_record` (main "Configure..." button)  | `edit_period_dates`             |
| 402          | `edit_period_record` (dropdown "Settings..." item) | `edit_period_dates`             |
| 406          | `edit_period_presentation`                         | *(no change — already correct)* |

---

## F. Risks and open questions

### F-1 — `NotOptionalIf` validators in CATS tile span a missing sibling field

In `EditProjectConfigFormFactory`, `CATS_supervision` carries `NotOptionalIf("uses_supervisor")`.
This validator walks the form to find a sibling field named `uses_supervisor`. In the new
`EditConfigCATSForm`, that sibling does not exist — the roles fields are on a different form.

**Decision needed before implementation:** Change CATS validators to `Optional()` (relying on
the config object's role flags for downstream logic) or derive a conditional `InputRequired`
in the route based on `config.uses_supervisor`. Recommended: use `Optional()` in the form
definition and add a view-level check that flashes an error if a CATS field is blank when
its corresponding role is enabled.

### F-2 — `requests_skipped` compound write logic

Setting `requests_skipped=True` also stamps `requests_skipped_id` and
`requests_skipped_timestamp`; setting it False clears them. This logic is currently in the
`edit_project_config` route (lines 416–421) and must be replicated in `edit_config_selection`.

### F-3 — `word_count_tolerance` percentage conversion

Stored as a fraction (e.g. `0.15`), displayed as a percentage (`15.0`). The GET/POST
conversion lives in the route (lines 401–403 and 443). Must be replicated in
`edit_config_doc_limits`.

### F-4 — Canvas tile when Canvas not enabled

The `canvas_module_id` / `canvas_login` fields are conditionally absent from the form when
`canvas_enabled=False`. The `edit_config_canvas` route should return a flash + redirect rather
than rendering an empty form if Canvas sync is off for the tenant. Same pattern for
`edit_period_canvas`.

### F-5 — `edit_project_config.html` uses `base_form.html`, not `pclass_form.html`

The monolithic template extends `base_form.html` (which extends the global base layout directly).
All new focused templates must extend `pclass_form.html` instead, which extends
`pclass_base.html` and provides the convenor sidebar and tab navigation. This aligns with
`edit_period_record.html` and `edit_period_presentation.html`.

### F-6 — `configure.html:339` currently links to `edit_period_record#presentation`

The "Presentation assessment" tile in `configure.html` (line 339) points to
`edit_period_record#presentation`, but the `#presentation` anchor in the old template is just
a heading + `<hr>` — there are no form fields under it. In Phase 5, this link must become
`edit_period_presentation`.

### F-7 — `GradingRubric` attribute used for display

The form uses `get_label="label"` for the grading rubric select, but `configure.html:143`
renders `config.grading_rubric.name`. Minor inconsistency in the display tile only; the new
form template should use the model's display attribute consistently.

### F-8 — `submission_period_configure_button` macro used beyond `configure.html`

The macro at `macros.html:388` is used in other parts of the codebase (e.g. lifecycle views,
period header cards). After Phase 5, the "Configure..." / "Settings..." dropdown items in this
macro must point to `edit_period_dates`, not the deleted `edit_period_record`. A codebase-wide
search for uses of `submission_period_configure_button` should be done before Phase 5
to confirm the full impact.
