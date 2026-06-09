# Phase 0b Reconnaissance: Non-dashboard convenor template subtrees

## Task 1 — Template inventory

### Reference: `convenor/dashboard/pclass_base.html`

Extends `convenor/dashboard/nav.html`. Overrides `pillblock` to render the persistent header
(breadcrumb, year badge, lifecycle chip, key metrics, action buttons) then calls `{{ super() }}`
to include the `tabblock` pill row from `nav.html`.

---

### supervision_events/

| Template path                                        | Extends        | Blocks defined                          | Already uses dashboard? | AJAX/modal? |
|------------------------------------------------------|----------------|-----------------------------------------|-------------------------|-------------|
| supervision_events/edit_period_unit.html             | base_form.html | form_content, formtitle, scripts, title | No                      | No          |
| supervision_events/edit_unit_event_template.html     | base_form.html | form_content, formtitle, title          | No                      | Small form  |
| supervision_events/inspect_period_units.html         | base_app.html  | bodyblock, scripts, title               | No                      | No          |
| supervision_events/inspect_template_events.html      | base_app.html  | bodyblock, scripts, title               | No                      | No          |
| supervision_events/inspect_unit_event_templates.html | base_app.html  | bodyblock, scripts, title               | No                      | No          |

---

### markingevent/

| Template path                                       | Extends        | Blocks defined                                          | Already uses dashboard? | AJAX/modal? |
|-----------------------------------------------------|----------------|---------------------------------------------------------|-------------------------|-------------|
| markingevent/add_workflow_attachment.html           | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/assessment_archive_inspector.html      | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/assign_moderator.html                  | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/confirm_calculate_conflation.html      | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/confirm_complete_all.html              | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/confirm_push_event_to_canvas.html      | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/confirm_return_all.html                | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/conflation_report_emails.html          | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/conflation_reports_inspector.html      | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/edit_marking_event.html                | base_form.html | footer, form_content, formtitle, header, scripts, title | No                      | No          |
| markingevent/edit_marking_scheme.html               | base_form.html | footer, form_content, formtitle, scripts, title         | No                      | No          |
| markingevent/edit_marking_workflow.html             | base_form.html | footer, form_content, formtitle, scripts, title         | No                      | No          |
| markingevent/enter_turnitin_score.html              | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/event_marking_workflows_inspector.html | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/export_period_to_box.html              | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/marking_events_inspector.html          | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/marking_report_properties.html         | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/marking_reports_inspector.html         | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/marking_schemes_inspector.html         | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/period_marking_events_inspector.html   | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/push_cr_feedback_to_canvas.html        | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/push_cr_to_canvas.html                 | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/reassign_marking_report.html           | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/resolve_risk_factors.html              | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/resolve_turnitin.html                  | base_app.html  | bodyblock, title                                        | No                      | No          |
| markingevent/submitter_reports_inspector.html       | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| markingevent/test_marking_event.html                | base_form.html | form_content, formtitle, scripts, title                 | No                      | No          |
| markingevent/test_send_reminder_for_workflow.html   | base_form.html | form_content, formtitle, scripts, title                 | No                      | No          |

---

### feedback/

| Template path                        | Extends        | Blocks defined                                          | Already uses dashboard? | AJAX/modal? |
|--------------------------------------|----------------|---------------------------------------------------------|-------------------------|-------------|
| feedback/add_feedback_asset.html     | base_form.html | form_content, formtitle, header, title                  | No                      | Small form  |
| feedback/add_recipe_asset.html       | base_app.html  | bodyblock, title                                        | No                      | No          |
| feedback/edit_feedback_asset.html    | base_form.html | form_content, formtitle, header, title                  | No                      | Small form  |
| feedback/feedback_recipe.html        | base_form.html | footer, form_content, formtitle, header, scripts, title | No                      | No          |
| feedback/feedback_template.html      | base_form.html | form_content, formtitle, header, scripts, title         | No                      | No          |
| feedback/generate_feedback_form.html | base_app.html  | bodyblock, scripts, title                               | No                      | No          |
| feedback/push_feedback_form.html     | base_app.html  | bodyblock, title                                        | No                      | No          |

---

### marking/

