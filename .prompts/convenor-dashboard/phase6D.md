# Prompt D — Trim lifecycle card state content and extract supervision hints card

**Prerequisite: Prompts A, B, and C are complete and verified.**

**Read files only in Step 1. Write no code until Step 2.**

---

## Objective

The `SELECTOR_LIFECYCLE_SELECTIONS_OPEN` and `SELECTOR_LIFECYCLE_READY_MATCHING /
READY_ROLLOVER` branches inside the right-column "Selection lifecycle" card currently
render large informational alert blocks and a supervision hints table that are too wide
and too verbose for a compact 40%-width card.

Three specific fixes:

1. **Strip the large alert blocks** from both lifecycle state branches — replace with
   compact single-line status indicators
2. **Extract the supervision hints table** from inside the lifecycle card and render it
   as a separate card in the right column, guarded by
   `lifecycle == SELECTOR_LIFECYCLE_SELECTIONS_OPEN and hint_list is non-empty`
3. **Consolidate the "Change deadline" form and "Close selections" button** so both
   actions appear together at the bottom of the `SELECTIONS_OPEN` branch

---

## Step 1 — Read before writing

Read `app/templates/convenor/dashboard/status.html` in full, with particular attention
to:

- Lines 728–929: the `SELECTIONS_OPEN` and `READY_MATCHING / READY_ROLLOVER` branches
  inside the right-column lifecycle card, and the action buttons block that follows
- Lines 509–933: the full right column, to understand insertion point for the new
  hints card relative to the existing selection metrics and popular projects cards
- The `dashboard_tile` macro import at line 12 — confirm whether this macro is used
  anywhere else in the file after the hints table is removed; if not, the import can
  be removed

Record:

1. The exact right-column card order currently: lifecycle card, selection metrics card,
   popular projects card — confirm the insertion point for the new hints card
   (it should sit between the lifecycle card and the selection metrics card)

2. The exact content of the hints table (lines 793–855): columns, row data bindings,
   accept/reject button routes — this markup will be moved verbatim into the new card

3. The exact location of the "Close selections" form (lines 920–928) and the "Change
   deadline" form (lines 856–865) — confirm they are currently separated

4. Whether `selector_data = config.selector_data` is assigned at the top of the
   `SELECTIONS_OPEN` branch (line ~730) so it can be reused in the compact status
   line without a duplicate call to `config.selector_data`

---

## Step 2 — Replace `SELECTIONS_OPEN` alert blocks with compact status line

The three `alert` blocks covering `submitted == total`, `missing == 0`, and the
warning case (lines ~735–792) must be replaced with a single compact status line.

Replace the entire `<div class="mb-2">` block containing the three alert conditionals
with:

```jinja
{# Compact selector readiness indicator — reuses selector_data already set above #}
<div class="d-flex align-items-center gap-2 small mb-2 pt-2 border-top">
    {% if submitted == total %}
        <i class="fas fa-check-circle text-success fa-fw"></i>
        <span class="text-success fw-semibold">All {{ total }} selectors have
            submitted.</span>
    {% elif missing == 0 %}
        <i class="fas fa-info-circle text-info fa-fw"></i>
        <span class="text-body-secondary">{{ submitted }}/{{ total }} submitted
            &middot; all have bookmarks</span>
    {% else %}
        <i class="fas fa-exclamation-circle text-warning fa-fw"></i>
        <span class="text-body-secondary">{{ submitted }}/{{ total }} submitted
            &middot; <span class="text-warning fw-semibold">{{ missing }} missing
            bookmarks</span></span>
    {% endif %}
</div>
```

This reuses `submitted`, `missing`, and `total` from the `selector_data` assignment
already present at the top of the `SELECTIONS_OPEN` branch (line ~730–734). Do not
add a duplicate `selector_data = config.selector_data` assignment.

---

## Step 3 — Remove the supervision hints block from the lifecycle card

Remove the entire `{% if hint_list %}` block (lines ~793–855) from inside the
`SELECTIONS_OPEN` branch. Do not replace it with anything here — the hints table
will be rendered as a separate right-column card in Step 5.

After removal, the `SELECTIONS_OPEN` branch should contain in order:

1. The compact status line (from Step 2)
2. The Change deadline form (lines ~856–865, unchanged)

---

## Step 4 — Consolidate "Change deadline" and "Close selections"

Move the "Close selections" form (lines ~920–928) from the action buttons block into
the `SELECTIONS_OPEN` branch, immediately after the Change deadline form submit
button. The two forms must remain as separate `<form>` elements — HTML does not
permit nested forms.

The end of the `SELECTIONS_OPEN` branch should become:

