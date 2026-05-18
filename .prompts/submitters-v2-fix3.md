# Task: Fix3 — pagination selector, search prominence, filter alignment

Three cosmetic and UX improvements to `app/templates/convenor/dashboard/submitters_v2.html`
and the corresponding route in `app/convenor/submitters.py`.

Do not modify any other files unless explicitly instructed. Maintain the existing
`sv2-` CSS class namespace and all token-only colour rules.

---

## Fix 1 — Per-page selector

Currently `per_page` defaults to 25 with no UI to change it.

### Route (`app/convenor/submitters.py`)

Read `per_page` from the request query string. Accept only the values `5`, `10`, `15`,
`20`; reject anything else and fall back to `10`. Default to `10` when the parameter is
absent. Pass `per_page` into the template context. Ensure `per_page` threads through all
pagination URL constructions in the route (it is already threaded through in the template
pagination links, but verify the route also passes it through correctly).

Update the default value at the top of `submitters_v2.html` (line 11) from `25` to `10`
to match.

### Template

Place the per-page selector immediately to the right of the search input/button, inside
the same `<form>` element as the search box, so submitting the form (pressing Enter or
clicking Search) also applies the selected per-page value.

Render it as a `<select>` element:

```html
<select name="per_page" class="sv2-per-page-select" onchange="this.form.submit()">
    {% for n in [5, 10, 15, 20] %}
    <option value="{{ n }}" {% if per_page== n %}selected{% endif %}>{{ n }} per page</option>
    {% endfor %}
</select>
```

Style `.sv2-per-page-select` to match the search input — same `border-radius`, `font-size`,
`border`, `background`, `color`, and `padding`. Add it to the CSS `<style>` block:

```css
.sv2-per-page-select {
    font-size: 0.8rem;
    padding: 0.1875rem 0.5rem;
    border-radius: 20px;
    border: 1px solid var(--bs-border-color);
    background: var(--bs-body-bg);
    color: var(--bs-body-color);
    outline: none;
    cursor: pointer;
    appearance: auto;
}

.sv2-per-page-select:focus {
    border-color: var(--bs-primary);
}
```

Also add `per_page` as a parameter to all pagination `href` links in the pager section
(Previous, page numbers, Next) so that changing page does not reset the per-page value.
The URL pattern should include `per_page=per_page` in every `url_for(...)` call in the
pager.

---

## Fix 2 — Make the search input more discoverable

The search input currently blends into the filter panel because it uses the same styling
as the inactive filter buttons. Make it stand out without introducing visual noise.

Apply the following changes to `.sv2-search-input` in the `<style>` block:

1. Give it a slightly larger `min-width`: change from `180px` to `220px`.
2. Add a subtle inset search icon using a Font Awesome `fa-search` pseudo-element or, more
   simply, place the icon as a sibling element with `position: relative` wrapping:

```html

<div class="sv2-search-wrap">
    <i class="fas fa-search sv2-search-icon"></i>
    <input type="text" name="name_filter" value="{{ name_filter }}"
           class="sv2-search-input" placeholder="Search students…" autocomplete="off">
</div>
```

```css
.sv2-search-wrap {
    position: relative;
    display: inline-flex;
    align-items: center;
}

.sv2-search-icon {
    position: absolute;
    left: 0.6rem;
    color: var(--bs-secondary-color);
    font-size: 0.7rem;
    pointer-events: none;
}

.sv2-search-input {
    padding-left: 1.6rem; /* make room for icon */
    min-width: 220px;
}
```

3. Give the search row label (`Search`) a slightly stronger visual weight by using
   `font-weight: 700` and `color: var(--bs-body-color)` (instead of
   `var(--bs-secondary-color)`) — only on the Search label, not all filter labels.
   Do this with an inline class override or by wrapping in a `<strong>` tag, not by
   changing the shared `.sv2-filter-label` rule.

These three changes together (icon, extra width, bolder label) should make the search
control clearly distinct from the filter button rows without requiring a colour change.

---

## Fix 3 — Align filter labels and buttons in a table layout