| Template path                 | Extends        | Blocks defined                                                             | Already uses dashboard? | AJAX/modal? |
|-------------------------------|----------------|----------------------------------------------------------------------------|-------------------------|-------------|
| marking/populate_markers.html | base_form.html | form_content, formtitle, scripts, title                                    | No                      | No          |
| marking/remove_markers.html   | base_form.html | card_classes, card_header_classes, form_content, formtitle, scripts, title | No                      | No          |

(Other marking/ templates — close_period.html, edit_period_record.html,
edit_period_presentation.html, faculty_workload.html, teaching_groups.html, manual_assign.html
— are rendered by marking_feedback.py and follow the same base_app.html / base_form.html
pattern.)

---

### language_analysis/

| Template path                         | Extends       | Blocks defined            | Already uses dashboard? | AJAX/modal? |
|---------------------------------------|---------------|---------------------------|-------------------------|-------------|
| language_analysis/clone_rubric.html   | base_app.html | bodyblock, title          | No                      | No          |
| language_analysis/rubric_manager.html | base_app.html | bodyblock, scripts, title | No                      | No          |

---

### presentations/

| Template path            | Extends       | Blocks defined            | Already uses dashboard? | AJAX/modal? |
|--------------------------|---------------|---------------------------|-------------------------|-------------|
| presentations/audit.html | base_app.html | bodyblock, scripts, title | No                      | No          |

---

### submitter/

| Template path             | Extends        | Blocks defined            | Already uses dashboard? | AJAX/modal? |
|---------------------------|----------------|---------------------------|-------------------------|-------------|
| submitter/add_role.html   | base_form.html | bodyblock, scripts, title | No                      | No          |
| submitter/edit_role.html  | base_form.html | bodyblock, scripts, title | No                      | No          |
| submitter/edit_roles.html | base_app.html  | bodyblock, scripts, title | No                      | No          |

(Also: submitter/delete_submitter.html, submitter/delete_all_submitters.html,
submitter/delete_role.html, submitter/canvas_missing_students.html — same pattern.)

---

### selector/

| Template path                        | Extends        | Blocks defined            | Already uses dashboard? | AJAX/modal? |
|--------------------------------------|----------------|---------------------------|-------------------------|-------------|
| selector/add_bookmark.html           | base_app.html  | bodyblock, scripts, title | No                      | No          |
| selector/add_ranking.html            | base_app.html  | bodyblock, scripts, title | No                      | No          |
| selector/create_custom_offer.html    | base_form.html | bodyblock, title          | No                      | Small form  |
| selector/edit_custom_offer.html      | base_form.html | bodyblock, title          | No                      | Small form  |
| selector/project_bookmarks.html      | base_app.html  | bodyblock, title          | No                      | Small form  |
| selector/project_choices.html        | base_app.html  | bodyblock, title          | No                      | No          |
| selector/project_confirmations.html  | base_app.html  | bodyblock, title          | No                      | Small form  |
| selector/project_custom_offers.html  | base_app.html  | bodyblock, scripts, title | No                      | No          |
| selector/project_new_offer.html      | base_app.html  | bodyblock, scripts, title | No                      | No          |
| selector/selector_bookmarks.html     | base_app.html  | bodyblock, scripts, title | No                      | No          |
| selector/selector_choices.html       | base_app.html  | bodyblock, scripts, title | No                      | No          |
| selector/selector_confirmations.html | base_app.html  | bodyblock, title          | No                      | Small form  |
| selector/selector_custom_offers.html | base_app.html  | bodyblock, scripts, title | No                      | No          |
| selector/selector_new_offer.html     | base_app.html  | bodyblock, scripts, title | No                      | No          |

---

### documents/

| Template path                           | Extends        | Blocks defined            | Already uses dashboard? | AJAX/modal? |
|-----------------------------------------|----------------|---------------------------|-------------------------|-------------|
| documents/edit_period_attachment.html   | base_form.html | bodyblock, scripts, title | No                      | No          |
| documents/period_manager.html           | base_app.html  | bodyblock, scripts, title | No                      | No          |
| documents/upload_period_attachment.html | base_form.html | bodyblock, scripts, title | No                      | No          |

---

**Cross-cutting observation:** Zero templates in any audited subtree define `pillblock` or import
from `convenor/dashboard/`. All extend either `base_app.html` (full pages) or `base_form.html`
(form pages). No pure AJAX fragment templates were found in these paths; AJAX endpoints live
in `app/ajax/` and return data/row HTML, not full pages.

---

## Task 2 — View function audit

View functions are spread across these source files:

- `app/convenor/marking_feedback.py` — marking, presentations, supervision_events
- `app/convenor/markingevent.py` — markingevent, feedback (generate/push)
- `app/convenor/feedback_resources.py` — feedback/
- `app/convenor/submitters.py` — submitter/
- `app/convenor/selector_details.py` — selector/
- `app/convenor/documents.py` — documents/

### app/convenor/feedback_resources.py

| View function          | Route                                       | Has pclass | Has config | Has convenor_data | pclass derivation   |
|------------------------|---------------------------------------------|------------|------------|-------------------|---------------------|
| add_feedback_asset     | /add_feedback_asset/\<int:pclass_id\>       | Yes        | No         | No                | direct              |
| edit_feedback_asset    | /edit_feedback_asset/\<int:asset_id\>       | Yes        | No         | No                | via asset.pclass    |
| add_feedback_template  | /add_feedback_template/\<int:pclass_id\>    | Yes        | No         | No                | direct              |
| edit_feedback_template | /edit_feedback_template/\<int:template_id\> | Yes        | No         | No                | via template.pclass |
| add_feedback_recipe    | /add_feedback_recipe/\<int:pclass_id\>      | Yes        | No         | No                | direct              |
| edit_feedback_recipe   | /edit_feedback_recipe/\<int:recipe_id\>     | Yes        | No         | No                | via recipe.pclass   |
| add_recipe_asset       | /add_recipe_asset/\<int:recipe_id\>         | Yes        | No         | No                | via recipe.pclass   |

Note: `feedback_resources` renders `convenor/dashboard/feedback_resources.html` (a dashboard
template already in scope of pclass_base.html) and already passes `pclass`, `config`,
`convenor_data` — not listed here.

### app/convenor/markingevent.py

| View function                     | Template                                            | Has pclass | Has config | Has convenor_data | pclass derivation                              |
|-----------------------------------|-----------------------------------------------------|------------|------------|-------------------|------------------------------------------------|
| marking_events_inspector          | markingevent/assessment_archive_inspector.html      | Yes        | Yes        | **Yes**           | direct                                         |
| marking_event_conflation_reports  | markingevent/conflation_reports_inspector.html      | Yes        | No         | No                | via event.period.config                        |
| view_conflation_report_emails     | markingevent/conflation_report_emails.html          | Yes        | No         | No                | via event.period.config                        |
| push_single_cr_feedback           | feedback/push_feedback_form.html                    | Yes        | No         | No                | via event.period.config                        |
| push_cr_to_canvas                 | markingevent/push_cr_to_canvas.html                 | Yes        | No         | No                | via event.period.config                        |
| push_cr_feedback_to_canvas        | markingevent/push_cr_feedback_to_canvas.html        | Yes        | No         | No                | via event.period.config                        |
| push_marking_event_feedback       | feedback/push_feedback_form.html                    | Yes        | No         | No                | via event.period.config                        |
| submitter_reports_inspector       | markingevent/submitter_reports_inspector.html       | Yes        | No         | No                | via workflow.event.period.config               |
| resolve_risk_factors              | markingevent/resolve_risk_factors.html              | Yes        | No         | No                | via record.period.config                       |
| enter_turnitin_score              | markingevent/enter_turnitin_score.html              | Yes        | No         | No                | via record.period.config                       |
| marking_reports_inspector         | markingevent/marking_reports_inspector.html         | Yes        | No         | No                | via workflow.event.period.config               |
| inspect_marking_schemes           | markingevent/marking_schemes_inspector.html         | Yes        | Yes        | **Yes**           | direct                                         |
| add_marking_scheme                | markingevent/edit_marking_scheme.html               | Yes        | No         | No                | direct                                         |
| edit_marking_scheme               | markingevent/edit_marking_scheme.html               | Yes        | No         | No                | via scheme.pclass                              |
| inspect_period_marking_events     | markingevent/period_marking_events_inspector.html   | Yes        | No         | No                | via period.config.project_class                |
| export_period_to_box              | markingevent/export_period_to_box.html              | Yes        | No         | No                | via period.config.project_class                |
| add_marking_event                 | markingevent/edit_marking_event.html                | Yes        | No         | No                | via period.config.project_class                |
| edit_marking_event                | markingevent/edit_marking_event.html                | Yes        | No         | No                | via event.period.config.project_class          |
| event_marking_workflows_inspector | markingevent/event_marking_workflows_inspector.html | Yes        | No         | No                | via event.period.config.project_class          |
| add_marking_workflow              | markingevent/edit_marking_workflow.html             | Yes        | No         | No                | via event.period.config.project_class          |
| edit_marking_workflow             | markingevent/edit_marking_workflow.html             | Yes        | No         | No                | via workflow.event.period.config.project_class |
| add_workflow_attachment           | markingevent/add_workflow_attachment.html           | Yes        | No         | No                | via workflow.event.period.config.project_class |
| test_marking_event                | markingevent/test_marking_event.html                | Yes        | No         | No                | via event.period.config.project_class          |
| send_reminder_for_workflow        | markingevent/test_send_reminder_for_workflow.html   | Yes        | No         | No                | via workflow.event.period.config.project_class |
| marking_report_properties         | markingevent/marking_report_properties.html         | Yes        | No         | No                | complex (report→workflow→event)                |
| assign_moderator                  | markingevent/assign_moderator.html                  | Yes        | No         | No                | via event.period.config.project_class          |
| generate_feedback                 | feedback/generate_feedback_form.html                | **No**     | **No**     | No                | via event.period.config                        |
| regenerate_single_feedback        | feedback/generate_feedback_form.html                | **No**     | **No**     | No                | via conflation_report.event                    |
| regenerate_all_feedback           | feedback/generate_feedback_form.html                | **No**     | **No**     | No                | via event.period.config                        |

