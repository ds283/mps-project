# Convenor overview redesign — Implementation

## Reference

The file `convenor-overview-mockup-v2.html` (attached or available in the project) is the
authoritative visual reference. Read it in full before writing any code. Every structural and
visual decision described below is embodied in that mockup. When in doubt, the mockup wins.

---

## Step 1 — Reconnaissance (read before writing anything)

Read the following files in full and produce a written plan before touching any code.

```
app/static/css/common.css
app/templates/convenor/dashboard/status.html
app/templates/convenor/dashboard/overview_cards/_action_panel.html
app/templates/convenor/dashboard/overview_cards/issue_confirmations.html
app/templates/convenor/dashboard/overview_cards/waiting_confirmations.html
app/templates/convenor/dashboard/overview_cards/golive.html
app/templates/convenor/dashboard/overview_cards/selection_open.html
app/templates/convenor/dashboard/overview_cards/selection_closed.html
app/templates/convenor/dashboard/overview_cards/rollover.html
app/templates/convenor/dashboard/overview_cards/blocking_task_list.html
app/templates/convenor/dashboard/pclass_base.html
app/convenor/dashboard.py   (the `status` view function and its context variables)
```

Your written plan must confirm:

- Which CSS tokens you will add to `common.css` (names and values)
- The exact rendering logic for each lifecycle state's right-column lifecycle card
- Which template files become unused/deprecated once the `[B]` block is removed
- Any Jinja2 variables needed from the view that are not already in context

Do not write any code until this plan is reviewed.

---

## Step 2 — CSS tokens in `common.css`

**This is the first code change. All subsequent work depends on it.**

Add a block of named semantic CSS custom properties to `common.css`. These replace every
hardcoded font-size and padding value in the new template code. No raw px or rem values
are permitted anywhere in the templates or component `<style>` blocks — use these tokens only.

Define the following tokens. The names are semantic (what the element is), not mechanical:

```css
/* ── Convenor dashboard typography tokens ─────────────────────── */

/* Standard card body / list item text */
--cd-text-body:
var

(
--bs-body-font-size

)
; /* inherits 1rem base */

/* Sub-section header labels ("Marking events", "Supervision", etc.) */
--cd-text-subsection:

0.8125
rem

;

/* Supporting / secondary body text (date lines, summary lines) */
--cd-text-secondary:

0.875
rem

; /* = Bootstrap .small */

/* Metric tile values */
--cd-text-metric-val:

0.875
rem

;

/* Metric tile labels, badge text, aggregate notes */
--cd-text-micro:

0.625
rem

;

/* Persistent header bar metric strip */
--cd-text-header-meta:

0.75
rem

;

/* Lifecycle form labels (inside lifecycle-action-area) */
--cd-text-form-label:

0.75
rem

;

/* Event name in marking event rows */
--cd-text-event-name:

0.8125
rem

;

/* CTA panel title */
--cd-text-cta-title:

0.8125
rem

;

/* CTA panel description */
--cd-text-cta-desc:

0.75
rem

;

/* Column labels ("SUBMISSION MANAGEMENT" etc.) */
--cd-text-col-label:

0.6875
rem

;
```

**Do not add tokens for sizes already covered by Bootstrap utility classes:**

- Body copy that uses Bootstrap `.small` stays as `.small`
- Buttons use `.btn-xs` (already in common.css) or `.btn-sm` — not custom tokens

After adding these tokens, run:

```bash
grep -n 'cd-text-' app/static/css/common.css
```

and confirm all tokens are present before proceeding.

---

## Step 3 — Action panel redesign (`_action_panel.html`)

The action panel macro receives `action_items` (a list of `ConvenorAction` objects). Redesign it
as follows. Do not change the Python-side `ConvenorAction` model or the logic that generates
`action_items` — only the Jinja2 macro.

**Structure of each row:**

```
[4px left border, colour by severity] [icon] [title + description] [CTA button(s)]
```

**Severity → left border colour → row background:**

| Severity    | Border                  | Background                    |
|-------------|-------------------------|-------------------------------|
| `blocking`  | `var(--bs-danger)`      | `var(--bs-danger-bg-subtle)`  |
| `warning`   | `#f0ad00` (BS5 warning) | `var(--bs-warning-bg-subtle)` |
| `info`      | `var(--bs-info)`        | `var(--bs-body-bg)` (no tint) |
| `success`   | `var(--bs-success)`     | `var(--bs-success-bg-subtle)` |
| `secondary` | `var(--bs-secondary)`   | `var(--bs-body-bg)`           |

