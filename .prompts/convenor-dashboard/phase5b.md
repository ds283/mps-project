# Phase 5b — Roll out `pclass_base.html` to full-page convenor subtree templates

**Prerequisite: Phase 1 is complete. Phase 5a is complete and verified.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

Change every full-page `base_app.html` template in the non-dashboard convenor subtrees to
extend `pclass_base.html` instead, and patch the corresponding view functions to pass
`pclass`, `config`, and `convenor_data` where they are currently missing.

This phase covers Groups A, B, and C from the Phase 0b reconnaissance — all templates
that extend `base_app.html` (not `base_form.html`). Form templates are handled in Phase 5c.

---

## Step 1 — Read before writing

Read the Phase 0b reconnaissance output in full
(`/.prompts/convenor-dashboard/phase0b-reconnaissance.md`).

Then read the following source files to confirm the derivation paths before writing any
view-function changes:

- `app/convenor/marking_feedback.py` — full file
- `app/convenor/markingevent.py` — full file
- `app/convenor/submitters.py` — full file
- `app/convenor/selector_details.py` — full file
- `app/convenor/documents.py` — full file
- `app/shared/context/convenor_dashboard.py` — confirm the signature of
  `get_convenor_dashboard_data(pclass, config)` and its import path

Confirm for `selector_details.py` specifically: do `add_student_bookmark` and
`add_student_ranking` have access to a `config` object via the `sel` (SelectorStudent)
model? Check whether `SelectorStudent` has a `config` relationship returning a
`ProjectClassConfig`. If yes, derivation is `sel.config` / `sel.config.project_class`.
If no, flag these two views as Group D and exclude them from this phase.

---

## Step 2 — Template changes

For every template in the list below, change the single `extends` line:

```jinja
{# Before #}
{% extends "base_app.html" %}

{# After #}
{% extends "convenor/dashboard/pclass_base.html" %}
```

No other changes to these templates.

### Templates to update

