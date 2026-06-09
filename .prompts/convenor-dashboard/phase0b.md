# Phase 0b — Reconnaissance: non-dashboard convenor template subtrees

**Read files only. Produce a written plan. Write no code.**

---

## Background

The persistent project-class header implemented in Phase 1 currently only renders on pages
that inherit from `convenor/dashboard/pclass_base.html`. A large number of convenor-facing
pages live in separate template subtrees and extend `base_app.html` or `base.html` directly,
bypassing the header entirely. The goal of the next implementation phase is to add the
persistent header to all of these pages via a shared Jinja2 macro, so convenors never lose
project-class context when navigating to a sub-page.

Before writing any code, this reconnaissance establishes:

1. The full set of affected template subtrees and individual templates
2. The view functions that render them, and what context variables each currently passes
3. The gap between what is currently passed and what the header macro will require
4. Any structural complications that would make the macro approach difficult

---

## Scope

The template subtrees to audit are:

- `convenor/supervision_events/`
- `convenor/markingevent/`
- `convenor/feedback/`
- `convenor/marking/`
- `convenor/language_analysis/`
- `convenor/presentations/`
- `convenor/submitter/`
- `convenor/selector/`
- `convenor/documents/`

And the following individual pages that may live outside a subtree but are reachable from
the convenor dashboard:

- `convenor/supervision_events/inspect_period_units.html` (confirmed independently routed)
- Any template directly under `convenor/` (not in `dashboard/`) that is rendered by a
  route decorated with `@roles_accepted("faculty", "admin", "root")` and calls
  `validate_is_convenor`

---

## Task 1 — Template inventory

For each subtree listed above, find every `.html` file and record:

- Its path relative to `app/templates/`
- What it extends (immediate parent template)
- Whether it defines a `bodyblock`, `pillblock`, or any other block that intersects with
  the header region
- Whether it already imports or calls anything from `convenor/dashboard/`

Present this as a table per subtree:

| Template path | Extends | Blocks defined | Already uses dashboard? |
|---------------|---------|----------------|-------------------------|

---

## Task 2 — View function audit

For each template identified in Task 1, find the view function(s) that render it. For each
view function record:

- File path (e.g. `app/convenor/marking.py`)
- Function name and route
- Every variable passed to `render_template_context` (or `render_template`)
- Specifically flag:
    - Does it pass `pclass`? (directly or must be derived from another variable)
    - Does it pass `config`? (a `ProjectClassConfig` instance)
    - Does it pass `convenor_data`? (the dict from `get_convenor_dashboard_data`)
    - If `pclass` is absent, can it be derived cheaply? (e.g. `config.project_class`,
      `period.config.project_class`, `submission.student.config.project_class`)

Present as a table:

| View function | Route | Has pclass | Has config | Has convenor_data | pclass derivation |
|---------------|-------|------------|------------|-------------------|-------------------|

Where "pclass derivation" is either "direct", "via config", "via period", "via submission",
"complex" (needs more than one hop), or "unclear".

---

## Task 3 — Gap analysis

Summarise the findings from Task 2 into three groups:

**Group A — Ready:** View functions that already pass `pclass`, `config`, and
`convenor_data`. The macro can be added to their templates with no view changes.

**Group B — Simple patch:** View functions that pass `pclass` and `config` but not
`convenor_data`. These need one additional line:

```python
convenor_data = get_convenor_dashboard_data(pclass, config)
```

and `convenor_data=convenor_data` added to the `render_template_context` call.

**Group C — Derivation needed:** View functions where `pclass` is not passed directly and
must be derived. List each one with the derivation path and flag any cases where the
derivation is non-trivial (more than one attribute access, or requires a database query
beyond what is already being done).

**Group D — Unclear or complex:** Any view functions where the route handles multiple
project classes simultaneously, or where the template is shared across convenor and
non-convenor contexts (e.g. admin views that reuse a convenor template). These need
individual design decisions before the macro can be added.

---

## Task 4 — Inheritance complications

For each subtree, note whether any template uses `pillblock`. If so, describe what it puts
there — the macro approach assumes `pillblock` is not used by these templates, so any that
do use it need a different integration strategy.

Also note any templates that render inside a modal or are returned as AJAX fragments rather
than full page responses. These should not receive the persistent header at all.

---

## Task 5 — `periods.html` retirement checklist

Confirm that `convenor/dashboard/periods.html` can be safely retired by verifying:

1. Every route that currently links to `url_for('convenor.periods', ...)` — list them all,
   including routes in templates (grep for `convenor.periods` in both Python files and
   Jinja2 templates)
2. The `periods` view function itself — confirm it only renders `periods.html` and has no
   side effects (POST handling, session state, etc.)
3. Any anchor links (`#period_section_N`, `#submitter_card_N`) that are used for deep-
   linking into `periods.html` from other templates — these will need to be re-pointed to
   equivalent anchors on the status page once `periods.html` is retired

Present as three sub-lists: inbound links to retire, view function assessment, anchors to
re-point.

---

## Task 6 — `pclass_header` macro design constraints

Based on the findings above, answer these questions to inform the macro design:

1. **Minimum required variables:** What is the smallest set of variables the macro needs
   to accept as arguments to render correctly? (Expected: `pclass`, `config`,
   `convenor_data` — confirm or correct this.)

2. **Optional variables:** Are there any variables that some templates pass that would
   allow the header to render richer state (e.g. a `period` argument that enables a
   "current period" indicator in the header)?

3. **`render_template_context` auto-injections:** Confirm which role flags (`is_admin`,
   `is_root`, `is_faculty`, etc.) are auto-injected by `render_template_context` and are
   therefore available in all templates without being passed explicitly. The macro can use
   these freely.

4. **Performance:** `get_convenor_dashboard_data` makes several database queries. For
   subtree pages where it is not currently called, estimate the additional query cost.
   Flag any view functions where the page is called very frequently (e.g. AJAX polling
   targets) where the extra queries would be a concern.

---

## Output format

Produce a Markdown document with six clearly labelled sections matching the six tasks.
Write this document to the project folder in
./.prompts/convenor-dashboard/phase0b-reconnaissance.md

End with a **Recommended implementation order** section: given the gap analysis, suggest
which subtrees to tackle first (lowest effort, highest navigational impact) and which to
defer (Group D or complex derivation cases).

**Do not write or modify any code.**