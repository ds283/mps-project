# Task: Fix remaining regressions in submitters_v2.html — second pass

Three issues remain after the first fix pass. Address all three. Do not modify any file
other than `app/templates/convenor/dashboard/submitters_v2.html` and, where required for
the search fix, `app/convenor/submitters.py`.

---

## Fix 1 — Risk factor button still not rendering

The risk factor resolve button is still absent from all period panels. The root cause is
that the condition is not in `submitters.html` — it is in the `project_tag` macro in
`app/templates/convenor/submitters_macros.html`. Read that macro now and locate the exact
Jinja2 condition and model attributes used to determine whether risk factors exist and
what the resolve URL is. Do not guess — read the file first.

Once you have the correct condition and URL, add the risk factor button to the period
panel in `submitters_v2.html`, in the correct position (below the status strip, above the
roles grid), using the styling already defined in the template:

```css
background:
var

(
--bs-danger-bg-subtle

)
;
color:
var

(
--bs-danger-text-emphasis

)
;
border:

1
px solid
var

(
--bs-danger-border-subtle

)
;
border-radius:
var

(
--bs-border-radius-sm

)
;
font-size:

0.875
rem

;
padding:

0.25
rem

0.6
rem

;
```

Note the `font-size` is expressed in `rem`, not `px` — see Fix 2 below for why.

---

## Fix 2 — Typography still too small

The root cause is a unit mismatch. The app's base stylesheet (`common.css`) and Bootstrap
are calibrated around `rem` units, where `1rem = 16px` in the browser but the app's
existing UI components (`.btn-sm`, `.filter-btn`, etc.) use `0.875rem` as their standard
text size. The new template was using bare `px` values which are not scaled by the
browser's rem base, causing them to render smaller than intended relative to surrounding
UI elements.

**Replace all bare `px` font-size values in the `<style>` block with `rem` equivalents
using the following mapping:**

| Element / class           | Old value | New rem value |
|---------------------------|-----------|---------------|
| `.stud-name`              | `14px`    | `0.95rem`     |
| `.stud-meta-text`         | `12px`    | `0.8rem`      |
| `.stud-meta-sep`          | `11px`    | `0.75rem`     |
| `.pill`                   | `11px`    | `0.75rem`     |
| `.proj-title`             | `13px`    | `0.875rem`    |
| `.proj-meta`              | `11px`    | `0.75rem`     |
| `.m-val` (metric numbers) | `18px`    | `1.2rem`      |
| `.m-lbl`                  | `10px`    | `0.7rem`      |
| `.metric-cap-label`       | `10px`    | `0.7rem`      |
| `.role-hd`                | `10px`    | `0.7rem`      |
| `.role-name`              | `12px`    | `0.8rem`      |
| `.role-grade`             | `11px`    | `0.75rem`     |
| `.pres-info`              | `12px`    | `0.8rem`      |
| `.llm-chip`               | `11px`    | `0.75rem`     |
| `.flag-chip`              | `11px`    | `0.75rem`     |
| `.sim-strip`              | `12px`    | `0.8rem`      |
| `.risk-btn`               | `11px`    | `0.75rem`     |
| `.xs-btn`                 | `11px`    | `0.75rem`     |
| `.status-strip`           | `12px`    | `0.8rem`      |
| `.filter-label`           | `11px`    | `0.75rem`     |
| `.fbtn`                   | `12px`    | `0.8rem`      |
| `.tbtn`                   | `12px`    | `0.8rem`      |
| `.ptab`                   | `12px`    | `0.8rem`      |
| `.pager`                  | `12px`    | `0.8rem`      |
| `.pager-btn`              | `12px`    | `0.8rem`      |
| `.act-btn`                | `12px`    | `0.8rem`      |
| `.chrome-header .title`   | `14px`    | `0.875rem`    |
| `.btn-chrome`             | `12px`    | `0.8rem`      |

Also replace any bare `px` values used for `padding`, `gap`, `margin`, `border-radius`,
`width`, and `height` in the same `<style>` block with their `rem` equivalents (divide by
16). For example, `gap: 6px` becomes `gap: 0.375rem`, `padding: 4px 10px` becomes
`padding: 0.25rem 0.625rem`. This is tedious but necessary for the template to sit
correctly alongside the app's existing rem-based components.

The exceptions are:

- `border: 1px solid ...` — keep `1px` for borders (standard practice)
- `width: 1px` separators — keep `1px`
- `border-radius: 20px` on pill filter buttons — keep `px` here as a fixed pill shape
- `width: 7px; height: 7px` on tab indicator dots — keep `px`
- `width: 9px; height: 9px` on the status dot — keep `px`

---

## Fix 3 — Replace client-side search with server-side search

The client-side search only filters cards present in the current page's DOM. Students on
other pages appear to be absent, which is misleading and potentially harmful if a
convenor concludes a student is not enrolled when they are.

Remove the client-side search implementation entirely (the JS event listener, the
`data-student-name` attributes, and the search input as currently implemented).

Replace it with a server-side name search, implemented as follows:

### Route change (`app/convenor/submitters.py`)