```jinja
<div class="mt-2">
    {# Change deadline form #}
    <form action="{{ url_for('convenor.adjust_selection_deadline', configid=config.id) }}"
          method="POST" name="adjust_selection_deadline">
        {{ change_form.hidden_tag() }}
        {{ date_field(change_form.live_deadline, 'live_datetimepicker') }}
        {{ wtf.render_field(change_form.notify_convenor) }}
        <div class="d-flex flex-row justify-content-end align-items-end gap-2 flex-wrap">
            {{ wtf.render_field(change_form.change,
               button_map={'change': 'outline-secondary'}, button_size='sm') }}
        </div>
    </form>
    {# Close selections — separate form, immediately adjacent #}
    <form action="{{ url_for('convenor.perform_close_selections', configid=config.id) }}"
          method="POST" class="mt-1 d-flex justify-content-end">
        {{ change_form.hidden_tag() }}
        <button type="submit" class="btn btn-sm btn-outline-danger">
            <i class="fas fa-lock fa-fw"></i> Close selections
        </button>
    </form>
</div>
```

Then remove the "Close selections" form from the action buttons block (lines ~920–928).
The action buttons block for `SELECTIONS_OPEN` then only needs "Reset popularity":

```jinja
{# Action buttons #}
<div class="d-flex gap-1 flex-wrap mt-2">
    <a href="{{ url_for('convenor.reset_popularity_data', id=config.id) }}"
       class="btn btn-xs btn-outline-secondary">
        <i class="fas fa-sync fa-fw"></i> Reset popularity
    </a>
    {# Close selections has moved into the SELECTIONS_OPEN branch above #}
</div>
```

---

## Step 5 — Add supervision hints as a separate right-column card

In the right column of `status.html`, after the closing `</div>` of the lifecycle
card (`{% endif %}` at approximately line 933) and before the selection metrics card,
insert the new supervision hints card:

```jinja
{# Supervision hints card — only during selections-open when hints exist #}
{% if pclass.publish and lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN %}
    {% set hint_list = config.pending_custom_offer_hints %}
    {% if hint_list %}
        <div class="card border-secondary mb-2">
            <div class="card-header py-2 d-flex justify-content-between align-items-center">
                <span class="fw-semibold text-secondary small">
                    <i class="fas fa-lightbulb fa-fw"></i> Supervision hints
                </span>
                <span class="badge bg-secondary rounded-pill">{{ hint_list | length }}</span>
            </div>
            <div class="card-body p-0">
                <table class="table table-sm table-hover mb-0">
                    <thead class="table-light">
                    <tr>
                        <th class="small">Student</th>
                        <th class="small">Prev. year</th>
                        <th class="small">Previous project</th>
                        <th class="small">Supervisor</th>
                        <th class="small"></th>
                    </tr>
                    </thead>
                    <tbody class="table-group-divider">
                    {% for hint in hint_list %}
                        {% set record = hint.submission_record %}
                        {% set prev_proj = record.project if record else none %}
                        {% set prev_sub_config = record.owner.config if record and record.owner else none %}
                        <tr>
                            <td class="small">{{ hint.selector.student.user.name }}</td>
                            <td class="small">
                                {% if prev_sub_config %}
                                    <div>{{ prev_sub_config.submit_year_a }}&ndash;{{ prev_sub_config.submit_year_b }}</div>
                                    <div class="text-body-secondary">{{ prev_sub_config.abbreviation }}</div>
                                {% else %}
                                    <span class="text-body-secondary">Unknown</span>
                                {% endif %}
                            </td>
                            <td class="small">
                                {% if prev_proj %}{{ prev_proj.name }}
                                {% else %}<span class="text-body-secondary">Unknown</span>{% endif %}
                            </td>
                            <td class="small">
                                {% if hint.faculty and hint.faculty.user %}
                                    {{ hint.faculty.user.name }}
                                {% else %}<span class="text-body-secondary">Unknown</span>{% endif %}
                            </td>
                            <td>
                                <div class="d-flex flex-row gap-1">
                                    <a href="{{ url_for('convenor.accept_custom_offer_hint', hint_id=hint.id) }}"
                                       class="btn btn-xs btn-outline-success"
                                       title="Create custom offers for all current projects by this supervisor">Accept</a>
                                    <a href="{{ url_for('convenor.reject_custom_offer_hint', hint_id=hint.id) }}"
                                       class="btn btn-xs btn-outline-danger"
                                       title="Delete this hint">Reject</a>
                                </div>
                            </td>
                        </tr>
                    {% endfor %}
                    </tbody>
                </table>
                <div class="px-2 py-1 small text-body-secondary border-top">
                    Hints are based on previous supervision history. Accepting creates
                    custom offers for all current projects by the supervisor.
                </div>
            </div>
        </div>
    {% endif %}
{% endif %}
```