**Text sizing:**

- Title: `font-size: var(--cd-text-cta-title); font-weight: 600`
- Description: `font-size: var(--cd-text-cta-desc); color: var(--bs-secondary-color)`
- Title colour for blocking: `var(--bs-danger-text-emphasis)`; for warning: `var(--bs-warning-text-emphasis)`; for
  success: `var(--bs-success-text-emphasis)`

**CTA buttons:**

- Blocking severity: solid `btn btn-sm btn-danger` (not outline, not btn-xs — these are primary actions)
- Warning severity: solid `btn btn-sm btn-warning`
- Info / secondary severity: `btn btn-sm btn-outline-secondary`
- `btn-sm` sizing is correct here — not `btn-xs`

The panel header retains its `<i class="fas fa-exclamation-triangle">` icon and item count badge.

---

## Step 4 — Period card: marking events + supervision restructure

This affects the period card body inside `status.html` (the block that renders for each
`SubmissionPeriodRecord p` in `config.periods`).

### 4a. Marking events sub-section

Replace the current section header row with a standard sub-section header pattern:

```html

<div class="d-flex justify-content-between align-items-center mb-1">
    <span class="fw-semibold text-secondary" style="font-size: var(--cd-text-subsection)">
        <i class="fas fa-calendar-check fa-fw"></i> Marking events
    </span>
    <div class="d-flex gap-1">
        <a href="{{ url_for('convenor.add_marking_event', period_id=p.id) }}"
           class="btn btn-outline-secondary btn-xs">
            <i class="fas fa-plus fa-fw"></i> Add event
        </a>
        <a href="{{ url_for('convenor.period_marking_events_inspector', period_id=p.id) }}"
           class="btn btn-outline-secondary btn-xs">
            View all events <i class="fas fa-arrow-right ms-1"></i>
        </a>
    </div>
</div>
```

**Remove** the old "Full detail →" button entirely (it pointed back to the same page).

### 4b. Event list rows

Each event row gets a consistent **"Workflows"** button regardless of state. The old
state-conditional logic (closed → "Workflows", active → "Inspect") is replaced:

```jinja2
{% for event in events %}
    <div class="list-group-item px-2 py-1
        {% if event.workflow_state >= MarkingEventWorkflowStates.OPEN
           and event.workflow_state < MarkingEventWorkflowStates.CLOSED %}
            border-start border-3 border-info
        {% endif %}">
        <div class="d-flex justify-content-between align-items-center gap-2">
            <div>
                <span class="fw-semibold" style="font-size: var(--cd-text-event-name)">
                    {{ event.name }}
                </span>
                {# status badge — unchanged #}
                {% set wf_count = event.workflows.count() %}
                {% if wf_count > 0 %}
                    <span class="text-body-secondary ms-1"
                          style="font-size: var(--cd-text-micro)">
                        {{ wf_count }} workflow{{ 's' if wf_count != 1 }}
                    </span>
                {% endif %}
            </div>
            <div class="d-flex gap-1 flex-shrink-0">
                {% if event.workflow_state != MarkingEventWorkflowStates.CLOSED %}
                    <a href="{{ url_for('convenor.generate_marking_event_feedback',
                                       event_id=event.id) }}"
                       class="btn btn-outline-secondary btn-xs">
                        <i class="fas fa-file-export fa-fw"></i> Generate feedback
                    </a>
                    <a href="{{ url_for('convenor.marking_event_conflation_reports',
                                       event_id=event.id) }}"
                       class="btn btn-outline-secondary btn-xs">
                        <i class="fas fa-compress-arrows-alt fa-fw"></i> Conflation reports
                    </a>
                {% endif %}
                <a href="{{ url_for('convenor.event_marking_workflows_inspector',
                                    event_id=event.id) }}"
                   class="btn btn-outline-secondary btn-xs">
                    <i class="fas fa-search fa-fw"></i> Workflows
                </a>
            </div>
        </div>
    </div>
{% endfor %}
```

### 4c. Aggregate metric tiles

Move the 4-cell grid to **below** the event list (currently it is above it). Add:

- The `Complete` tile label becomes **"Complete marking reports"**
- Below the grid, add a note:
  ```html
  <p class="text-body-secondary mb-1" style="font-size: var(--cd-text-micro)">
      <i class="fas fa-info-circle fa-fw"></i>
      Totals across all events in this period
  </p>
  ```

The `Generate feedback` and `Conflation reports` buttons that currently appear after the metric
grid as a second button group are **removed** — they now live in the event rows (Step 4b).

### 4d. Supervision sub-section — sibling to Marking events

After the metric tiles and note, add a horizontal rule separator, then the Supervision section as
a **sibling** (not a nested child) of the Marking events section:

```html

<hr style="border: none; border-top: 1px solid var(--bs-border-color); margin: 8px 0">

{% if p.has_units %}
<div class="d-flex justify-content-between align-items-center mb-1">
        <span class="fw-semibold text-secondary" style="font-size: var(--cd-text-subsection)">
            <i class="fas fa-chalkboard-teacher fa-fw"></i> Supervision
        </span>
    <div class="d-flex gap-1">
        <a href="{{ url_for('convenor.inspect_period_units', period_id=p.id) }}"
           class="btn btn-outline-secondary btn-xs">Inspect units</a>
        <a href="{{ url_for('convenor.populate_supervision_events', period_id=p.id) }}"
           class="btn btn-outline-secondary btn-xs">Populate events</a>
    </div>
</div>
<p class="text-body-secondary mb-1" style="font-size: var(--cd-text-secondary)">
    {{ p.number_units }} supervision unit{{ 's' if p.number_units != 1 }}
    {% set first_unit = p.ordered_units.first() %}
    {% set all_units = p.ordered_units.all() %}
    {% if first_unit and all_units %}
    &middot;
    {% if first_unit.start_date %}wk {{ first_unit.start_date.strftime("%d %b") }}{% endif %}
    &ndash;
    {% if all_units[-1].end_date %}wk {{ all_units[-1].end_date.strftime("%d %b") }}{% endif %}
    {% endif %}
</p>
{# TODO: surface attendance alerts here when supervision event data is available #}
{# e.g. supervisor not recording attendance, student absent 2+ consecutive meetings #}
{% endif %}
```

---

## Step 5 — Lifecycle card: absorb [B] block into right column

The `[B]` block in `status.html` (lines ~98–125) renders a different lifecycle macro depending on
`config.selector_lifecycle`. It must be **removed entirely**. Its content is absorbed into the
right-column "Selection lifecycle" card, which becomes lifecycle-state-aware.

### The exception: `READY_GOLIVE`

At `READY_GOLIVE`, the go-live form is too large for the 40% right column. Instead:

- Render the go-live form as a **full-width card** between `{{ action_panel(...) }}` and the
  two-column layout
- **Suppress** the right-column "Selection lifecycle" card entirely at this state

For all other states, the right-column lifecycle card absorbs the relevant inline content as
described below.

### Right-column lifecycle card body — per-state content

The card always starts with the 5-step stepper and deadline line (unchanged). Below the stepper,
add a state-conditional block:

```jinja2
{% if lifecycle == config.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED %}
    {# Inline issue-confirmations form — replaces issue_confirmations macro #}
    <div class="border rounded p-2 mb-2" style="background: var(--bs-tertiary-bg)">
        <p class="fw-semibold text-secondary mb-2"
           style="font-size: var(--cd-text-subsection)">
            <i class="fas fa-paper-plane fa-fw"></i> Issue confirmation requests
        </p>
        <form action="{{ url_for('convenor.issue_confirm_requests', id=config.id) }}"
              method="POST" name="issue-form">
            {{ issue_form.hidden_tag() }}
            <div class="d-flex align-items-center gap-2 mb-2">
                <label class="text-secondary mb-0"
                       style="font-size: var(--cd-text-form-label); min-width: 90px">
                    Request deadline
                </label>
                {{ date_field(issue_form.request_deadline, 'issue_datetimepicker') }}
            </div>
            <div class="mb-2" style="font-size: var(--cd-text-form-label); color: var(--bs-secondary-color)">
                {{ issue_form.confirm_template.label.text }}
            </div>
            {{ wtf.render_field(issue_form.confirm_template) }}
            <div class="d-flex justify-content-end gap-2 mt-2">
                {% if issue_form.skip_button is defined %}
                    {{ wtf.render_field(issue_form.skip_button,
                       button_map={'skip_button': 'outline-secondary'}, button_size='sm') }}
                {% endif %}
                {{ wtf.render_field(issue_form.submit_button,
                   button_map={'submit_button': 'outline-primary'}, button_size='sm') }}
            </div>
        </form>
    </div>

{% elif lifecycle == config.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS %}
    {# Inline waiting-confirmations content — replaces waiting_confirmations macro #}
    <div class="border rounded p-2 mb-2" style="background: var(--bs-tertiary-bg)">
        <p class="fw-semibold text-secondary mb-2"
           style="font-size: var(--cd-text-subsection)">
            <i class="fas fa-hourglass-half fa-fw"></i> Awaiting faculty confirmations
        </p>
        <div class="alert alert-warning py-2 px-2 mb-2"
             style="font-size: var(--cd-text-cta-desc)">
            <strong>{{ config.confirm_outstanding_count }} faculty</strong>
            have outstanding confirmation requests.
            <a class="alert-link ms-1"
               href="{{ url_for('convenor.outstanding_confirm', id=config.id) }}">
                View outstanding&hellip;
            </a>
            <a href="{{ url_for('convenor.force_confirm_all', id=config.id) }}"
               class="btn btn-outline-danger btn-xs float-end">
                Force confirm all
            </a>
        </div>
        {{ approvals_state(approval_data) }}
        <form action="{{ url_for('convenor.issue_confirm_requests', id=config.id) }}"
              method="POST" name="issue-form">
            {{ issue_form.hidden_tag() }}
            <div class="d-flex align-items-center gap-2 mb-2">
                <label class="text-secondary mb-0"
                       style="font-size: var(--cd-text-form-label); min-width: 90px">
                    Request deadline
                </label>
                {{ date_field(issue_form.request_deadline, 'confirm_datetimepicker') }}
            </div>
            <div class="d-flex justify-content-end gap-2 mt-2">
                <a href="{{ url_for('convenor.confirmation_reminder', id=config.id) }}"
                   class="btn btn-sm btn-outline-secondary">Send reminders</a>
                {{ wtf.render_field(issue_form.submit_button,
                   button_map={'submit_button': 'outline-secondary'}, button_size='sm') }}
            </div>
        </form>
    </div>

{% elif lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
    {# Inline selections-open content — replaces selection_open macro #}
    {# Status alert #}
    {% set selector_data = config.selector_data %}
    {% set submitted = selector_data['have_submitted'] %}
    {% set missing = selector_data['missing'] %}
    {% set total = selector_data['total'] %}
    <div class="border rounded p-2 mb-2" style="background: var(--bs-tertiary-bg)">
        <p class="fw-semibold text-secondary mb-2"
           style="font-size: var(--cd-text-subsection)">
            <i class="fas fa-check fa-fw text-success"></i> Selections are live
        </p>
        {% if submitted == total %}
            <div class="alert alert-success py-2 px-2 mb-2"
                 style="font-size: var(--cd-text-cta-desc)">
                <strong>All selectors have submitted validated choices.</strong>
                It is safe to close selections.
            </div>
        {% elif missing == 0 %}
            <div class="alert alert-info py-2 px-2 mb-2"
                 style="font-size: var(--cd-text-cta-desc)">
                <strong>Some selectors have not yet made a validated submission.</strong>
                Bookmark data can be used if selections close now.
            </div>
        {% else %}
            <div class="alert alert-warning py-2 px-2 mb-2"
                 style="font-size: var(--cd-text-cta-desc)">
                <strong>Some selectors are missing both a validated submission and bookmark
                data.</strong>
                {% if not config.selection_open_to_all %}
                    Bookmark data (where it exists) can be used for matching.
                {% endif %}
            </div>
        {% endif %}
        {# Supervision hints — only shown when non-empty #}
        {% set hint_list = config.pending_custom_offer_hints %}
        {% if hint_list %}
            <div class="border rounded mb-2" style="overflow:hidden">
                <div class="px-2 py-1 fw-semibold text-secondary"
                     style="background: var(--bs-tertiary-bg);
                            border-bottom: 1px solid var(--bs-border-color);
                            font-size: var(--cd-text-form-label)">
                    <i class="fas fa-lightbulb fa-fw"></i>
                    {{ hint_list|length }} previous supervision hint{{ 's' if hint_list|length != 1 }}
                </div>
                {% for hint in hint_list %}
                    <div class="d-flex justify-content-between align-items-center px-2 py-1
                         {% if not loop.last %}border-bottom{% endif %}"
                         style="font-size: var(--cd-text-cta-desc)">
                        <span class="text-body-secondary text-truncate me-2">
                            {{ hint.selector.student.user.name }} &middot;
                            {{ hint.faculty.user.name if hint.faculty }}
                        </span>
                        <div class="d-flex gap-1 flex-shrink-0">
                            <a href="{{ url_for('convenor.accept_custom_offer_hint',
                                               hint_id=hint.id) }}"
                               class="btn btn-outline-success btn-xs">Accept</a>
                            <a href="{{ url_for('convenor.reject_custom_offer_hint',
                                               hint_id=hint.id) }}"
                               class="btn btn-outline-danger btn-xs">Reject</a>
                        </div>
                    </div>
                {% endfor %}
            </div>
        {% endif %}
        {# Change-deadline form. The old `close` button is removed — Close selections
           remains in the right-column buttons below. #}
        <form action="{{ url_for('convenor.adjust_selection_deadline',
                                 configid=config.id) }}"
              method="POST" name="adjust_selection_deadline">
            {{ change_form.hidden_tag() }}
            <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
                <label class="text-secondary mb-0"
                       style="font-size: var(--cd-text-form-label); min-width: 60px">
                    Deadline
                </label>
                {{ date_field(change_form.live_deadline, 'live_datetimepicker') }}
                {{ wtf.render_field(change_form.notify_convenor) }}
            </div>
            <div class="d-flex justify-content-end gap-2 mt-2">
                {{ wtf.render_field(change_form.change,
                   button_map={'change': 'outline-secondary'}, button_size='sm') }}
            </div>
        </form>
        {# Close selections — separate POST form, kept prominent #}
        {% if lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
            <div class="mt-2">
                <form action="{{ url_for('convenor.perform_close_selections',
                                         configid=config.id) }}"
                      method="POST" class="d-inline">
                    {{ change_form.hidden_tag() }}
                    <button type="submit" class="btn btn-sm btn-outline-danger w-100">
                        <i class="fas fa-lock fa-fw"></i> Close selections
                    </button>
                </form>
            </div>
        {% endif %}
    </div>

{% elif lifecycle == config.SELECTOR_LIFECYCLE_READY_MATCHING
     or lifecycle == config.SELECTOR_LIFECYCLE_READY_ROLLOVER %}
    {# Selection-closed status — replaces selection_closed macro #}
    {% set selector_data = config.selector_data %}
    {% set submitted = selector_data['have_submitted'] %}
    {% set missing = selector_data['missing'] %}
    {% set total = selector_data['total'] %}
    <div class="border rounded p-2 mb-2" style="background: var(--bs-tertiary-bg)">
        <p class="fw-semibold text-secondary mb-2"
           style="font-size: var(--cd-text-subsection)">
            <i class="fas fa-lock fa-fw"></i> Selections closed
        </p>
        {% if submitted == total %}
            <div class="alert alert-success py-2 px-2 mb-0"
                 style="font-size: var(--cd-text-cta-desc)">
                <strong>All students submitted validated choices before selection closed.</strong>
            </div>
        {% elif missing == 0 %}
            <div class="alert alert-success py-2 px-2 mb-0"
                 style="font-size: var(--cd-text-cta-desc)">
                <strong>Some students did not submit validated choices, but all students
                have bookmark data.</strong>
            </div>
        {% else %}
            <div class="alert alert-warning py-2 px-2 mb-0"
                 style="font-size: var(--cd-text-cta-desc)">
                <strong>Some selectors are missing both a validated submission and bookmark
                data.</strong>
                {% if not config.selection_open_to_all %}
                    <ul class="mb-0 mt-1">
                        <li>Bookmark data (where it exists) can be used for automated matching.</li>
                        <li>Selectors with missing data may receive a random project allocation.</li>
                    </ul>
                {% endif %}
            </div>
        {% endif %}
    </div>
{% endif %}
```

