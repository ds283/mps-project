# Prompt B — Lifecycle consolidation, layout cleanup, tasks panel, action panel styling

**Prerequisite: Prompt A is complete and verified.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

This prompt makes five related changes to `status.html` in a single editing pass:

1. Remove the `[B]` full-width lifecycle action card block and move all four lifecycle
   state CTA surfaces into the right-column "Selection lifecycle" card
2. Add "Change deadline" to the right-column lifecycle card for the selections-open state
3. Remove the "Full detail →" button from period card headers
4. Move the "Upcoming tasks" panel to sit below the actions panel, above the 60/40 split
5. Wrap the actions panel in a visually anchored card

All changes are template-only. No Python view functions are modified.

---

## Step 1 — Read before writing

Read these files in full before writing anything:

**The four lifecycle macro files** — read each completely, recording for each:

- What template variables/form objects it requires as arguments
- What it renders: forms, alerts, date pickers, buttons, informational text
- Whether it contains any POST form (and if so, the form object name and action URL)
- Whether it uses `datepicker` or `select2` JS initialisation

Files to read:

- `app/templates/convenor/dashboard/overview_cards/selection_open.html`
- `app/templates/convenor/dashboard/overview_cards/golive.html`
- `app/templates/convenor/dashboard/overview_cards/issue_confirmations.html`
- `app/templates/convenor/dashboard/overview_cards/waiting_confirmations.html`
- `app/templates/convenor/dashboard/overview_cards/selection_closed.html`
- `app/templates/convenor/dashboard/overview_cards/rollover.html`
- `app/templates/convenor/dashboard/overview_cards/rollover_not_yet.html`

**The action panel fragment:**

- `app/templates/convenor/dashboard/overview_cards/_action_panel.html`

**`status.html`** — re-read with particular attention to:

- Lines 87–125: the `[B]` lifecycle action card block and its form variables
  (`issue_form`, `golive_form`, `change_form`, `approval_data`)
- Lines 432–563: the existing right-column "Selection lifecycle" card
- Lines 700–790: the conditional cards (rollover, proposed matches, schedules)
- Lines 779–905: the tasks table
- The `{% block scripts %}` section (lines 20–85): identify which `select2` and
  `datepicker` initialisers are required by the lifecycle macros vs. used elsewhere

Produce a written plan covering:

**A. Lifecycle macro content catalogue** — for each of the four macros, list exactly
what needs to move into the right-column lifecycle card, and what form objects it
requires that are currently only injected via the macro call.

**B. JS dependency audit** — for each `datetimepicker` and `select2` initialiser in
`{% block scripts %}`, identify which template element it targets (by the element `id`)
and whether that element will still exist after the move. Flag any that are only needed
by a macro that is being removed from its current location.

**C. `change_form` dependency** — the "Close selections" button at line 552 uses
`{{ change_form.hidden_tag() }}`. Confirm this form object is passed directly from the
`status` view function (not only via the `selection_open` macro). If it is only available
via the macro, flag it — the view function will need to be checked to confirm it passes
`change_form` directly.

Do not write any code until Step 2.

---

## Step 2 — Redesign the right-column lifecycle card

The right-column "Selection lifecycle" card (currently lines 432–564 of `status.html`)
must become the single surface for all selector lifecycle state rendering.

### New card structure

```
[Card header]
  "Selection lifecycle" label

[Card body]
  [Blocking items alert strip — existing, keep as-is]

  [Lifecycle stepper — existing, keep as-is]

  [State-specific CTA content — NEW, replaces [B] block]
  {% if lifecycle == CONFIRMATIONS_NOT_ISSUED %}
      {inline content from issue_confirmations macro}
  {% elif lifecycle == WAITING_CONFIRMATIONS %}
      {inline content from waiting_confirmations macro}
  {% elif lifecycle == READY_GOLIVE %}
      {inline content from golive macro}
  {% elif lifecycle == SELECTIONS_OPEN %}
      {deadline display + Change deadline form + Close selections form}
  {% elif lifecycle == READY_MATCHING or READY_ROLLOVER %}
      {inline content from selection_closed macro}
  {% endif %}

  [Action buttons row — Reset popularity, state-specific buttons]
```

