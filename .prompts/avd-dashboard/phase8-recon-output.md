# Phase 8 Recon Output

## Step 0.1 — Existing collapsible-panel conventions

Two established patterns found in the codebase:

**Pattern A — `status.html` (button inside card header):**
A `btn btn-link` with `data-bs-toggle="collapse"` inside a card header, with `aria-expanded`
set to `"true"` or `"false"` depending on whether the panel is open by default:

```html
<button class="btn btn-link p-0 text-start text-decoration-none fw-semibold"
        style="font-size: var(--cd-text-secondary); color: var(--bs-primary)"
        type="button"
        data-bs-toggle="collapse"
        data-bs-target="#{{ collapse_id }}"
        aria-expanded="{{ 'true' if is_current else 'false' }}"
        aria-controls="{{ collapse_id }}">
    {{ p.display_name|safe }}
</button>
```

**Pattern B — `ai_dashboard.html` (entire card header is the toggle):**
The `data-bs-toggle="collapse"` is placed on the card header `<div>` itself with a chevron icon
that starts as `fa-chevron-down` (collapsed) or `fa-chevron-right` (expanded):

```html
<div class="card-header d-flex align-items-center justify-content-between py-2 bg-light"
     style="cursor: pointer;"
     data-bs-toggle="collapse"
     data-bs-target="#{{ collapse_id }}"
     aria-expanded="{{ 'true' if only_period else 'false' }}"
     aria-controls="{{ collapse_id }}">
    <span class="fw-semibold text-dark">
        <i class="fas fa-chevron-{{ 'down' if only_period else 'right' }} me-1 small period-chevron"></i>
        ...
    </span>
</div>
```

**`template-ui-patterns.md` rule** for filter panels with >2 filter rows:
> wrapped in a collapsible section with a toggle button ("Hide filters" / "Show filters" + chevron
> icon). The panel should be visible by default on first load. Implement the toggle in vanilla
> JavaScript (no jQuery).

This rule directly applies here — use a standalone toggle button, not a card-header trigger.
Bootstrap collapse handles show/hide; vanilla JS updates the label, chevron, and active-count badge.

## Step 0.2 — Current filter-block markup (verbatim, lines 130–293)

```html
{# Filter panel #}
<div class="card mt-3 mb-3 card-body bg-well">

    {# Tenant filter #}
    {% if accessible_tenants is not none and accessible_tenants|length > 1 %}
        <div class="row mb-2"> ... </div>
        <hr class="intro-divider">
    {% endif %}

    {# Project class filter #}
    {% if pclasses is not none and pclasses|length > 0 %}
        <div class="row mb-2"> ... </div>
    {% endif %}

    {# Year filter #}
    {% if years is not none and years|length > 0 %}
        {% if pclasses is not none and pclasses|length > 0 %}<hr class="intro-divider">{% endif %}
        <div class="row mb-2"> ... </div>
    {% endif %}

    {# Research group filter #}
    {% if groups is not none and groups|length > 0 %}
        {% if ... %}<hr class="intro-divider">{% endif %}
        <div class="row"> ... </div>
    {% endif %}

    {# Grade filter #}
    {% if ... %}<hr class="intro-divider">{% endif %}
    <div class="row mb-2"> ... </div>

    {# Consent filters — AVD and exemplar merged under one heading with adjacent labelled groups #}
    <hr class="intro-divider">
    <div class="row"> ... </div>

</div>
{# end filter panel #}
```

The outer container is a single `<div class="card mt-3 mb-3 card-body bg-well">` — the whole
thing collapses as one unit by adding `id="avd-filter-panel"` and `class="collapse show"` to this
div, and pointing the toggle button's `data-bs-target` at it.

## Step 0.3 — Default state and persistence decision

**Default state on first load: expanded.** Per `template-ui-patterns.md`: "The panel should be
visible by default on first load." First-time visitors need to see the filter options; returning
users who know the filters can collapse the panel after it loads.

**Persistence mechanism: `localStorage`.** The session-key mechanism (used for individual filter
values) _is_ reusable for a boolean — e.g. `session["avd_dashboard_filter_panel_expanded"] = True`.
However, that would require:
1. Plumbing the value from the view into the template, AND
2. A separate AJAX endpoint or an extra query param on all filter link URLs (or a tiny standalone
   form/POST) to write the session key when the panel is toggled.

`localStorage` is simpler and equivalent for the use case: it persists the collapse state in the
browser across full page reloads (including those triggered by filter button clicks), survives
tab refreshes, but resets when browser storage is cleared. Since the collapse state is purely a
UI preference with no security or server-side implications, `localStorage` is the right tool and
avoids touching the view.

Key: `"avd_filter_panel_expanded"` (string `"true"` / `"false"`), default `"true"` (show panel).

## Step 0.4 — Filter changes: full page reload or in-place AJAX?

Filter button clicks are **full page reloads** — every filter button is an `<a href="...">` link
that bakes all filter values into the URL as query parameters. Clicking one navigates to a new
URL, which re-renders the template server-side. The DataTables AJAX URL is baked into the
`<script>` block at render time.

This confirms that collapse state **must survive page reloads** — `localStorage` achieves this.
The panel's initial CSS state (`collapse show` = expanded) is overridden by the JS bootstrap
snippet that runs on `DOMContentLoaded`, checking localStorage before Bootstrap processes the page.

## Implementation plan

1. Compute `active_filter_count` in Jinja at the top of the template (sum of non-"all" filters for
   pclass, year, group, grade, avd_consent, exemplar_consent — 6 filters, range 0–6).
2. Add a toggle button row immediately before the filter card:
   - Label: "Hide filters" / "Show filters"
   - Chevron: `fa-chevron-up` (expanded) / `fa-chevron-down` (collapsed)
   - Count badge: shown when collapsed AND `active_filter_count > 0`; hidden otherwise
3. Change the filter card `<div class="card mt-3 mb-3 card-body bg-well">` to
   `<div id="avd-filter-panel" class="collapse show card mt-0 mb-3 card-body bg-well">`.
   (`mt-3` dropped to `mt-0` because the toggle row above provides the top spacing.)
4. Add vanilla JS in the scripts block:
   - On `DOMContentLoaded`: read `localStorage`; if `"false"`, programmatically hide the panel
     before first paint by removing `.show` and setting `aria-expanded="false"`.
   - On `hide.bs.collapse` / `show.bs.collapse` events: update localStorage, toggle label text,
     swap chevron class, and show/hide the count badge.