After the state-conditional block, the "Reset popularity" button and (if `SELECTIONS_OPEN`) the
close-selections form remain — but note the close-selections form is now **inside** the
`SELECTIONS_OPEN` block above. Remove the duplicate from its current position in the card.

### Go-live full-width card (READY_GOLIVE only)

Insert this between `{{ action_panel(action_items) }}` and the `{# [G] TWO-COLUMN LAYOUT #}` div:

```jinja2
{% if lifecycle == config.SELECTOR_LIFECYCLE_READY_GOLIVE and pclass.publish
      and approval_data is defined %}
    <div class="card border-secondary mt-2 mb-3">
        <div class="card-header d-flex justify-content-between align-items-center py-2">
            <span class="fw-semibold" style="font-size: var(--cd-text-secondary)">
                <i class="fas fa-rocket fa-fw text-primary"></i>
                Go live &mdash; set deadline and launch selections
            </span>
            <div class="d-flex gap-2">
                {% if golive_form.live_and_close is defined %}
                    {{ wtf.render_field(golive_form.live_and_close,
                       button_map={'live_and_close': 'outline-secondary'}, button_size='sm') }}
                {% endif %}
                {{ wtf.render_field(golive_form.live,
                   button_map={'live': 'outline-primary'}, button_size='sm') }}
            </div>
        </div>
        <div class="card-body p-3">
            <div class="row g-3">
                <div class="col-md-6">
                    <form action="{{ url_for('convenor.go_live', id=config.id) }}"
                          method="POST" name="golive-form">
                        {{ golive_form.hidden_tag() }}
                        {{ date_field(golive_form.live_deadline, 'golive_datetimepicker') }}
                        {{ wtf.render_field(golive_form.accommodate_matching) }}
                        {{ wtf.render_field(golive_form.full_CATS) }}
                        {{ wtf.render_field(golive_form.notify_faculty) }}
                        {{ wtf.render_field(golive_form.notify_selectors) }}
                        {{ approvals_state(approval_data) }}
                        {{ blocking_task_list(config.get_blocking_tasks[0]) }}
                    </form>
                </div>
                <div class="col-md-6">
                    <p class="fw-semibold text-secondary mb-1"
                       style="font-size: var(--cd-text-form-label)">
                        Faculty notification email
                    </p>
                    {{ wtf.render_field(golive_form.faculty_template) }}
                    <p class="fw-semibold text-secondary mb-1 mt-2"
                       style="font-size: var(--cd-text-form-label)">
                        Selector notification email
                    </p>
                    {{ wtf.render_field(golive_form.selector_template) }}
                    <p class="fw-semibold text-secondary mb-1 mt-2"
                       style="font-size: var(--cd-text-form-label)">
                        Convenor summary email
                    </p>
                    {{ wtf.render_field(golive_form.convenor_template) }}
                </div>
            </div>
        </div>
    </div>
{% endif %}
```

