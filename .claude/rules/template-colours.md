# Template colour policy

All colours in templates and component `<style>` blocks must use either Bootstrap 5.3 CSS custom
property tokens (e.g. `var(--bs-primary)`, `var(--bs-danger-bg-subtle)`) or the app-level
semantic tokens defined in `app/static/css/common.css`. No other hardcoded hex values are
permitted except:

- `color: var(--bs-white)` — white text on a solid `var(--bs-primary)` background
- Ghost buttons on coloured card headers must use the `.btn-ghost-header` class defined in
  `app/static/css/common.css` — do not inline the raw `rgba(255,255,255,…)` values directly

## Dashboard colour ramps

The `--db-orange-*` ramp (`--db-orange-50`, `100`, `200`, `400`, `600`, `800`) is reserved for
similarity concern UI elements (concern strips, score chips, review buttons) to maintain visual
continuity with the similarity concern dashboard.

The `--db-blue-*`, `--db-green-*`, and `--db-purple-*` ramps are available for other
dashboard-themed components.

Do not use `--db-*` tokens for general-purpose UI — Bootstrap semantic tokens remain the default.

For ramp stop semantics and per-dashboard element mapping, see `dashboard-colours.md`.
