# Phase 0 — Reconnaissance

**Read files only. Produce a written plan. Write no code.**

---

## Context

We are about to redesign the convenor dashboard. The work will span four phases:

1. Persistent project-class header (new `pclass_base.html` base template)
2. Actions panel (new computed data function + template fragment)
3. Overview tab redesign (60/40 split layout)
4. Configuration tile surface (new `configure` route)

This phase establishes everything needed to execute phases 1–4 safely.

---

## Task

### 1. Map the template inheritance tree

Starting from `app/templates/convenor/dashboard/`, find every template file and determine:

- What it extends (immediate parent)
- What named blocks it defines or overrides
- What `pane` / `subpane` values it sets (these drive active-state logic in `nav.html`)

Express this as an indented tree. Example format:

```
base.html
  base_app.html
    convenor/dashboard/nav.html          [defines: pillblock, tabblock]
      convenor/dashboard/overview_nav.html  [pane=overview, tabblock→Status/Periods/Capacity]
        convenor/dashboard/status.html
        convenor/dashboard/periods.html
        convenor/dashboard/capacity.html
      convenor/dashboard/comms.html
      ...
```

Include every template under `convenor/dashboard/` — do not skip any.

### 2. Catalogue context variables per view

For every view function in `app/convenor/dashboard.py` (and any other file that renders a `convenor/dashboard/`
template), record:

- The route and function name
- The template it renders
- Every variable passed to `render_template_context` (or `render_template`)

Specifically flag which views **do not** pass `convenor_data`. The new base template will require `pclass`, `config`,
and `convenor_data` on every dashboard route; any views missing these will need patching in Phase 1.

### 3. Confirm the `render_template_context` signature

Locate `app/shared/context/global_context.py` (or wherever `render_template_context` is defined). Record:

- What extra variables it injects automatically (e.g. `is_admin`, `is_root`, `is_faculty`, `current_user`, role flags)
- Whether it calls `get_convenor_dashboard_data` itself or relies on the caller to pass `convenor_data`

This determines whether the persistent header can read role flags from template context directly, or whether view
functions need explicit changes.

### 4. Identify the `urgent_action_count` property

In `app/models/` (likely `marking_event.py` or a mixin), find the `urgent_action_count` property on `MarkingEvent`.
Record:

- Its definition (what states/conditions it counts)
- Whether an analogous property exists on `SubmissionPeriodRecord` that aggregates across all its events

This is needed for Phase 2 (actions panel) to understand what "urgent" and "blocking" already mean in the model.

### 5. Locate all resources-related routes

Find every route currently reachable from the "Resources…" button on the convenor dashboard (marking schemes, email
templates, feedback documents, grading rubric). Record route names and their view files. These will be surfaced as tiles
in Phase 4.

---

## Output format

Produce a Markdown document with five clearly labelled sections matching the five tasks above. End with a **Risks and
notes** section listing any surprises: views that don't follow the standard pattern, templates that extend something
unexpected, context variables with inconsistent names across views, etc.

**Do not write or modify any code.**