Also suppress the right-column lifecycle card when `READY_GOLIVE`:

```jinja2
{% if pclass.publish and lifecycle != config.SELECTOR_LIFECYCLE_READY_GOLIVE %}
    {# ... existing lifecycle card ... #}
{% endif %}
```

---

## Step 6 — Match proposal and assessment schedule cards → action panel

The two full-width cards at lines ~709–774 of `status.html` (proposed matches and proposed
schedules) must be **removed** from the template body. Their content is now generated by the
Python view and surfaced through `action_items` in the action panel.

In `app/convenor/dashboard.py`, in the `status` view function, find where `action_items` is
built (or add the following if not already present):

```python
# Proposed match available
if pclass.publish and config.has_published_matches and not rollover_in_progress:
    match_url = url_for('convenor.audit_matches', pclass_id=config.pclass_id)
    if config.select_in_previous_cycle:
        desc = ("An administrator has published a selector/project match. "
                "Selections take place in the prior cycle — once accepted, "
                "no further convenor action is required.")
    else:
        desc = ("An administrator has published a selector/project match. "
                "Selections are in the same cycle as submissions — once accepted, "
                "submitter records can be generated immediately.")
    action_items.append(ConvenorAction(
        severity="blocking",
        icon="sitemap",
        title="A proposed selector/project match is available for review",
        description=desc,
        buttons=[ConvenorActionButton(
            label="View proposed match",
            url=match_url,
            icon="arrow-right",
            outline=False,
        )],
    ))

# Proposed assessment schedule available
if pclass.publish and config.has_auditable_schedules:
    sched_url = url_for('convenor.audit_schedules', pclass_id=config.pclass_id)
    action_items.append(ConvenorAction(
        severity="blocking",
        icon="calendar-alt",
        title="Proposed assessment schedules are available for review",
        description="An administrator has published one or more proposed presentation assessment schedules.",
        buttons=[ConvenorActionButton(
            label="View proposed schedules",
            url=sched_url,
            icon="arrow-right",
            outline=False,
        )],
    ))
```