**convenor/supervision_events/** (base_app.html subset only):

- `inspect_period_units.html`
- `inspect_template_events.html`
- `inspect_unit_event_templates.html`

**convenor/markingevent/** (all base_app.html templates):

- `add_workflow_attachment.html`
- `assessment_archive_inspector.html`
- `assign_moderator.html`
- `confirm_calculate_conflation.html`
- `confirm_complete_all.html`
- `confirm_push_event_to_canvas.html`
- `confirm_return_all.html`
- `conflation_report_emails.html`
- `conflation_reports_inspector.html`
- `enter_turnitin_score.html`
- `event_marking_workflows_inspector.html`
- `export_period_to_box.html`
- `marking_events_inspector.html`
- `marking_report_properties.html`
- `marking_reports_inspector.html`
- `marking_schemes_inspector.html`
- `period_marking_events_inspector.html`
- `push_cr_feedback_to_canvas.html`
- `push_cr_to_canvas.html`
- `reassign_marking_report.html`
- `resolve_risk_factors.html`
- `resolve_turnitin.html`
- `submitter_reports_inspector.html`

**convenor/feedback/**:

- `add_recipe_asset.html`
- `generate_feedback_form.html`
- `push_feedback_form.html`

**convenor/language_analysis/**:

- `clone_rubric.html`
- `rubric_manager.html`

**convenor/presentations/**:

- `audit.html`

**convenor/submitter/** (base_app.html subset):

- `canvas_missing_students.html`
- `delete_submitter.html`
- `delete_all_submitters.html`
- `edit_roles.html`

**convenor/selector/** (base_app.html subset — see Step 1 caveat for bookmarks/rankings):

- `project_bookmarks.html`
- `project_choices.html`
- `project_confirmations.html`
- `project_custom_offers.html`
- `project_new_offer.html`
- `selector_bookmarks.html`
- `selector_choices.html`
- `selector_confirmations.html`
- `selector_custom_offers.html`
- `selector_new_offer.html`
- `hints_list.html`
- `add_bookmark.html` _(only if Step 1 confirms `sel.config` exists)_
- `add_ranking.html` _(only if Step 1 confirms `sel.config` exists)_

**convenor/documents/**:

- `period_manager.html`

---

## Step 3 — View function patches

For each view function below, make exactly the changes described. In every case:

1. Add the import at the top of the file if not already present:
   ```python
   from app.shared.context.convenor_dashboard import get_convenor_dashboard_data
   ```

2. Derive `pclass` and `config` as shown, then add:
   ```python
   convenor_data = get_convenor_dashboard_data(pclass, config)
   ```

3. Add `convenor_data=convenor_data` to the `render_template_context` call.

Do not change any other logic in the view function.

---

### `app/convenor/marking_feedback.py`

**Group A — template change only (already has pclass + config + convenor_data):**
_(none in this file)_

**Group B — add `convenor_data` only (pclass + config already present):**

- `edit_period_record` — pclass and config already passed; add `convenor_data`
- `edit_period_presentation` — same
- `populate_markers` — same
- `remove_markers` — same
- `faculty_workload` — same
- `teaching_groups` — same

**Group C — derive pclass/config then add `convenor_data`:**

- `inspect_period_units`:
  ```python
  config = period.config
  pclass = config.project_class
  convenor_data = get_convenor_dashboard_data(pclass, config)
  ```

- `add_period_unit` — same pattern via `period`
- `edit_period_unit`:
  ```python
  config = unit.period.config
  pclass = config.project_class
  convenor_data = get_convenor_dashboard_data(pclass, config)
  ```

- `inspect_unit_event_templates` — same pattern via `unit.period`
- `add_unit_event_template` — same pattern via `unit.period`
- `edit_unit_event_template`:
  ```python
  config = template.unit.period.config
  pclass = config.project_class
  convenor_data = get_convenor_dashboard_data(pclass, config)
  ```

- `inspect_template_events` — same pattern via `template.unit.period`
- `close_period`:
  ```python
  config = period.config
  pclass = config.project_class
  convenor_data = get_convenor_dashboard_data(pclass, config)
  ```

- `audit_matches` — pclass is direct; derive config:
  ```python
  config = pclass.most_recent_config
  convenor_data = get_convenor_dashboard_data(pclass, config)
  ```
  Guard against `config is None` — if `most_recent_config` returns None, log a warning
  and redirect to `convenor.overview` with an error flash rather than crashing.

- `rubric_manager` — same pattern as `audit_matches`
- `clone_grading_rubric` — same pattern

---

### `app/convenor/markingevent.py`

**Group A (already has pclass + config + convenor_data):**

- `marking_events_inspector` — template change only, no view change
- `inspect_marking_schemes` — template change only, no view change

**Group B (pclass present, add config + convenor_data):**

- `add_marking_scheme`:
  ```python
  config = pclass.most_recent_config
  convenor_data = get_convenor_dashboard_data(pclass, config)
  ```
  Guard against `config is None` as above.

**Group C (derive config → pclass → convenor_data):**

For all remaining markingevent views where the route parameter is an event, workflow, or
record, the derivation pattern is:

```python
# event-rooted:
config = event.period.config
pclass = config.project_class
convenor_data = get_convenor_dashboard_data(pclass, config)

# workflow-rooted:
config = workflow.event.period.config
pclass = config.project_class
convenor_data = get_convenor_dashboard_data(pclass, config)

# record-rooted (SubmitterReport, MarkingReport):
config = record.period.config
pclass = config.project_class
convenor_data = get_convenor_dashboard_data(pclass, config)
```

Apply the appropriate pattern to each view. Read the function body to confirm the
primary object variable name before writing. Do not guess.

**Group D — exclude from this phase:**

- `generate_feedback`, `regenerate_single_feedback`, `regenerate_all_feedback`
- These render `feedback/generate_feedback_form.html` which is in the template list above.
  The template change (extends update) should still be applied, but do NOT add
  `get_convenor_dashboard_data` to these view functions until a separate design decision
  is made. Instead, pass a minimal stub:
  ```python
  convenor_data = {}
  ```
  and add a `{# TODO Phase 5b Group D: replace stub with real convenor_data #}` comment.
  The template change will not crash because `pclass_base.html` reads `convenor_data`
  keys with `convenor_data['selectors']` etc. — verify whether this raises KeyError on
  an empty dict. If it does, use `convenor_data.get('selectors', 0)` or equivalent
  defensive reads in `pclass_base.html` instead of modifying the view functions for
  Group D views.

---

### `app/convenor/submitters.py`

**Group A:**

- `canvas_missing_students` — template change only

**Group B:**

- `delete_submitter` — add `convenor_data`
- `delete_all_submitters` — add `convenor_data`
- `edit_roles` — add `convenor_data`
- `add_role` — add `convenor_data`
- `edit_role` — add `convenor_data`

---

### `app/convenor/selector_details.py`

**Group C (all views — pclass absent, derive from config):**

```python
pclass = config.project_class
convenor_data = get_convenor_dashboard_data(pclass, config)
```

Apply to all views that have `config` in scope. For `add_student_bookmark` and
`add_student_ranking`: if Step 1 confirmed `sel.config` exists, derive as:

```python
config = sel.config
pclass = config.project_class
convenor_data = get_convenor_dashboard_data(pclass, config)
```

If Step 1 found these views are Group D, apply the empty-dict stub and TODO comment
as described for Group D markingevent views above.

For `project_custom_offers` and `new_project_offer` where pclass derives from a project:
read the function body carefully to identify the correct derivation path before writing.

---

### `app/convenor/documents.py`

**Group C (all views):**

```python
config = period.config  # or attachment.period.config
pclass = config.project_class
convenor_data = get_convenor_dashboard_data(pclass, config)
```

Read each function body to identify the correct primary object before writing.

---

### `app/convenor/feedback_resources.py`

**Group C:**

For views where `pclass` is passed directly but `config` is not:

```python
config = pclass.most_recent_config
convenor_data = get_convenor_dashboard_data(pclass, config)
```

Guard against `config is None` as above.

---

## Step 4 — Verification

1. **Template extends audit**: Grep all nine subtree directories for
   `extends "base_app.html"`. The only remaining results should be templates explicitly
   excluded from this phase (Group D template exclusions, if any). List any unexpected
   results.

2. **Import audit**: Grep all five view files modified in Step 3 for
   `get_convenor_dashboard_data`. Confirm it appears in every file that was patched.

3. **`convenor_data` in render calls**: For each view function patched in Step 3, confirm
   `convenor_data=convenor_data` appears in its `render_template_context` call.

4. **Group D stubs**: Grep for `convenor_data = {}` and confirm the count matches the
   number of Group D view functions. Confirm each stub has the accompanying TODO comment.

5. **`pclass_base.html` defensive reads**: If the Group D stub approach requires defensive
   reads in `pclass_base.html`, list every `convenor_data[...]` access changed to
   `convenor_data.get(..., default)` and confirm the default values are sensible (0 for
   counts, None for optional items).

6. **`base_form.html` templates untouched**: Grep the nine subtrees for
   `extends "base_form.html"`. Confirm the count is unchanged from Phase 0b — none of
   these should have been modified in this phase (they are handled in Phase 5c).

Report the result of each check. If any check fails, fix it before finishing.