### Inlining the macro content

Do not call the macros from within the lifecycle card. Instead, inline their rendered
content directly. This is necessary because the card provides its own surrounding
structure (stepper, blocking alert) that the macros were not designed to nest inside.

For each macro, copy its substantive inner content — the alerts, forms, and informational
text — not its outer card wrapper (the macros each wrap their content in a card which
would create a card-within-a-card if called directly).

Preserve all form `action` URLs, CSRF hidden tags, and button types exactly.

### "Change deadline" for selections-open state

The `selection_open` macro renders a date picker form for changing the deadline. This
must be included in the `SELECTIONS_OPEN` branch of the lifecycle card. The form
targets `url_for('convenor.change_deadline', configid=config.id)` (confirm the exact
route name from reading the macro). The deadline display line (currently at line 538)
already exists in the right-column card — the Change deadline form should follow it.

The `change_form` form object must be available in this section. Confirm from Step 1
plan item C that it is passed directly from the view; if not, note the gap for the
view-function fix but do not modify the view function in this prompt.

### JS initialisers

Any `datetimepicker` initialiser that targets an element inside a moved macro must
remain in `{% block scripts %}`. Do not remove any datepicker or select2 initialiser
without confirming the targeted element `id` no longer exists in the template at all.
If a macro's datepicker was previously initialised inline within the macro itself
(via a `{% block scripts %}` call in the macro), check whether that still works after
inlining — if not, move the initialiser into `status.html`'s `{% block scripts %}`.

---

## Step 3 — Remove the `[B]` lifecycle action card block

After the right-column lifecycle card has been extended to cover all states, remove the
`[B]` block from `status.html` entirely (lines 98–125 approximately):

```jinja
{# [B] LIFECYCLE ACTION CARD — primary CTA #}
{% if pclass.publish %}
    {% if lifecycle == config.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED %}
        ...
    {% endif %}
{% else %}
    ...
{% endif %}
```

The unpublished-class alert (`This project class is not published...`) must be
preserved. Move it to sit between the actions panel and the 60/40 split — it is not
a lifecycle state and should display regardless of state when `not pclass.publish`.

The macro imports at the top of `status.html` for the four lifecycle macros can be
removed once their content is inlined, but only after confirming the macros are no
longer called anywhere in the file. Keep the `rollover.html` and `rollover_not_yet.html`
imports — those cards remain below the split.

---

## Step 4 — Remove "Full detail →" button

In the period card header (inside the `{% for p in config.periods %}` loop, around
line 183), remove this button entirely:

```jinja
<a class="btn btn-xs btn-outline-secondary"
   href="{{ url_for('convenor.status', id=pclass.id) }}">
    Full detail <i class="fas fa-arrow-right ms-1"></i>
</a>
```

This button currently links back to the same page and serves no purpose. Do not replace
it with anything.

---

## Step 5 — Move tasks panel below actions panel

The tasks table (currently lines 779–905, inside `{% if num_to_dos > 0 %}`) must move
to sit between the actions panel and the 60/40 split.

### New placement

```jinja
{# [A] ALERT BANNERS — centralised action panel #}
{{ action_panel(action_items) }}        {# existing #}

{# [T] UPCOMING TASKS — quick-access panel #}
{% if num_to_dos > 0 %}
    ... tasks card ...
{% endif %}

{# unpublished warning if applicable #}

{# [G] TWO-COLUMN LAYOUT #}
<div class="row g-3 mt-1 mb-3">
```

### Task card visual treatment

Replace the current standalone full-width table with a `card mb-3`:

```html

<div class="card mb-3">
    <div class="card-header d-flex justify-content-between align-items-center py-2">
        <span class="fw-semibold text-body-secondary small">
            <i class="fas fa-tasks fa-fw"></i> Upcoming tasks
        </span>
        <div class="d-flex align-items-center gap-2">
            <span class="badge bg-secondary rounded-pill">{{ num_to_dos }}</span>
            <a href="{{ url_for('convenor.todo_list', id=pclass.id) }}"
               class="btn btn-xs btn-outline-secondary">
                View all <i class="fas fa-arrow-right ms-1"></i>
            </a>
        </div>
    </div>
    <div class="card-body p-0">
        {# existing table markup, unchanged #}
    </div>
</div>
```

