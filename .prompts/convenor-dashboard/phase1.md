# Phase 1 — Persistent project-class header

**Prerequisite: Phase 0 reconnaissance is complete.**

Read the Phase 0 output before writing a single line of code. The plan in Phase 0 identifies every file that needs
touching; do not proceed if that plan is missing or incomplete.

---

## Objective

Insert a new template `convenor/dashboard/pclass_base.html` between `convenor/dashboard/nav.html` and all per-page
dashboard templates. This base owns the persistent header (class name, year, lifecycle chip, key metrics, action
buttons) and the pill navigation bar.

After this phase, every page in the convenor dashboard shows a consistent header regardless of which tab is active. No
existing page behaviour changes — only the header and nav are affected.

---

## Step 1 — Read before writing

Read these files in full before writing anything:

- `app/templates/convenor/dashboard/nav.html`
- `app/templates/base.html` (block structure only — identify `pillblock` and `bodyblock`)
- `app/templates/base_app.html`
- `app/shared/context/global_context.py` (confirm which role flags are auto-injected)
- `app/shared/context/convenor_dashboard.py` — the `get_convenor_dashboard_data` function signature and return dict keys
- Every view function that renders a `convenor/dashboard/` template (from Phase 0 list)

---

## Step 2 — Design the new template

The new `pclass_base.html` must:

1. Extend `convenor/dashboard/nav.html` (which extends `base_app.html` → `base.html`)
2. Override `pillblock` to render:
    - **Persistent header strip** containing:
        - "All classes" breadcrumb link → `url_for('convenor.overview')`
        - `pclass.name` (plain text, not a link)
        - Year badge: `{{ config.submit_year_a }}–{{ config.submit_year_b }}`
        - Lifecycle chip: text and colour driven by `config.selector_lifecycle` (reuse the existing lifecycle label
          logic already in `status.html`)
        - Metrics inline: selectors count, submitters count, attached projects count, faculty enrolled/total — all from
          `convenor_data`
        - Action buttons (right-aligned): **Resources**, **Configure**, **Workflow log →** — link to the existing routes
          identified in Phase 0
    - **Pill navigation** (moved here from `nav.html`): the existing `<ul class="nav nav-pills dashboard-nav">` content
      from `nav.html`, unchanged
    - Call `{{ super() }}` at the end of `pillblock` so `tabblock` (used by `overview_nav.html` for the
      Status/Periods/Capacity sub-tabs) still works
3. Define a `bodyblock` that child templates fill normally

**CSS constraints:**

- Use only existing CSS token classes from `common.css` and `site-default.css` — no new inline hex colours
- The header strip should use Bootstrap utility classes consistent with the rest of the app (the existing navbar uses
  `bg-body-secondary`, `border-bottom`, etc.)
- Follow the convention in `template-ui-patterns.md` and `convenor-ui-patterns.md` for badge and chip styling

---

## Step 3 — Update child templates

Change every template listed in the Phase 0 tree that currently `extends "convenor/dashboard/nav.html"` to instead
`extends "convenor/dashboard/pclass_base.html"`.

**Do not change** templates that extend `overview_nav.html` — those already get `pclass_base.html` through the chain
because `overview_nav.html` itself will extend `pclass_base.html`.

So the only changes are:

- `overview_nav.html` → change its extends from `nav.html` to `pclass_base.html`
- Any other direct children of `nav.html` identified in Phase 0

---

## Step 4 — Patch view functions with missing context variables

The persistent header needs `pclass`, `config`, and `convenor_data` in every view's template context.

From the Phase 0 audit, patch any view function that does not already pass all three. The pattern is:

```python
data = get_convenor_dashboard_data(pclass, config)
# then in render_template_context:
convenor_data = data,
```

Do not change views that already pass `convenor_data`. Do not add `get_convenor_dashboard_data` calls where they would
duplicate an existing call in the same view.

---

## Step 5 — Verification

After writing all changes, perform these checks **by reading the files you have written**:

1. Grep for `extends "convenor/dashboard/nav.html"` in the templates directory. The only result should be
   `pclass_base.html` itself and `overview_nav.html` **before** your change (after your change, zero results).
2. Grep for `extends "convenor/dashboard/pclass_base.html"`. Confirm the list matches the Phase 0 tree (every direct
   child of the old `nav.html` now points here).
3. For each view function in `dashboard.py`, confirm `convenor_data` appears in its `render_template_context` call.
4. Confirm `pclass_base.html` calls `{{ super() }}` inside `pillblock` so the `tabblock` chain is preserved.

Report the results of each check. If any check fails, fix it before finishing.

---

## What NOT to do

- Do not modify any view logic beyond adding the missing `convenor_data` pass-through
- Do not change any existing page layout — only the header and nav are new
- Do not remove the `tabblock` mechanism used by `overview_nav.html`
- Do not add new CSS classes — use existing tokens only
- Do not add any new routes in this phase