The filter panel currently uses `display: flex; flex-wrap: wrap` rows, which causes the
buttons to have a ragged left margin because each row is independently laid out. Replace
the flex rows with a two-column CSS grid or `<table>` so that all labels align to a
common left boundary and all button groups align to a common second column.

Use a `<table>` with `role="presentation"` (it is layout, not data). The structure is:

```html

<table role="presentation" class="sv2-filter-table">
    <tbody>
    <tr>
        <td class="sv2-filter-label">Search</td>
        <td><!-- search form --></td>
    </tr>
    {% if cohorts and cohorts|length > 1 %}
    <tr>
        <td class="sv2-filter-label">Cohort</td>
        <td><!-- cohort buttons --></td>
    </tr>
    {% endif %}
    {% if progs and progs|length > 1 %}
    <tr>
        <td class="sv2-filter-label">Programme</td>
        <td><!-- programme buttons --></td>
    </tr>
    {% endif %}
    <tr>
        <td class="sv2-filter-label">State</td>
        <td><!-- state buttons --></td>
    </tr>
    <tr>
        <td class="sv2-filter-label">Display</td>
        <td><!-- display buttons --></td>
    </tr>
    </tbody>
</table>
```

Add to the `<style>` block:

```css
.sv2-filter-table {
    border-collapse: separate;
    border-spacing: 0 0.3rem;
    width: 100%;
}

.sv2-filter-table td:first-child {
    white-space: nowrap;
    vertical-align: middle;
    padding-right: 0.75rem;
    width: 1%; /* shrink to content */
}

.sv2-filter-table td:last-child {
    vertical-align: middle;
}
```

Remove the now-redundant `.sv2-filter-row` and `.sv2-filter-row:last-child` rules from
the `<style>` block (or keep them if they are used elsewhere — check first). Remove the
`min-width: 70px` constraint from `.sv2-filter-label` since the table column width now
handles alignment.

The `sv2-fbtn` pill buttons within each `<td>` should remain `display: inline-block` with
`gap` handled by `margin-right: 0.25rem` on each button (since they are no longer inside
a flex container). Alternatively, wrap them in a `<div style="display:flex;flex-wrap:wrap;
gap:0.25rem">` inside the `<td>`.

---

## Verification

1. Per-page selector: confirm that selecting "5 per page" shows exactly 5 cards, selecting
   "20 per page" shows up to 20, and that navigating to page 2 preserves the selected
   per-page value.
2. Per-page selector: confirm that the selector sits visually alongside the search input
   and Search button, not on a separate line.
3. Search icon: confirm the magnifying glass icon appears inside the left side of the
   search input on all major browsers (Chrome, Firefox, Safari).
4. Filter alignment: confirm that all filter row labels (Search, Cohort, Programme, State,
   Display) have a clean common left boundary and that the button groups all start from
   the same horizontal position.
5. Run the existing test suite and confirm no regressions.

# Addendum to fix3 prompt — typography size corrections

Apply alongside the three fixes in the fix3 prompt, in the same session.

Update the following CSS rules in the `<style>` block of
`app/templates/convenor/dashboard/submitters_v2.html`. These are increases only —
no other sizing changes.

| Selector              | Property    | Current value | New value  |
|-----------------------|-------------|---------------|------------|
| `.sv2-stud-name`      | `font-size` | `0.95rem`     | `1.05rem`  |
| `.sv2-proj-title`     | `font-size` | `0.875rem`    | `1rem`     |
| `.sv2-m-val`          | `font-size` | `1.2rem`      | `1.4rem`   |
| `.sv2-stud-meta-text` | `font-size` | `0.8rem`      | `0.875rem` |
| `.sv2-role-name`      | `font-size` | `0.8rem`      | `0.875rem` |
| `.sv2-pres-info`      | `font-size` | `0.8rem`      | `0.875rem` |

All other font sizes remain unchanged — filter buttons, toolbar buttons, chips, labels,
and pager controls are secondary chrome and should stay at their current sizes.
