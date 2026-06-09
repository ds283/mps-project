# Phase 5c — Roll out `pclass_form.html` to convenor form templates

**Prerequisite: Phase 5a is complete and verified. Phase 5b is complete and verified.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

Change every convenor form template that currently extends `base_form.html` to extend
`convenor/dashboard/pclass_form.html` instead, and patch the corresponding view functions
to pass `pclass`, `config`, and `convenor_data` where they are currently missing.

The view-function patches follow exactly the same derivation patterns established in
Phase 5b. Any view already patched in Phase 5b (because it had a `base_app.html` sibling
in the same file) will not need re-patching — only the `render_template_context` call for
the form template needs `convenor_data` confirmed present.

---

## Step 1 — Read before writing

Read the Phase 0b reconnaissance output in full
(`/.prompts/convenor-dashboard/phase0b-reconnaissance.md`).

Then read `pclass_form.html` to confirm its block structure matches `base_form.html`
(this should be guaranteed by Phase 5a verification, but confirm before proceeding).

Read these source files to confirm derivation paths for any view functions not already
patched in Phase 5b:

- `app/convenor/marking_feedback.py`
- `app/convenor/markingevent.py`
- `app/convenor/feedback_resources.py`

---

## Step 2 — Template changes

For every template below, change the single `extends` line:

```jinja
{# Before #}
{% extends "base_form.html" %}

{# After #}
{% extends "convenor/dashboard/pclass_form.html" %}
```

No other changes to these templates.

### Templates to update

**convenor/supervision_events/**:

- `edit_period_unit.html`
- `edit_unit_event_template.html`

**convenor/markingevent/**:

- `edit_marking_event.html`
- `edit_marking_scheme.html`
- `edit_marking_workflow.html`
- `test_marking_event.html`
- `test_send_reminder_for_workflow.html`

**convenor/feedback/**:

- `add_feedback_asset.html`
- `edit_feedback_asset.html`
- `feedback_recipe.html`
- `feedback_template.html`

**convenor/marking/**:

- `populate_markers.html`
- `remove_markers.html`
- `edit_period_record.html`
- `edit_period_presentation.html`
- `close_period.html`
- `faculty_workload.html`
- `teaching_groups.html`
- `manual_assign.html`

**convenor/submitter/**:

- `add_role.html`
- `edit_role.html`

**convenor/selector/**:

- `create_custom_offer.html`
- `edit_custom_offer.html`

**convenor/documents/**:

- `edit_period_attachment.html`
- `upload_period_attachment.html`

---

## Step 3 — View function patches

Only patch view functions not already patched in Phase 5b. For each, confirm whether
`convenor_data` is already being passed (because the function also renders a `base_app.html`
template that was handled in Phase 5b) before adding a second call.

### View functions requiring new patches in this phase

**`app/convenor/marking_feedback.py`**

These were Group B in Phase 5b (base_app.html template sibling) but confirm the patch
was applied. If not, apply now:

- `edit_period_record` — pclass + config present; add `convenor_data`
- `edit_period_presentation` — same
- `populate_markers` — same
- `remove_markers` — same
- `faculty_workload` — same
- `teaching_groups` — same
- `close_period` — config via `period.config`; pclass via `config.project_class`

For `manual_assign`: read the function body carefully. If it operates across multiple
project classes simultaneously, apply the Group D stub approach (empty dict + TODO comment)
rather than calling `get_convenor_dashboard_data` — it is unclear which config to use.

**`app/convenor/markingevent.py`**

- `add_marking_scheme` — already patched in Phase 5b; confirm only
- `edit_marking_scheme` — pclass via `scheme.pclass`; config via `pclass.most_recent_config`
- `add_marking_event` — config via `period.config`; pclass via `config.project_class`
- `edit_marking_event` — config via `event.period.config`; pclass via `config.project_class`
- `add_marking_workflow` — config via `event.period.config`; pclass via `config.project_class`
- `edit_marking_workflow` — config via `workflow.event.period.config`
- `test_marking_event` — config via `event.period.config`
- `send_reminder_for_workflow` — config via `workflow.event.period.config`
- `assign_moderator` — config via `event.period.config`

**`app/convenor/feedback_resources.py`**

All views: pclass direct; config via `pclass.most_recent_config`. Guard `config is None`.

**`app/convenor/submitters.py`**

- `add_role` — already patched in Phase 5b; confirm only
- `edit_role` — already patched in Phase 5b; confirm only
- `delete_role`:
  ```python
  config = role.record.period.config
  pclass = config.project_class
  convenor_data = get_convenor_dashboard_data(pclass, config)
  ```

**`app/convenor/selector_details.py`**

- `create_new_offer` — already patched in Phase 5b; confirm only
- `edit_custom_offer` — already patched in Phase 5b; confirm only

**`app/convenor/documents.py`**

- `edit_period_attachment` — config via `attachment.period.config`; pclass via `config.project_class`
- `upload_period_attachment` — config via `period.config`; pclass via `config.project_class`

---

## Step 4 — Verification

1. **Template extends audit**: Grep all nine subtree directories for
   `extends "base_form.html"`. The only remaining results should be:
    - Templates explicitly excluded (Group D, `manual_assign` if stubbed)
    - Any template outside the nine named subtrees (not in scope for this phase)
      List every remaining result and confirm each is either an expected exclusion or
      genuinely out of scope.

2. **Block override compatibility**: For each template that overrides a non-standard block
   (i.e. anything other than `formtitle`, `form_content`, `scripts`, `title`), confirm
   that block is defined in `pclass_form.html`. Specifically verify:
    - `edit_marking_event.html` — `header` and `footer` blocks present in `pclass_form.html`
    - `remove_markers.html` — `card_classes` and `card_header_classes` present
    - Any others identified in Step 1 reading

3. **`convenor_data` in render calls**: For each view function patched in Step 3, confirm
   `convenor_data=convenor_data` appears in every `render_template_context` call in that
   function. Some functions have multiple render paths (e.g. GET vs POST branches) — check
   all of them.

4. **No double-patching**: For view functions confirmed as already patched in Phase 5b,
   confirm `get_convenor_dashboard_data` is not called twice in the same function.

5. **Form layout unchanged**: For three representative form templates — one from
   `markingevent/`, one from `marking/`, one from `feedback/` — confirm that the rendered
   HTML structure (card, header, form_content) is unchanged from before this phase. Do
   this by checking that the template's `formtitle` and `form_content` blocks are
   identical to their pre-phase content.

6. **`periods.html` retirement**: Confirm `convenor/dashboard/periods.html` still exists
   at this point. It is retired in Phase 5d, not here.

Report the result of each check. If any check fails, fix it before finishing.