### app/convenor/submitters.py

| View function           | Template                               | Has pclass | Has config | Has convenor_data | pclass derivation                           |
|-------------------------|----------------------------------------|------------|------------|-------------------|---------------------------------------------|
| canvas_missing_students | submitter/canvas_missing_students.html | Yes        | Yes        | **Yes**           | direct                                      |
| delete_submitter        | submitter/delete_submitter.html        | Yes        | Yes        | No                | via submitter.config.project_class          |
| delete_all_submitters   | submitter/delete_all_submitters.html   | Yes        | Yes        | No                | via config.project_class                    |
| edit_roles              | submitter/edit_roles.html              | Yes        | Yes        | No                | via submitter.config.project_class          |
| add_role                | submitter/add_role.html                | Yes        | Yes        | No                | via record.period.config.project_class      |
| edit_role               | submitter/edit_role.html               | Yes        | Yes        | No                | via role.record.period.config.project_class |

### app/convenor/selector_details.py

| View function           | Template                             | Has pclass | Has config | Has convenor_data | pclass derivation                       |
|-------------------------|--------------------------------------|------------|------------|-------------------|-----------------------------------------|
| selector_bookmarks      | selector/selector_bookmarks.html     | **No**     | Yes        | No                | via config.project_class                |
| project_bookmarks       | selector/project_bookmarks.html      | **No**     | Yes        | No                | via config.project_class                |
| delete_student_bookmark | selector/delete_bookmark.html        | **No**     | Yes        | No                | via selector.config.project_class       |
| add_student_bookmark    | selector/add_bookmark.html           | **No**     | **No**     | No                | **unclear** (sel object only)           |
| selector_choices        | selector/selector_choices.html       | **No**     | Yes        | No                | via config.project_class                |
| project_choices         | selector/project_choices.html        | **No**     | Yes        | No                | via config.project_class                |
| delete_student_choice   | selector/delete_choice.html          | **No**     | Yes        | No                | via selector.config.project_class       |
| add_student_ranking     | selector/add_ranking.html            | **No**     | **No**     | No                | **unclear** (sel object only)           |
| selector_confirmations  | selector/selector_confirmations.html | **No**     | Yes        | No                | via config.project_class                |
| project_confirmations   | selector/project_confirmations.html  | **No**     | Yes        | No                | via config.project_class                |
| project_custom_offers   | selector/project_custom_offers.html  | **No**     | Yes        | No                | complex (project→description→config)    |
| selector_custom_offers  | selector/selector_custom_offers.html | **No**     | Yes        | No                | via selector.config.project_class       |
| new_selector_offer      | selector/selector_new_offer.html     | **No**     | Yes        | No                | via selector.config.project_class       |
| new_project_offer       | selector/project_new_offer.html      | **No**     | Yes        | No                | complex (project→description→config)    |
| create_new_offer        | selector/create_custom_offer.html    | **No**     | Yes        | No                | via selector.config.project_class       |
| edit_custom_offer       | selector/edit_custom_offer.html      | **No**     | Yes        | No                | via offer.selector.config.project_class |
| hints_list              | selector/hints_list.html             | **No**     | Yes        | No                | via config.project_class                |

