# Template conventions

## Colour policy

All colours in templates and component `<style>` blocks must use either Bootstrap 5.3 CSS custom
property tokens (e.g. `var(--bs-primary)`, `var(--bs-danger-bg-subtle)`) or the app-level
semantic tokens defined in `app/static/css/common.css`. No other hardcoded hex values are
permitted except:

- `color: #fff` — white text on a solid `var(--bs-primary)` background
- `background: rgba(255,255,255,.18)` and `border: 1px solid rgba(255,255,255,.4)` — ghost
  button on a primary-coloured header bar

The `--db-orange-*` ramp (`--db-orange-50`, `100`, `200`, `400`, `600`, `800`) is reserved for
similarity concern UI elements (concern strips, score chips, review buttons) to maintain visual
continuity with the similarity concern dashboard. The `--db-blue-*`, `--db-green-*`, and
`--db-purple-*` ramps are available for other dashboard-themed components. Do not use `--db-*`
tokens for general-purpose UI — Bootstrap semantic tokens remain the default.

## Filter button pattern

Many templates contain rows of filter/toggle buttons. The target pattern for new and refactored
templates is:

- Render as `<a href>` elements styled as pill buttons (server-side navigation reloads the page
  with updated query parameters).
- Pill shape: `border-radius: 20px`, `font-size: 12px`, `padding: 3px 11px`.
- Inactive: `background: var(--bs-body-bg)`, `border: 1px solid var(--bs-border-color)`,
  `color: var(--bs-body-color)`. Hover darkens border to `var(--bs-secondary-color)`.
- Active (current filter value): `background: var(--bs-primary)`, `color: #fff`,
  `border-color: var(--bs-primary)`.
- Existing templates using the old `btn-sm btn-primary` / `btn-outline-secondary` pattern do not
  need immediate conversion; convert opportunistically when a template is touched for another reason.

## Collapsible filter panels

Filter panels with more than two filter rows should be wrapped in a collapsible section with a
toggle button ("Hide filters" / "Show filters" + chevron icon). The panel should be visible by
default on first load. Implement the toggle in vanilla JavaScript (no jQuery).

## Toolbar button grouping

Action toolbars should group related actions with a 1px vertical separator
(`background: var(--bs-border-color)`, `height: 22px`) between groups.

- Destructive actions must use `border-color: var(--bs-danger-border-subtle)` and
  `color: var(--bs-danger-text-emphasis)` to distinguish them visually.
- Infrequent bulk actions (e.g. Pipeline operations) should be collapsed into a dropdown rather
  than shown as individual buttons.
