# Template UI patterns

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
