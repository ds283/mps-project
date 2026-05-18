# Addendum to fix3 prompt — toolbar, display options, sort order, link decoration

Apply alongside the fix3 prompt and its typography addendum, in the same session.
Changes touch both `app/templates/convenor/dashboard/submitters_v2.html` and
`app/convenor/submitters.py`.

---

## Change 1 — Consolidate toolbar buttons into dropdowns

Replace the flat button groups in the toolbar with three dropdowns, matching the
existing pattern already used for the Pipeline button. Delete all remains as a flat
danger button — do not group it.

The four toolbar groups after this change should be:

**Email ▾**

- "Email via local client" — the existing `mailto:` href (currently "Email filtered")
- "Send email" — the existing system email href (currently "Email matching", admin/root/emailer only)

**Publish ▾** (only rendered when `pclass.publish` is true)

- "Publish all" — existing href
- "Unpublish all" — existing href

**Markers ▾**

- "Populate" — existing href, only when `config.project_class.uses_marker`
- "Remove" — existing href

**Pipeline ▾** — unchanged

**Delete all** — unchanged, flat danger button

Each dropdown should use the same structure as the existing Pipeline dropdown:

```html

<div class="dropdown">
    <a class="sv2-tbtn dropdown-toggle" data-bs-toggle="dropdown" href="#">
        <i class="fas fa-{icon} fa-fw"></i> {Label}
    </a>
    <ul class="dropdown-menu dropdown-menu-dark">
        <li><a class="dropdown-item d-flex gap-2" href="...">...</a></li>
        ...
    </ul>
</div>
```

Suggested icons: Email → `fa-envelope`, Publish → `fa-eye`, Markers → `fa-user-tag`.

If the Markers dropdown would have no visible items (neither Populate nor Remove
conditions are met), omit the dropdown entirely. If only one item would be visible
(e.g. `uses_marker` is false so Populate is hidden but Remove is shown), still render
the dropdown — a single-item dropdown is preferable to breaking the pattern.

---

## Change 2 — Simplify Display options and wire sort order

### Template

Remove the "Name + number" option from the Display filter row. The remaining three
options are:

| `data_display` value | Label            |
|----------------------|------------------|
| `name`               | Name             |
| `number`             | Candidate number |
| `both-number`        | Number + name    |

Update all references to `'both-name'` in the template (filter links, conditionals) to
remove them. Any existing URL that arrives with `data_display=both-name` should be
treated the same as `name` by the route (see below).

### Route (`app/convenor/submitters.py`)

1. Treat `data_display=both-name` as equivalent to `data_display=name` — normalise it
   on read so old bookmarks do not break.

2. Apply sort order to the submitter queryset based on `data_display`:

    - `name` → order by `User.last_name` ascending, then `User.first_name` ascending.
      Join through `StudentData` → `User` as needed. Check the existing query to see
      what joins are already present before adding new ones.
    - `number` or `both-number` → order by `StudentData.exam_number` ascending.

   Apply the `order_by` before `.paginate()` so sort is consistent across pages.

3. Pass the normalised `data_display` value back into the template context.

---

## Change 3 — Remove underlines from links

Add `text-decoration: none` to the following selectors in the `<style>` block. The
existing `:hover { text-decoration: underline }` rules on these selectors should be
retained — underline on hover is a reasonable affordance and should stay.

| Selector           | Note                             |
|--------------------|----------------------------------|
| `.sv2-stud-name`   | Student name link                |
| `.sv2-proj-title`  | Project title link               |
| `.sv2-proj-meta a` | Owner name and Change links      |
| `.sv2-role-name`   | Supervisor and marker name links |

Additionally, find the candidate number `<a>` element in the card header (rendered when
`is_admin or is_root` and `data_display` includes the number). It is currently rendered
without a class. Add `class="sv2-stud-number-link"` to it and add the following rule:

```css
.sv2-stud-number-link {
    text-decoration: none;
    color: var(--bs-primary);
}

.sv2-stud-number-link:hover {
    text-decoration: underline;
    color: var(--bs-primary);
}
```

Do not add `text-decoration: none` globally to all `<a>` elements in the template scope —
apply it only to the named selectors above.

---

## Verification

1. Toolbar: confirm four dropdowns (Email, Publish, Markers, Pipeline) plus flat Delete all
   are present. Confirm Publish dropdown is absent when `pclass.publish` is false.
2. Email dropdown: confirm "Email via local client" opens a `mailto:` link and "Send email"
   is only visible to admin/root/emailer users.
3. Display: confirm "Name + number" option is gone. Confirm selecting "Name" sorts cards
   alphabetically by last name. Confirm selecting "Candidate number" sorts by exam number.
   Confirm selecting "Number + name" also sorts by exam number. Confirm sort is stable
   across pages (page 2 continues the sort, not a fresh sort).
4. Display: confirm a URL with `data_display=both-name` renders as the "Name" display
   without an error.
5. Link decoration: confirm student names, project titles, owner/Change links, and role
   names have no underline at rest. Confirm underline appears on hover. Confirm candidate
   number link has no underline at rest.
6. Run the existing test suite and confirm no regressions.