### app/convenor/documents.py

| View function               | Template                                | Has pclass | Has config | Has convenor_data | pclass derivation                          |
|-----------------------------|-----------------------------------------|------------|------------|-------------------|--------------------------------------------|
| custom_CATS_limits          | documents/custom_CATS_limits.html       | Yes        | No         | No                | via record.period.config.project_class     |
| submission_period_documents | documents/period_manager.html           | Yes        | No         | No                | via period.config.project_class            |
| delete_period_attachment    | documents/delete_period_attachment.html | Yes        | No         | No                | via attachment.period.config.project_class |
| upload_period_attachment    | documents/upload_period_attachment.html | Yes        | No         | No                | via period.config.project_class            |
| edit_period_attachment      | documents/edit_period_attachment.html   | Yes        | No         | No                | via attachment.period.config.project_class |

### app/convenor/marking_feedback.py

| View function                | Template                                             | Has pclass | Has config | Has convenor_data | pclass derivation                             |
|------------------------------|------------------------------------------------------|------------|------------|-------------------|-----------------------------------------------|
| inspect_period_units         | supervision_events/inspect_period_units.html         | Yes        | No         | No                | via period.config.project_class               |
| add_period_unit              | supervision_events/add_period_unit.html              | Yes        | No         | No                | via period.config.project_class               |
| edit_period_unit             | supervision_events/edit_period_unit.html             | Yes        | No         | No                | via unit.period.config.project_class          |
| inspect_unit_event_templates | supervision_events/inspect_unit_event_templates.html | Yes        | No         | No                | via unit.period.config.project_class          |
| add_unit_event_template      | supervision_events/add_unit_event_template.html      | Yes        | No         | No                | via unit.period.config.project_class          |
| edit_unit_event_template     | supervision_events/edit_unit_event_template.html     | Yes        | No         | No                | via template.unit.period.config.project_class |
| inspect_template_events      | supervision_events/inspect_template_events.html      | Yes        | No         | No                | via template.unit.period.config.project_class |
| close_period                 | marking/close_period.html                            | Yes        | No         | No                | via period.config.project_class               |
| edit_period_record           | marking/edit_period_record.html                      | Yes        | Yes        | No                | via config.project_class                      |
| edit_period_presentation     | marking/edit_period_presentation.html                | Yes        | Yes        | No                | via config.project_class                      |
| populate_markers             | marking/populate_markers.html                        | Yes        | Yes        | No                | via config.project_class                      |
| remove_markers               | marking/remove_markers.html                          | Yes        | Yes        | No                | via config.project_class                      |
| faculty_workload             | marking/faculty_workload.html                        | Yes        | Yes        | No                | via config.project_class                      |
| teaching_groups              | marking/teaching_groups.html                         | Yes        | Yes        | No                | via config.project_class                      |
| manual_assign                | marking/manual_assign.html                           | Yes        | Yes        | No                | complex (multi-config possible)               |
| audit_matches                | presentations/audit.html                             | Yes        | No         | No                | direct                                        |
| rubric_manager               | language_analysis/rubric_manager.html                | Yes        | No         | No                | direct                                        |
| clone_grading_rubric         | language_analysis/clone_rubric.html                  | Yes        | No         | No                | direct                                        |

---

## Task 3 — Gap analysis

### Group A — Ready (pclass + config + convenor_data all present)

Template change only — no view changes needed:

| View function            | Template                                       |
|--------------------------|------------------------------------------------|
| marking_events_inspector | markingevent/assessment_archive_inspector.html |
| inspect_marking_schemes  | markingevent/marking_schemes_inspector.html    |
| canvas_missing_students  | submitter/canvas_missing_students.html         |

### Group B — Simple patch (pclass + config present, only convenor_data missing)

Add one line in the view function:

```python
convenor_data = get_convenor_dashboard_data(pclass, config)
```

and `convenor_data=convenor_data` to `render_template_context`.

**marking_feedback.py:** edit_period_record, edit_period_presentation, populate_markers,
remove_markers, faculty_workload, teaching_groups

**submitters.py:** delete_submitter, delete_all_submitters, edit_roles, add_role, edit_role

