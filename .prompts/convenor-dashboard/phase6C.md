# Prompt C — Retire sub-tab bar, `overview_nav.html`, and `capacity` route

**Prerequisite: Prompts A and B are complete and verified. Phase 5d is complete.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

Remove the three-tab sub-navigation bar ("Status / Submission periods / Capacity
estimates") that currently appears below the pill navigation on the convenor overview
pages. This requires:

1. Retiring `convenor/dashboard/overview_nav.html` — the template that defines the
   sub-tab bar
2. Retiring the `convenor.capacity` route and its template
3. Changing `status.html` (the only remaining consumer of `overview_nav.html`) to
   extend `pclass_base.html` directly
4. Cleaning up a missed inbound link to `convenor.periods` in `overview_nav.html`
   that was not fixed in Phase 5d

---

## Step 1 — Read before writing

Read these files in full:

- `app/templates/convenor/dashboard/overview_nav.html` — note it currently extends
  `nav.html` directly (not `pclass_base.html`), and still contains a link to
  `convenor.periods` at line 15 which is a broken reference from Phase 5d
- `app/templates/convenor/dashboard/status.html` — confirm it extends
  `overview_nav.html` and uses `subpane` to set active tab states; record every
  occurrence of `subpane` in the file
- `app/templates/convenor/dashboard/pclass_base.html` — confirm it extends
  `convenor/dashboard/nav.html` and that switching `status.html` to extend it
  directly will preserve the persistent header and pill bar

Then perform these grep searches and record every result:

1. Grep all of `app/` for `extends "convenor/dashboard/overview_nav.html"` —
   this identifies every template that will need its `extends` changed
2. Grep all of `app/` for `convenor.capacity` — identifies every inbound link
   to the capacity route (Python redirects and Jinja2 `url_for` calls)
3. Grep all of `app/` for `convenor.periods` — confirms whether any remaining
   references exist beyond the one in `overview_nav.html` line 15 (Phase 5d
   should have cleared these; flag any survivors)
4. Grep all of `app/` for `subpane` — identifies every template that sets or
   reads `subpane`, since this variable drives the active-tab logic in
   `overview_nav.html` and becomes redundant once the tab bar is removed
5. Grep all of `app/` for `capacity.html` — confirms the template is only
   rendered by the `convenor.capacity` view function
6. Grep `app/convenor/dashboard.py` for `def capacity` — locate and read the
   full view function

Produce a written plan with:

**A. Consumer list** — every template that extends `overview_nav.html` (from grep 1).
Expected: only `status.html`. If others are found, list them and flag — they need
individual assessment before `overview_nav.html` is deleted.

**B. Capacity inbound links** — every location linking to `convenor.capacity`
(from grep 2). These must all be removed or redirected in Step 4.

**C. Surviving `convenor.periods` references** — any remaining after Phase 5d
(from grep 3). These are bugs that must be fixed in Step 4 regardless.

**D. `subpane` usage** — every template that sets `subpane` as a variable
(from grep 4). Once `overview_nav.html` is deleted, `subpane` serves no purpose;
confirm these are only in templates that extend `overview_nav.html`.

**E. Capacity view function** — record the full signature, what it queries, and
what it passes to the template. This determines whether the route has any side
effects or is purely read-only.

Do not write any code until Step 2.

---

## Step 2 — Fix the surviving `convenor.periods` reference

In `app/templates/convenor/dashboard/overview_nav.html`, line 15:

```jinja
{# Before #}
<a class="nav-link {% if subpane=='periods' %}active{% endif %}"
   href="{{ url_for('convenor.periods', id=pclass.id) }}">
    Submission periods
</a>

{# After — fix the broken link before deleting the file #}
{# (This tab will be removed entirely in Step 3, but fix it now
    in case this step needs to be rolled back independently) #}
<a class="nav-link {% if subpane=='status' %}active{% endif %}"
   href="{{ url_for('convenor.status', id=pclass.id) }}">
    Submission periods
</a>
```

Also fix any other surviving `convenor.periods` references identified in Step 1 plan C,
following the same replacement: `url_for('convenor.periods', ...)` →
`url_for('convenor.status', ...)`.

---

## Step 3 — Change `status.html` to extend `pclass_base.html`

In `app/templates/convenor/dashboard/status.html`, change the single `extends` line:

```jinja
{# Before #}
{% extends "convenor/dashboard/overview_nav.html" %}

{# After #}
{% extends "convenor/dashboard/pclass_base.html" %}
```

`overview_nav.html` sets `subpane` and `state` variables and defines `tabblock`.
After this change:

- `subpane` is no longer needed — remove any `{% set subpane = ... %}` line in
  `status.html` if present
- `tabblock` is no longer meaningful — `pclass_base.html` does not define `tabblock`
  and will silently ignore any `{% block tabblock %}` override; if `status.html`
  defines one, remove it
- `state = config.selector_lifecycle` may already be set in `status.html` as
  `lifecycle = config.selector_lifecycle` (line 90) — confirm no duplicate is
  introduced

For any other templates found in Step 1 plan A that also extend `overview_nav.html`,
apply the same `extends` change.

---

## Step 4 — Remove the `conveyor.capacity` route and template

### 4a — Remove inbound links

For every location identified in Step 1 plan B, remove or replace the link:

- Jinja2 `url_for('convenor.capacity', ...)` in templates: remove the enclosing
  element entirely (do not replace with a dead link)
- Python redirects to `url_for('convenor.capacity', ...)`: replace with
  `url_for('convenor.status', id=pclass.id)` using the appropriate `pclass.id`
  variable in scope at that point

The one known location is `overview_nav.html` line 20 — this is being deleted in
Step 4c, so no separate fix is needed there.

### 4b — Remove the `capacity` view function

In `app/convenor/dashboard.py`, remove the `capacity` view function and its route
decorator entirely.

Confirm before removing:

- The function has no POST handling (read it fully)
- It sets no session state
- It performs no side effects (write operations, email sends, etc.)

If any side effects are found, stop and report rather than proceeding.

### 4c — Delete the template

Delete `app/templates/convenor/dashboard/capacity.html`.

---

## Step 5 — Delete `overview_nav.html`

Delete `app/templates/convenor/dashboard/overview_nav.html`.

This file is safe to delete once:

- All templates that extended it have been updated (Step 3)
- All inbound `url_for` references to `convenor.capacity` and `convenor.periods`
  within it are moot (the file is being deleted)

---

## Step 6 — Verification

1. **`overview_nav.html` gone**: Confirm
   `app/templates/convenor/dashboard/overview_nav.html` does not exist.

2. **`capacity.html` gone**: Confirm
   `app/templates/convenor/dashboard/capacity.html` does not exist.

3. **`capacity` view function gone**: Grep `app/convenor/dashboard.py` for
   `def capacity`. Must return zero results.

4. **No orphaned `extends`**: Grep all of `app/templates/` for
   `extends "convenor/dashboard/overview_nav.html"`. Must return zero results.

5. **No `convenor.capacity` references**: Grep all of `app/` for
   `convenor.capacity`. Must return zero results.

6. **No `convenor.periods` references**: Grep all of `app/` for
   `convenor.periods`. Must return zero results.

7. **`status.html` extends correctly**: Read line 1 of `status.html`. Confirm
   it reads `{% extends "convenor/dashboard/pclass_base.html" %}`.

8. **`subpane` cleaned up**: Grep `status.html` for `subpane`. Must return zero
   results — no references to the now-defunct variable should remain.

9. **`tabblock` cleaned up**: Grep `status.html` for `tabblock`. Must return
   zero results — the block is no longer meaningful and should not be defined.

10. **Inheritance chain intact**: Confirm the chain for `status.html` is now:
    `status.html` → `pclass_base.html` → `nav.html` → `base_app.html` → `base.html`
    Do this by reading the `extends` line of each file in the chain.

11. **Persistent header still renders**: Confirm `pclass_base.html` is unchanged —
    same line count and `extends "convenor/dashboard/nav.html"` as before this prompt.
    The persistent header and pill bar must not have been accidentally modified.

Report results of all eleven checks. Fix any failures before finishing.