Note the differences from the original `dashboard_tile` version:

- Uses standard `card` / `card-header` / `card-body` pattern matching the rest of the
  right column — no `dashboard_tile` wrapper
- `card-body p-0` with `table-sm table-hover mb-0` for a compact flush table
- Footer text moved into a `px-2 py-1 small border-top` div inside `card-body`
- Column widths removed (browser determines proportions at 40% column width)

---

## Step 6 — Replace `READY_MATCHING / READY_ROLLOVER` alert blocks

Replace the two `alert` blocks in the `READY_MATCHING / READY_ROLLOVER` branch
(lines ~873–910) with a compact status line following the same pattern as Step 2:

```jinja
{% set selector_data = config.selector_data %}
{% set submitted = selector_data['have_submitted'] %}
{% set missing = selector_data['missing'] %}
{% set total = selector_data['total'] %}
<div class="d-flex align-items-center gap-2 small mb-2 pt-2 border-top">
    {% if submitted == total %}
        <i class="fas fa-check-circle text-success fa-fw"></i>
        <span class="text-success fw-semibold">All {{ total }} selectors submitted
            validated choices.</span>
    {% elif missing == 0 %}
        <i class="fas fa-check-circle text-success fa-fw"></i>
        <span class="text-body-secondary">{{ submitted }}/{{ total }} submitted
            &middot; remainder have bookmark data</span>
    {% else %}
        <i class="fas fa-exclamation-circle text-warning fa-fw"></i>
        <span class="text-body-secondary">{{ submitted }}/{{ total }} submitted
            &middot; <span class="text-warning fw-semibold">{{ missing }} have no
            bookmark data</span></span>
    {% endif %}
</div>
```

---

## Step 7 — Clean up `dashboard_tile` import

After the hints table has been moved out of the `dashboard_tile` wrapper and into the
new card pattern, check whether `dashboard_tile` is used anywhere else in `status.html`.

Grep `status.html` for `dashboard_tile`. If the only remaining occurrence is the
import at line 12, remove the import line. If it is used elsewhere, leave the import.

---

## Step 8 — Verification

1. **Alert blocks removed from `SELECTIONS_OPEN` branch**: Read the `SELECTIONS_OPEN`
   branch in the edited file. Confirm it contains no `alert-success`, `alert-info`,
   or `alert-warning` divs. The compact status line (a plain `d-flex` div with an
   icon) should be the only selector readiness indicator.

2. **Alert blocks removed from `READY_MATCHING` branch**: Same check for the
   `READY_MATCHING / READY_ROLLOVER` branch.

3. **Hints table not inside lifecycle card**: Grep `status.html` for
   `accept_custom_offer_hint`. Confirm it appears only outside the lifecycle card
   `<div>` — i.e. after the closing `{% endif %}` of the `{% if pclass.publish %}`
   lifecycle card block.

4. **Hints card lifecycle guard**: Grep `status.html` for `pending_custom_offer_hints`.
   Confirm it appears inside a block guarded by both `pclass.publish` and
   `lifecycle == config.SELECTOR_LIFECYCLE_SELECTIONS_OPEN`.

5. **"Close selections" button location**: Grep `status.html` for
   `perform_close_selections`. Must appear exactly once, inside the `SELECTIONS_OPEN`
   branch, after the Change deadline form. Must not appear in the action buttons block.

6. **`change_form.hidden_tag()` not duplicated within a single form**: Confirm that
   within the `SELECTIONS_OPEN` branch, the two `change_form.hidden_tag()` calls each
   appear inside a separate `<form>` element — not both inside the same form.

7. **`selector_data` not double-assigned in `SELECTIONS_OPEN`**: Grep the
   `SELECTIONS_OPEN` branch for `config.selector_data`. Must appear exactly once.

8. **`dashboard_tile` import cleaned up if unused**: Grep `status.html` for
   `dashboard_tile`. If only the import line remains, confirm the import has been
   removed. If it appears in template body content, leave the import and report
   where it is used.

9. **Right-column card order**: Read the right column (`col-12 col-lg-5`) and confirm
   the card order is: lifecycle card → hints card (conditional) → selection metrics
   card → popular projects card.

10. **`table-striped` replaced**: The original hints table used `table-striped`. The
    new version uses `table-hover`. Grep `status.html` for `table-striped` within the
    hints block — must return zero results (the class has been replaced).

Report results of all ten checks. Fix any failures before finishing.