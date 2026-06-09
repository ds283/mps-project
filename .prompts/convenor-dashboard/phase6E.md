# Prompt E — Text size consistency and button layout in Selection lifecycle card

**Prerequisite: Prompt D is complete and verified.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

Two targeted fixes to the `SELECTOR_LIFECYCLE_SELECTIONS_OPEN` branch inside the
right-column "Selection lifecycle" card:

1. The Change deadline form renders at full body font size via `wtf.render_field`,
   which is visually inconsistent with the `small` text used throughout the rest of
   the card. Replace with manually-constructed compact form markup.

2. The "Change deadline" submit button and "Close selections" button are currently
   stacked vertically because they live in separate `<form>` elements each with their
   own right-aligned wrapper. They should sit on the same horizontal row.

---

## Step 1 — Read before writing

Read `app/templates/convenor/dashboard/status.html`, focusing on lines 750–770
(the Change deadline form and Close selections form in the `SELECTIONS_OPEN` branch).

Also read `app/templates/macros.html` and locate the `date_field` macro definition.
Record exactly what HTML it renders — specifically whether it produces a `<label>`,
a wrapping `<div>`, and what classes it applies to the `<input>`. This determines
whether `date_field` can be used in compact form or whether the input must be
constructed manually.

Also read `app/templates/base_form.html` to understand whether `wtf.render_field`
with `button_size='sm'` produces a `btn-sm` button or a `btn-xs` button — confirm
which class the "Change deadline" submit button currently has.

---

## Step 2 — Replace the Change deadline form with compact markup

The current form (lines ~751–761) uses `date_field` and `wtf.render_field` which
both produce full-size Bootstrap form groups. Replace the entire `<div class="mt-2">`
block (lines ~750–770, containing both forms) with the following compact version.

The key changes:

- `form-control form-control-sm` on the date input (Bootstrap small input size)
- `<label class="form-label small mb-1">` for the label
- Checkbox rendered manually with `form-check-label small` rather than via
  `wtf.render_field`
- Both action buttons (`btn-xs`) on the same row using a shared `d-flex` wrapper
  that spans both forms

Because HTML does not allow nested `<form>` elements, the two-button single-row
layout requires either:

**Option A** — A single `<form>` with two submit buttons using different `formaction`
attributes. This is the cleanest approach: one form, one CSRF token, two submit
buttons each pointing to a different action URL via `formaction`.

**Option B** — Two adjacent `<form>` elements styled to appear inline, with the
button row using flexbox to lay them out horizontally.

**Use Option A** — it is simpler, avoids the flex-across-forms complexity, and is
valid HTML5. The CSRF token from `change_form.hidden_tag()` is included once.

```jinja
<div class="mt-2 pt-2 border-top">
    <form action="{{ url_for('convenor.adjust_selection_deadline', configid=config.id) }}"
          method="POST" name="adjust_selection_deadline">
        {{ change_form.hidden_tag() }}

        {# Date input — compact #}
        <div class="mb-1">
            <label for="live_datetimepicker" class="form-label small mb-1">
                {{ change_form.live_deadline.label.text }}
            </label>
            <div class="input-group input-group-sm" id="live_datetimepicker">
                {{ change_form.live_deadline(class="form-control form-control-sm",
                                             placeholder="DD/MM/YYYY") }}
                <span class="input-group-text">
                    <i class="fas fa-calendar fa-fw"></i>
                </span>
            </div>
        </div>

        {# Notify convenor checkbox — compact #}
        <div class="form-check mb-2">
            {{ change_form.notify_convenor(class="form-check-input") }}
            <label class="form-check-label small"
                   for="{{ change_form.notify_convenor.id }}">
                {{ change_form.notify_convenor.label.text }}
            </label>
        </div>

        {# Both action buttons on a single row #}
        <div class="d-flex gap-1 justify-content-end">
            <button type="submit"
                    formaction="{{ url_for('convenor.adjust_selection_deadline', configid=config.id) }}"
                    class="btn btn-xs btn-outline-secondary">
                <i class="fas fa-clock fa-fw"></i> Change deadline
            </button>
            <button type="submit"
                    formaction="{{ url_for('convenor.perform_close_selections', configid=config.id) }}"
                    class="btn btn-xs btn-outline-danger">
                <i class="fas fa-lock fa-fw"></i> Close selections
            </button>
        </div>
    </form>
</div>
```

Note that with Option A, `perform_close_selections` receives the form POST including
the CSRF token and the deadline field values. Confirm that `perform_close_selections`
ignores unexpected form fields gracefully — Flask-WTF validators only check the fields
declared on the form, so extra fields in the POST data are silently ignored. This is
safe.

---

## Step 3 — Apply consistent `small` sizing to all card-body text

The card body currently mixes `small` text (the compact status line, supervision
units summary, etc.) with unsized text from `wtf.render_field`. Now that Step 2
replaces the form fields with manually-constructed markup, confirm that every text
element inside the lifecycle card body uses `small` or `text-body-secondary` or
explicit `style="font-size:10px"` (for tile labels only).

Scan the lifecycle card body (approximately lines 523–807 of the current file) and
find any text-bearing elements that lack a size class. Specifically check:

- The deadline display line (`Deadline: <strong>...`) at approximately line 538 —
  confirm it has `small` or `p class="small"`
- The blocking items alert strip — confirm it has `small` on the alert div
- The lifecycle stepper labels — confirm they use `style="font-size:10px"`
- The compact status line added in Prompt D — confirm it has `small` on its wrapper
  `<div>`
- The new form markup from Step 2 — all labels use `form-label small` or
  `form-check-label small` as shown above

For any element found without a size class, add `small` to its containing element.
Do not add `small` to the card header — the `fw-semibold text-secondary small` class
is already there.

---

## Step 4 — Verification

1. **No `wtf.render_field` in lifecycle card**: Grep `status.html` for
   `wtf.render_field` within the right-column lifecycle card section (lines ~515–808).
   Must return zero results. (Occurrences elsewhere in the file, e.g. in other
   lifecycle state branches that use full forms like `golive`, are acceptable.)

2. **Single form for selections-open actions**: Within the `SELECTIONS_OPEN` branch,
   grep for `<form`. Must appear exactly once (the combined form from Step 2). The
   separate Close selections `<form>` from Prompt D must no longer exist.

3. **`formaction` on both buttons**: Within the `SELECTIONS_OPEN` branch, grep for
   `formaction`. Must appear exactly twice — once on the Change deadline button and
   once on the Close selections button.

4. **`change_form.hidden_tag()` once**: Grep the `SELECTIONS_OPEN` branch for
   `hidden_tag`. Must appear exactly once.

5. **`btn-xs` on both action buttons**: Within the `SELECTIONS_OPEN` branch, grep for
   `btn-xs`. Must appear on both the Change deadline and Close selections buttons.
   Neither should use `btn-sm`.

6. **`form-control-sm` on date input**: Grep the `SELECTIONS_OPEN` branch for
   `form-control-sm`. Must appear on the deadline input.

7. **`form-label small` on labels**: Grep the `SELECTIONS_OPEN` branch for
   `form-label`. Each occurrence must also have `small` on the same element.

8. **Deadline display line has `small`**: Grep for `Deadline:` in the lifecycle card.
   Confirm the containing element has class `small`.

Report results of all eight checks. Fix any failures before finishing.