Confirm the exact field names on `ConvenorAction` and `ConvenorActionButton` from the existing
codebase during reconnaissance — do not guess.

---

## Step 7 — Rollover cards

The `rollover_not_yet_card` and `rollover_card` macros (called at lines ~703–707) are redesigned
as follows.

**`rollover_not_yet_card`** — convert to a `warning`-severity action panel item. Add to
`action_items` in the Python view, or (if the rollover condition is only cheaply testable in
Jinja2) replace the macro call with inline action-panel-style markup within `status.html` that
matches the action panel row structure exactly.

**`rollover_card`** — keep as a full-width card below the two-column layout, but replace
the `bg-danger` card header with a warning-accent design:

```html

<div class="card mt-3 mb-3" style="border: 2px solid var(--bs-warning-border-subtle)">
    <div class="card-header d-flex align-items-center gap-2 py-2"
         style="background: var(--bs-warning-bg-subtle);
                border-bottom: 1px solid var(--bs-warning-border-subtle)">
        <i class="fas fa-sync-alt fa-fw" style="color: var(--bs-warning-text-emphasis)"></i>
        <strong style="color: var(--bs-warning-text-emphasis)">
            Rollover of academic year to {{ current_year }}&ndash;{{ current_year+1 }}
            is available
        </strong>
    </div>
    <div class="card-body">
        {# ... retain existing body content unchanged ... #}
    </div>
</div>
```

The rollover action buttons ("Rollover", "Drop markers", "Rollover and assign markers") remain
`btn btn-outline-warning` and `btn btn-warning` — do not change these to `btn-xs`.

---

## Step 8 — Tasks summary widget

Replace the existing full-width tasks table (lines ~778–906 of `status.html`) with a compact
summary widget. The widget shows only the top tasks (the existing `top_to_dos` list) with a
"View all" link to the Tasks pill:

```html
{% if top_to_dos is defined and top_to_dos is not none and top_to_dos|length > 0 %}
<div class="card border-secondary mt-2 mb-3">
    <div class="card-header d-flex justify-content-between align-items-center py-2">
            <span class="fw-semibold text-secondary" style="font-size: var(--cd-text-subsection)">
                <i class="fas fa-tasks fa-fw"></i> Upcoming tasks
            </span>
        <a href="{{ url_for('convenor.todo_list', id=pclass.id) }}"
           class="btn btn-outline-secondary btn-xs">
            View all in Tasks tab <i class="fas fa-arrow-right ms-1"></i>
        </a>
    </div>
    {% for tk in top_to_dos %}
    {% set tk_type = tk.__mapper_args__['polymorphic_identity'] %}
    {% set obj = tk.parent %}
    {% set row_bg = '' %}
    {% if tk.is_overdue %}{% set row_bg = 'style="background: var(--bs-danger-bg-subtle)"' %}
    {% elif tk.complete %}{% set row_bg = 'style="background: var(--bs-success-bg-subtle)"' %}
    {% endif %}
    <div class="d-flex align-items-center gap-2 px-3 py-2 border-bottom"
         {{ row_bg|safe }}
         style="font-size: var(--cd-text-cta-desc)">
        {% if tk.is_overdue %}
        <i class="fas fa-exclamation-triangle text-danger flex-shrink-0"></i>
        {% elif tk.complete %}
        <i class="fas fa-check text-success flex-shrink-0"></i>
        {% else %}
        <i class="fas fa-circle text-body-secondary flex-shrink-0"
           style="font-size: 0.5em"></i>
        {% endif %}
        <span class="flex-grow-1 fw-medium">
                    {% if tk_type == 1 or tk_type == 2 %}
                        <a class="text-decoration-none"
                           href="{{ url_for('convenor.edit_student_task', tid=tk.id,
                                           url=url_for('convenor.status', id=pclass.id)) }}">
                            {{ tk.description|truncate(60) }}
                        </a>
                    {% elif tk_type == 3 %}
                        <a class="text-decoration-none"
                           href="{{ url_for('convenor.edit_generic_task', tid=tk.id,
                                           url=url_for('convenor.status', id=pclass.id)) }}">
                            {{ tk.description|truncate(60) }}
                        </a>
                    {% else %}
                        {{ tk.description|truncate(60) }}
                    {% endif %}
                </span>
        {% if tk.due_date %}
        <span class="text-body-secondary flex-shrink-0">
                        Due: {{ tk.due_date.strftime("%d %b %Y") }}
                    </span>
        {% endif %}
        {% if tk.is_overdue %}
        <span class="badge bg-danger-subtle text-danger-emphasis"
              style="font-size: var(--cd-text-micro)">Overdue</span>
        {% elif tk.complete %}
        <span class="badge bg-success-subtle text-success-emphasis"
              style="font-size: var(--cd-text-micro)">Complete</span>
        {% elif tk.is_available %}
        <span class="badge bg-info-subtle text-info-emphasis"
              style="font-size: var(--cd-text-micro)">Available</span>
        {% endif %}
    </div>
    {% endfor %}
</div>
{% endif %}
```