**markingevent.py:** add_marking_scheme (pclass direct; must also derive config via
`pclass.most_recent_config`)

For `close_period`: pclass already passed; config is `period.config` — one attribute access.

### Group C — Derivation needed (pclass absent or config absent)

Derivation is cheap (attribute access on already-loaded ORM objects, no extra DB queries).

Pattern for period-rooted views:

```python
config = period.config  # or event.period.config, etc.
pclass = config.project_class
convenor_data = get_convenor_dashboard_data(pclass, config)
```

**documents.py (all 5 views):** `period.config.project_class`

**marking_feedback.py (supervision_events base_app.html subset):** `period.config.project_class`

**markingevent.py (most views):** pclass already passed; config via `event.period.config`

**feedback_resources.py:** pclass already passed; config via `pclass.most_recent_config`

**selector_details.py (most views):** config already passed; pclass via `config.project_class`

**language_analysis and presentations:** pclass direct; config via `pclass.most_recent_config`

### Group D — Unclear or complex

| View function              | Reason                                                                      |
|----------------------------|-----------------------------------------------------------------------------|
| generate_feedback          | No pclass or config at all; multi-hop event chain; action-confirmation page |
| regenerate_single_feedback | Same                                                                        |
| regenerate_all_feedback    | Same                                                                        |
| add_student_bookmark       | Only `sel` object; pclass derivation path unclear without further read      |
| add_student_ranking        | Same                                                                        |
| manual_assign              | May handle multiple project classes simultaneously                          |
| marking_report_properties  | Deep chain (report→workflow→event→period→config)                            |

---

## Task 4 — Inheritance complications

**pillblock usage:** Zero templates in any audited subtree define a `pillblock` block.
Confirmed by grep across all nine subtrees. No block-conflict risk for the macro approach.

**base_form.html templates:** These render inside a centred card layout without a full-width
pill row. Adding the persistent header requires a design decision:

- Option A: Add a header slot to `base_form.html` that child templates can fill.
- Option B: Convert affected form templates to extend `base_app.html` and render the form
  inside `bodyblock`.

Option B is simpler and more consistent but changes the visual form layout. Defer until the
approach is agreed. The `base_app.html` pages are straightforward and can proceed immediately.

**AJAX fragments / modals:** No templates in these subtrees are AJAX fragments. The AJAX
endpoints in `app/ajax/convenor/` return data rows or partial HTML and are never in scope
for the header. Templates in scope are all full-page responses.

---

## Task 5 — `periods.html` retirement checklist

### Inbound links to retire

All occurrences of `url_for('convenor.periods', ...)` that must be updated:

**Python redirects:**

1. `app/convenor/marking_feedback.py:545` — redirect after editing a period record
2. `app/convenor/marking_feedback.py:592` — redirect after editing a period presentation
3. `app/convenor/markingevent.py:3252` — default fallback URL argument
4. `app/convenor/markingevent.py:3281` — default fallback URL argument

**Jinja2 templates:**

5. `app/templates/macros.html:410` — return URL for `projecthub.edit_submission_period_articles`
6. `app/templates/macros.html:414` — return URL for `convenor.submission_period_documents`
7. `app/templates/convenor/dashboard/overview_nav.html:15` — "Submission periods" tab link
8. `app/templates/convenor/dashboard/status.html:546` — link in compact period table
9. `app/templates/convenor/dashboard/overview_cards/submitter_card.html:43` — period settings return URL
10. `app/templates/convenor/dashboard/overview_cards/period_settings.html:72` — edit period unit return URL

### View function assessment

The `periods` view (`app/convenor/dashboard.py:357–397`):

- Declared `methods=["GET", "POST"]` but contains no POST handling.
- Performs only read-only DB queries: fetches `pclass`, `config`, `period`, calls
  `get_convenor_dashboard_data`.
- Sets no session state; no side effects.
- **Safe to retire.** Renders only `periods.html` with no other function.

### Anchors to re-point

`periods.html` defines `<a id="period_section_{{ loop.index }}">` and
`<a id="submitter_card_{{ loop.index }}">` per period. No external template or Python file
references these anchors as fragment targets. No re-pointing needed.

---

## Task 6 — `pclass_header` macro design constraints

### 1. Minimum required variables

Confirmed by reading `pclass_base.html` lines 1–118:

- `pclass` — `ProjectClass` instance (name, id for `url_for` links)
- `config` — `ProjectClassConfig` instance (year badge, `selector_lifecycle`, lifecycle constants)
- `convenor_data` — dict from `get_convenor_dashboard_data` (keys used: `selectors`,
  `submitters`, `attached_projects`, `faculty`, `total_faculty`)

### 2. Optional variables

- `period` — could enable a "current period" indicator; not currently used in `pclass_base.html`.
- `subpane` — used by `overview_nav.html` to highlight the active tab; not needed by the header
  macro itself, but pages that also render a tab bar would pass it separately.

### 3. `render_template_context` auto-injections

Available in every template without explicit passing
(`app/shared/context/global_context.py:163–168`):

**Role flags (boolean):** `is_faculty`, `is_office`, `is_student`, `is_reports`, `is_archive`,
`is_archive_reports`, `is_root`, `is_admin`, `is_edit_tags`, `is_view_email`,
`is_manage_users`, `is_emailer`, `is_data_dashboard_AI`, `is_data_dashboard_marking`,
`is_data_dashboard_similarity`, `can_view_dashboards`

**Computed:** `is_convenor` = `is_faculty AND current_user.faculty_data is not None AND
current_user.faculty_data.is_convenor`

**Standard:** `current_user`, `current_time`, `real_user`, `home_dashboard_url`,
`all_pclasses`, `assessment_data`, `matching_data`, `website_revision`, `branding_label`,
`MarkingEvent`, `MarkingEventWorkflowStates`, `SubmitterReportWorkflowStates`

The macro can use all role flags and `all_pclasses` freely.

### 4. Performance

`get_convenor_dashboard_data` (`app/shared/context/convenor_dashboard.py:54–204`) runs
approximately 14 DB queries per call, including:

- 2 faculty count queries
- 1 complex attached-projects query (multi-join)
- 4 selector/submitter/live/canvas count queries
- 1 convenor tasks union query (complex, with subqueries)
- 4 confirm-request count queries
- 4 custom CATS count queries
- 1 marking events query
- **1 Python-side loop** for `marking_urgent_count` — iterates all periods × events, calling
  `.urgent_action_count` on each (an ORM property that queries workflows and submitter_reports)

Cost for non-dashboard full-page views: **acceptable** — comparable to what a typical inspector
page already runs, and these pages are navigated once per user action.

**Do not add to AJAX endpoints.** The following data endpoints are called on every
DataTables page/sort/filter change and must never call `get_convenor_dashboard_data`:
`convenor.popular_projects_ajax`, `convenor.attached_ajax`, `convenor.faculty_ajax`,
`convenor.selectors_ajax`, `convenor.selector_grid_ajax`, `convenor.submitters_ajax`,
`convenor.canvas_missing_students_ajax`. They are JSON endpoints and never render HTML
templates — not in scope.

---

## Recommended implementation order

### Phase 1 — Lowest effort, highest navigational impact (base_app.html pages only)

1. **`convenor/language_analysis/`** — 2 views, pclass direct, config via `most_recent_config`.
   Small scope, good proof of concept for the macro.

2. **`convenor/presentations/`** — 1 view (audit.html), same pattern.

3. **`convenor/documents/`** — 5 views, all use the same `period→config→pclass` derivation.

4. **`convenor/supervision_events/`** (base_app.html subset only: inspect_period_units,
   inspect_unit_event_templates, inspect_template_events) — same period chain.

5. **`convenor/marking/`** (base_app.html subset: faculty_workload, teaching_groups,
   close_period) — pclass + config already present; add `convenor_data` only.

6. **`convenor/markingevent/`** (Group A first, then remaining base_app.html views) — Group A
   views need template changes only; others need config derivation from event chain.

### Phase 2 — Selector subtree

All selector views have `config` but not `pclass`. Derivation is `config.project_class`
(single attribute). Requires verifying `add_student_bookmark`/`add_student_ranking` before
patching (confirm the `sel` model has a `config` relationship).

### Phase 3 — Form-based templates (base_form.html)

Needs a design decision on Option A vs. Option B (see Task 4). Defer until agreed.
Affects: supervision_events edit forms, markingevent edit forms, marking forms, feedback forms.

### Defer — Group D views

`generate_feedback` siblings (action-confirmation shared template), `manual_assign`
(multi-pclass risk), `marking_report_properties` (deep chain). These need individual design
decisions before the macro can be added.
