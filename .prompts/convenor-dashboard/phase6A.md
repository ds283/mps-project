# Prompt A — Metric tile macro

**Prerequisite: Phases 1–3 are complete. `status.html` contains the 60/40 split layout.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

Extract the repeated inline metric tile pattern in `status.html` into a single reusable
Jinja2 macro `metric_tile`, defined in a new fragment file. Replace all three existing
inline implementations with macro calls. No visual output should change.

---

## Step 1 — Read before writing

Read `app/templates/convenor/dashboard/status.html` in full.

Identify and record the exact line ranges of the three metric tile grid implementations:

1. **Workflow status grid** — the 4-cell `row g-1` grid accumulating `ns.complete`,
   `ns.pending_upload`, `ns.in_progress`, `ns.risk_flags` across marking events
   (currently around line 263)

2. **Submitters card grid** — the 2-cell grid showing `n_uploaded` / `n_missing`
   (currently around line 392)

3. **Selection metrics grid** — the 3-cell grid showing submitted/bookmarked/confirms
   outstanding (currently around line 584)

For each, record:

- The number of cells
- The `variant` used for each cell (success, warning, danger, secondary, or conditional)
- Whether any cell uses a conditional variant (i.e. the colour depends on a value
  being zero or non-zero)
- Whether any cell shows a denominator alongside the main value (e.g. `17/43`)

Also read `app/templates/convenor/dashboard/overview_cards/` — list any existing
macro files there so the new file follows the naming convention.

---

## Step 2 — Design the macro signature

Based on the Step 1 findings, the macro must handle:

- A primary `value` (integer or string)
- A `label` (string shown below the value in small text)
- A `variant` (one of: `success`, `warning`, `danger`, `secondary`) controlling
  background, border, and text colours using Bootstrap 5.3 semantic CSS variables
- An optional `denominator` (integer/string, default `none`) — when provided, renders
  as `value<small class="fw-normal text-body-secondary">/denominator</small>`
- An optional `conditional_variant` mechanism for cells whose colour depends on whether
  a value equals zero:
    - `zero_variant` (default `none`) — variant to use when `value == 0`
    - `nonzero_variant` (default `none`) — variant to use when `value != 0`
    - When both are provided, `variant` is ignored and the displayed variant is
      determined by comparing `value` to zero

The Bootstrap 5.3 CSS variable mapping for each variant is:

| variant     | background                    | border                            | text                              |
|-------------|-------------------------------|-----------------------------------|-----------------------------------|
| `success`   | `var(--bs-success-bg-subtle)` | `var(--bs-success-border-subtle)` | `var(--bs-success-text-emphasis)` |
| `warning`   | `var(--bs-warning-bg-subtle)` | `var(--bs-warning-border-subtle)` | `var(--bs-warning-text-emphasis)` |
| `danger`    | `var(--bs-danger-bg-subtle)`  | `var(--bs-danger-border-subtle)`  | `var(--bs-danger-text-emphasis)`  |
| `secondary` | `var(--bs-secondary-bg)`      | `var(--bs-border-color)`          | `var(--bs-secondary-color)`       |

The `secondary` variant uses `text-body-secondary` on the value rather than an emphasis
colour — ensure this is handled correctly in the macro.

---

## Step 3 — Create the macro file

Create `app/templates/convenor/dashboard/overview_cards/_metric_tile.html`.

The macro renders a single tile — a `rounded p-1 text-center` div with:

- Background and border set by the resolved variant (via inline `style` — this is
  acceptable here because the values are Bootstrap CSS variable references, not
  hardcoded hex)
- Value in `<div class="small fw-bold">` with text colour set by the resolved variant
- Optional denominator rendered inline as described above
- Label in `<div class="text-body-secondary" style="font-size:10px">`

```jinja
{% macro metric_tile(value, label, variant='secondary', denominator=none,
                     zero_variant=none, nonzero_variant=none) %}
    {# resolve effective variant #}
    ...
{% endmacro %}
```

The macro renders only the tile `<div>` — it does not render the Bootstrap `col-*`
wrapper. The caller is responsible for the grid column wrapper. This keeps the macro
composable across different column widths (col-6, col-4, col-3, etc.).

---

## Step 4 — Replace inline implementations in `status.html`

Import the macro at the top of `status.html`, alongside the existing imports:

```jinja
{% from "convenor/dashboard/overview_cards/_metric_tile.html" import metric_tile %}
```

### Replacement 1 — Workflow status grid (4 cells, col-6 col-sm-3 each)

Replace the four inline tile divs with:

```jinja
<div class="row g-1 mb-2">
    <div class="col-6 col-sm-3">
        {{ metric_tile(ns.complete, 'Complete', variant='success') }}
    </div>
    <div class="col-6 col-sm-3">
        {{ metric_tile(ns.pending_upload, 'Pending upload',
                       zero_variant='secondary', nonzero_variant='warning') }}
    </div>
    <div class="col-6 col-sm-3">
        {{ metric_tile(ns.in_progress, 'In progress', variant='secondary') }}
    </div>
    <div class="col-6 col-sm-3">
        {{ metric_tile(ns.risk_flags, 'Risk flags',
                       zero_variant='secondary', nonzero_variant='danger') }}
    </div>
</div>
```

Note: `pending_upload` uses `zero_variant='secondary'` (neutral when zero, warning when
non-zero). `risk_flags` uses `zero_variant='secondary'` (neutral when zero, danger when
non-zero). Read the original implementation to confirm these match the original
conditional logic before writing.

### Replacement 2 — Submitters card (2 cells, col-6 each)

Replace the two inline tile divs with:

```jinja
<div class="row g-1 mb-2">
    <div class="col-6">
        {{ metric_tile(n_uploaded, 'Uploaded', variant='success') }}
    </div>
    <div class="col-6">
        {{ metric_tile(n_missing, 'Missing',
                       zero_variant='secondary', nonzero_variant='warning') }}
    </div>
</div>
```

Read the original to confirm the `n_missing > 0` condition maps to `nonzero_variant='warning'`.

### Replacement 3 — Selection metrics (3 cells, col-4 each)

```jinja
<div class="row g-1 mb-1">
    <div class="col-4">
        {{ metric_tile(sel_submitted, 'Submitted', denominator=sel_total,
                       zero_variant='danger', nonzero_variant='success') }}
    </div>
    <div class="col-4">
        {{ metric_tile(sel_bookmarks, 'Bookmarked', denominator=sel_total,
                       variant='secondary') }}
    </div>
    <div class="col-4">
        {{ metric_tile(sel_outstanding_confirm, 'Confirms outstanding',
                       zero_variant='success', nonzero_variant='danger') }}
    </div>
</div>
```

Note: `sel_submitted` uses `zero_variant='danger'` / `nonzero_variant='success'` — read
the original `submitted_ok = sel_submitted == sel_total` condition. The original turns
green only when submitted equals total, not merely when non-zero. This is a subtle
distinction the simple `zero_variant`/`nonzero_variant` mechanism doesn't capture.

To handle this correctly, add an optional `value_ok` boolean parameter to the macro:

```jinja
{% macro metric_tile(value, label, variant='secondary', denominator=none,
                     zero_variant=none, nonzero_variant=none, value_ok=none) %}
```

When `value_ok` is provided (not `none`), it overrides the zero-comparison logic:

- `value_ok == true` → use `zero_variant` (the "good" state)
- `value_ok == false` → use `nonzero_variant` (the "bad" state)

The `sel_submitted` cell then becomes:

```jinja
{{ metric_tile(sel_submitted, 'Submitted', denominator=sel_total,
               zero_variant='success', nonzero_variant='danger',
               value_ok=(sel_submitted == sel_total)) }}
```

Update the macro definition to incorporate `value_ok` before writing the replacements.

---

## Step 5 — Verification

1. **Grep for removed pattern**: Grep `status.html` for
   `bs-success-bg-subtle` and `bs-warning-bg-subtle` and `bs-danger-bg-subtle`.
   All results must be inside the macro import line or the macro file itself —
   zero results should remain in `status.html`'s body content.

2. **Grep for inline style on tile labels**: Grep `status.html` for
   `style="font-size:10px"`. All remaining results must be inside the macro file,
   not in `status.html` itself.

3. **Macro file self-contained**: Confirm `_metric_tile.html` contains no `{% extends %}`
   and no `{% block %}` — it is a pure macro file.

4. **Three call-sites present**: Grep `status.html` for `metric_tile(`. Confirm exactly
   9 calls are present (4 + 2 + 3).

5. **`value_ok` parameter present**: Grep `_metric_tile.html` for `value_ok`. Confirm
   it appears in the macro signature and in the variant resolution logic.

6. **Visual parity check**: For each of the three grids, manually trace the macro
   output for a representative set of values and confirm the rendered HTML is identical
   to the original:
    - Workflow grid: `complete=14, pending_upload=2, in_progress=23, risk_flags=0` →
      complete=success, pending_upload=warning, in_progress=secondary, risk_flags=secondary
    - Submitters: `n_uploaded=37, n_missing=2` → uploaded=success, missing=warning
    - Selection: `sel_submitted=17, sel_total=43, sel_bookmarks=14,
     sel_outstanding_confirm=9` → submitted=danger (17≠43), bookmarks=secondary,
      confirms=danger (9≠0)

Report results of all checks. Fix any failures before finishing.