---

## Step 9 — Remove deprecated [B] block and imports

Once Steps 5–6 are complete and verified:

1. Delete the entire `{# [B] LIFECYCLE ACTION CARD #}` block from `status.html`
2. Remove the macro imports at the top of `status.html` for:
    - `issue_confirmations`
    - `waiting_confirmations`
    - `golive`
    - `selection_open`
    - `selection_closed`
3. Keep the imports for `rollover_card` and `rollover_not_yet_card` (still used in Step 7)
4. The five removed macro files (`issue_confirmations.html`, `waiting_confirmations.html`,
   `golive.html`, `selection_open.html`, `selection_closed.html`) are now unused. Add a
   comment to each: `{# DEPRECATED: content absorbed into status.html lifecycle card. #}`
   Do not delete them in this prompt — leave deletion for a follow-up cleanup pass.

---

## Verification steps

After each step, run the following before moving to the next:

```bash
# After Step 2 — token definitions present
grep -n '\-\-cd-text-' app/static/css/common.css | wc -l
# Expect: 11 or more

# After Step 4 — no remaining 'Full detail' buttons
grep -rn 'Full detail' app/templates/convenor/dashboard/
# Expect: no output

# After Step 4 — no remaining 'period_marking_events_inspector' in status.html
grep -n 'period_marking_events_inspector' app/templates/convenor/dashboard/status.html
# Expect: no output (moved to 'View all events' link in section header)

# After Step 5 — selection_open macro no longer called in status.html
grep -n 'selection_open\|issue_confirmations\|waiting_confirmations\|golive(' \
    app/templates/convenor/dashboard/status.html
# Expect: no output (only in {# DEPRECATED #} comments if any)

# After Step 6 — match/schedule card divs removed
grep -n 'has_published_matches\|has_auditable_schedules' \
    app/templates/convenor/dashboard/status.html
# Expect: no output

# After Step 9 — no raw font-size px or rem values in status.html
grep -n 'font-size:.*px\|font-size:.*rem' \
    app/templates/convenor/dashboard/status.html
# Expect: no output (all sizing via --cd-text-* tokens or Bootstrap classes)

# Line count sanity check
wc -l app/templates/convenor/dashboard/status.html
# Expect: substantially less than original (~912 lines)
```

---

## Constraints

- **No hardcoded font-size values** anywhere in the templates. Use `var(--cd-text-*)` tokens
  or Bootstrap utility classes (`.small`, `.fw-semibold`, etc.) exclusively.
- **No hardcoded hex or rgb colour values.** Use `var(--bs-*)` tokens only.
- **No inline `style="background: ..."`** for colours — use `var(--bs-*-bg-subtle)` tokens.
  The only permitted inline styles are `font-size: var(--cd-text-*)` and structural values
  (padding, gap, min-width) where no Bootstrap utility class covers the exact need.
- `btn-xs` for secondary/tertiary dashboard actions; `btn-sm` for primary lifecycle actions
  (issue, close, rollover buttons).
- The `approvals_state` macro is still used in Steps 5 (WAITING_CONFIRMATIONS) and 5 (READY_GOLIVE).
  Its import must be retained.
- The `blocking_task_list` macro is still used in the go-live card (Step 5). Its import must
  be retained.
- Do not modify any Python model, route URL, or form class. Only `dashboard.py` (action_items
  additions in Step 6) and Jinja2 templates are changed.