The table inside `card-body p-0` should use `table-sm mb-0` and `table-responsive` to
fit within the card. The orange `bg-warning` header from the original must not be
carried over — use the card header pattern above instead. The table content (columns,
row colouring, dropdown actions) is unchanged.

Remove the tasks block from its original position below the two-column layout (the
`{% if num_to_dos > 0 %}` block at approximately line 779). Confirm it is entirely
removed — do not leave a stub or comment.

---

## Step 6 — Wrap the actions panel in a containing card

In `app/templates/convenor/dashboard/overview_cards/_action_panel.html`, the panel
currently renders a bare sequence of bordered rows without an outer container.

Wrap the entire panel output in:

```html
{% if action_items %}
<div class="card mb-3 border-warning">
    <div class="card-header d-flex align-items-center justify-content-between py-2"
         style="background: var(--bs-warning-bg-subtle)">
        <span class="fw-semibold small" style="color: var(--bs-warning-text-emphasis)">
            <i class="fas fa-exclamation-triangle fa-fw"></i> Items requiring attention
        </span>
        <span class="badge rounded-pill"
              style="background: var(--bs-warning-text-emphasis); color: var(--bs-warning-bg-subtle)">
            {{ action_items | length }}
        </span>
    </div>
    <div class="card-body p-2">
        {# existing action item rows #}
    </div>
</div>
{% endif %}
```

When `action_items` is empty, render nothing — remove the existing "all clear" row
entirely. The absence of the panel is itself the "all clear" signal; an empty state
card adds visual noise on days when no actions are needed.

The existing individual action item rows inside the card body are unchanged — keep their
severity-coloured left borders (`border-start border-3 border-danger` etc.), their
message text, and their action buttons exactly as they are.

---

## Step 7 — Verification

1. **`[B]` block removed**: Grep `status.html` for `LIFECYCLE ACTION CARD`. Must return
   zero results.

2. **Macro imports cleaned**: Grep `status.html` for each of the four imports:
   `selection_open`, `golive`, `issue_confirmations`, `waiting_confirmations`. Each must
   return zero results (these macros are no longer called). The `rollover` and
   `rollover_not_yet` imports must still be present.

3. **All lifecycle states covered**: Confirm the right-column lifecycle card contains
   a branch for each of:
   `SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED`,
   `SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS`,
   `SELECTOR_LIFECYCLE_READY_GOLIVE`,
   `SELECTOR_LIFECYCLE_SELECTIONS_OPEN`,
   `SELECTOR_LIFECYCLE_READY_MATCHING`,
   `SELECTOR_LIFECYCLE_READY_ROLLOVER`.

4. **"Full detail →" button removed**: Grep `status.html` for `Full detail`. Must
   return zero results.

5. **Tasks table location**: Grep `status.html` for `top_to_dos`. Confirm it appears
   only once, in the new location between the actions panel and the 60/40 split.
   Confirm it does not appear in the original location below the two-column layout.

6. **`change_form` accessible**: Confirm `change_form.hidden_tag()` appears inside the
   `SELECTOR_LIFECYCLE_SELECTIONS_OPEN` branch of the right-column lifecycle card.
   Grep for `change_form` — confirm all occurrences are in the right-column card, not
   in the removed `[B]` block.

7. **Unpublished warning preserved**: Grep `status.html` for `not published` (or the
   exact text from the alert). Confirm it still renders, now placed between the actions
   panel and the 60/40 split.

8. **JS initialisers intact**: For each `datetimepicker` initialiser ID in
   `{% block scripts %}`, confirm the corresponding element `id` still exists in the
   template body. Flag any orphaned initialisers (element no longer present) — these
   should be removed.

9. **Action panel empty state removed**: Grep `_action_panel.html` for `all clear` or
   `No actions required`. Must return zero results.

10. **Tasks card header style**: Grep `status.html` for `bg-warning` inside the tasks
    block. Must return zero results — the orange header must be gone.

Report results of all ten checks. Fix any failures before finishing.