1. Read the `name_filter` query parameter from the request (default empty string).
2. If `name_filter` is non-empty, filter the student queryset to include only students
   whose full name (first + last) contains the search string, case-insensitively.
   Use SQLAlchemy `ilike` on the concatenated name, or filter in Python after the query
   if the ORM makes concatenation awkward. Match against both `user.first_name` and
   `user.last_name` — a student should match if the search string appears anywhere in
   their full name.
3. Pass `name_filter` into the template context so the input can be pre-populated with
   the current search value.
4. Include `name_filter` in all existing filter URL constructions so that changing
   another filter (cohort, state, etc.) does not silently clear the name search.

### Template change (`submitters_v2.html`)

1. Replace the current search input with a form `<input>` that submits via GET to
   `url_for('convenor.submitters', id=pclass.id)`, carrying the current values of all
   other active filters as hidden inputs, plus the `name_filter` value.
   Use `hx-get` only if HTMX is already loaded in the app; otherwise use a plain form
   submit (check the base template before deciding).
2. Pre-populate the input with `{{ name_filter }}` so the current filter is visible.
3. Add a small "×" clear link next to the input when `name_filter` is non-empty, linking
   to the same URL with `name_filter` omitted (i.e. cleared).
4. Include `name_filter` as a hidden input or query parameter in all filter button `href`
   links (cohort, programme, state, display) so that activating a filter button does not
   discard the name search.
5. The search input should submit on Enter (standard form behaviour) or optionally on a
   small "Search" button next to it. Do not use a live `oninput` handler that fires on
   every keystroke, as this would cause a server request per character.
6. Style the input consistently with the filter panel: same `border-radius`, `font-size`,
   `border-color`, and `padding` as `.fbtn`.

### Pagination

Ensure `name_filter` is passed through pagination links as well, so moving between pages
does not drop the search.

---

## Verification

1. Risk factor button: confirm it appears for at least one student known to have unresolved
   risk factors (visible in the review screenshot — check Harry Dhonigan and James
   Sutherland). Confirm the resolve URL is correct by comparing with the original macro.
2. Typography: open the page and confirm that student names, metric values, and project
   titles are visually comparable in size to other text in the app's existing UI (e.g.
   the navigation pills, card titles). They should not appear noticeably smaller.
3. Search — cross-page: with 46 students across multiple pages, search for a student
   known to be on page 2. Confirm they appear correctly rather than appearing absent.
4. Search — filter interaction: apply a cohort filter, then search by name. Confirm both
   filters are active simultaneously and that clicking a different state filter preserves
   the name search.
5. Search — clear: confirm the × clear link removes the name filter and returns the full
   filtered list.
6. Run the existing test suite and confirm no regressions.
7. Grep for bare `px` font-size values in the `<style>` block (excluding the permitted
   exceptions listed above) and confirm none remain.

--- 

# Addendum to fix2 prompt — colour policy correction and similarity strip styling

Apply this addendum alongside the three fixes in the fix2 prompt, in the same session.

---

## Colour policy correction

The colour policy stated in the original implementation prompt and in `.claude/rules/` is
too restrictive. Update the relevant rules file to read as follows:

> **Colour policy.** All colours in templates and component `<style>` blocks must use
> either Bootstrap 5.3 CSS custom property tokens (e.g. `var(--bs-primary)`,
> `var(--bs-danger-bg-subtle)`) or the app-level semantic tokens defined in
> `app/static/css/common.css`. No other hardcoded hex values are permitted, except `#fff`
> for white text on solid primary backgrounds and rgba-white values for ghost buttons on
> coloured headers.
>
> The `--db-orange-*` ramp is reserved for similarity concern UI elements (concern strips,
> score chips, review buttons) to maintain visual continuity with the similarity concern
> dashboard, which is themed on this ramp. The `--db-blue-*`, `--db-green-*`, and
> `--db-purple-*` ramps are available for other dashboard-themed components where
> appropriate. Do not use `--db-*` tokens for general-purpose UI — Bootstrap semantic
> tokens remain the default.

---

## Fix 4 — Restyle similarity concern strip using `--db-orange-*` tokens

The similarity concern strip in `submitters_v2.html` is currently using Bootstrap warning
tokens (`--bs-warning-*`). Replace these with the `--db-orange-*` tokens from `common.css`
to match the similarity concern dashboard's established colour language.

Apply the following token mapping throughout the similarity strip and its child elements:

| Element           | Property     | Token                                                               |
|-------------------|--------------|---------------------------------------------------------------------|
| `.sim-strip`      | `background` | `var(--db-orange-50)`                                               |
| `.sim-strip`      | `border`     | `1px solid var(--db-orange-200)`                                    |
| `.sim-lbl`        | `color`      | `var(--db-orange-800)`                                              |
| `.sim-score` chip | `background` | `var(--db-orange-100)`                                              |
| `.sim-score` chip | `color`      | `var(--db-orange-800)`                                              |
| Review button     | —            | Use `btn-outline-db-orange` class (already defined in `common.css`) |

The sim-more collapse button (if implemented from fix2) should use the same
`btn-outline-db-orange` class.

Also update the tab indicator dot for a period that has similarity concerns — if the
period tab alert dot is currently using `--bs-warning` for this case, change it to
`var(--db-orange-400)` to match.

No other elements should use `--db-orange-*` tokens.