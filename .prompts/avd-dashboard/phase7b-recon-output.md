# Phase 7b — Recon output

## AVD dashboard capsule-building code (as committed in Phase 7)

From `app/ajax/archive/reports.py`, the `_grade` Jinja2 string template:

```jinja2
{% if grade_data|length > 0 %}
    <div class="mt-1 d-flex justify-content-end">
        <div class="sv2-metric-cap grades">
            <div class="sv2-metric-cap-label">Grades</div>
            <div class="sv2-metric-cap-body">
                {% for g in grade_data %}
                    {% if not loop.first %}<div class="sv2-m-sep"></div>{% endif %}
                    <div class="sv2-m-item">
                        <div class="sv2-m-lbl">{{ g.label }}</div>
                        {% if g.grade is not none %}
                            <div class="sv2-m-val sv2-mv-ok">{{ "%.1f"|format(g.grade) }}%</div>
                        {% else %}
                            <div class="sv2-m-val sv2-mv-dim">&mdash;</div>
                        {% endif %}
                    </div>
                {% endfor %}
            </div>
        </div>
    </div>
{% endif %}
```

`grade_data` comes directly from `record.grade_display_data()` with no
post-processing in the Python formatter:

```python
grade_data = record.grade_display_data()
# ... then passed to render_template(grade_templ, ..., grade_data=grade_data)
```

## submitters_v2.html equivalent logic

From `app/templates/convenor/dashboard/submitters_v2.html` (lines ~797–862):

```jinja2
{% set grade_data = r.grade_display_data() %}
{% set show_grades = grade_data|length > 0 %}

{% if show_grades %}
    {# Filter grade items relevant to this project class #}
    {% set visible_grades = [] %}
    {% for g in grade_data %}
        {% if visible_grades.append(g) %}{% endif %}
    {% endfor %}
    {% if visible_grades|length > 0 %}
        <div class="sv2-metric-cap grades">
            <div class="sv2-metric-cap-label">Grades</div>
            <div class="sv2-metric-cap-body">
                {% for g in visible_grades %}
                    {% if not loop.first %}<div class="sv2-m-sep"></div>{% endif %}
                    <div class="sv2-m-item">
                        <div class="sv2-m-lbl">{{ g.label }}</div>
                        {% if g.grade is not none %}
                            <div class="sv2-m-val sv2-mv-ok">{{ "%.1f"|format(g.grade) }}%</div>
                        {% else %}
                            <div class="sv2-m-val sv2-mv-dim">&mdash;</div>
                        {% endif %}
                    </div>
                {% endfor %}
            </div>
        </div>
    {% endif %}
{% endif %}
```

### What `visible_grades` actually does

The `{% if visible_grades.append(g) %}{% endif %}` pattern is the Jinja2
idiom for calling `list.append()` as a statement — `append()` returns `None`
(falsy), so the `{% if %}` body never executes and nothing is rendered, but
the side-effect (appending `g`) still happens. **`visible_grades` is therefore
an unconditional copy of `grade_data`**; no filtering takes place despite the
"Filter grade items" comment.

## Where the "not applicable" vs "applicable-but-ungraded" distinction lives

**The distinction is encoded entirely in `grade_display_data()` itself
(`app/models/submissions.py`, line 2297).** The Phase 7 commit updated this
method from unconditionally returning all three grade types to gating each one
on the corresponding period availability flag:

```python
if period is None or period.supervision_grade_available:
    grade_specs.append(("Supervision", self.supervision_grade, ...))
if period is None or period.report_grade_available:
    grade_specs.append(("Report", self.report_grade, ...))
if period is None or period.presentation_grade_available:
    grade_specs.append(("Presentation", self.presentation_grade, ...))
```

Where the availability flags are:
- `period.supervision_grade_available` → `bool(uses_supervision_grade)` column
- `period.report_grade_available` → `number_markers is not None and > 0`
- `period.presentation_grade_available` → `bool(has_presentation)` column

**Items absent from the returned list are not applicable to this period. Items
present with `grade: None` are applicable but not yet graded.** The two cases
are fully distinguished at the model layer; neither template needs to consult
period/pclass configuration separately.

## Conclusion: the bug was already fixed in Phase 7

Both the AVD dashboard's `_grade` template and `submitters_v2.html` have
identical rendering logic for the two cases:
- `grade: None` → `<div class="sv2-m-val sv2-mv-dim">&mdash;</div>` (dim dash)
- `grade: float` → `<div class="sv2-m-val sv2-mv-ok">xx.x%</div>`

And because `grade_display_data()` now omits non-applicable grade types
(updated in Phase 7), neither template ever sees a Presentation entry for a
period with `has_presentation = False`.

**Step 1 (fix) requires no code changes.** The Phase 7 implementation
correctly handles all four cases:

| Period config | Grade set? | Expected | Actual |
|---|---|---|---|
| has_presentation=False | n/a | No Presentation item | ✓ (not in grade_data) |
| has_presentation=True | No | "Presentation —" (dim) | ✓ (grade: None → dim dash) |
| has_presentation=True | Yes | "Presentation xx.x%" | ✓ (grade: float → mv-ok) |
| report_grade_available=True | No | "Report —" (dim) | ✓ |

The pre-Phase-7 bug was in the OLD `grade_display_data()`, which always
included all three grade types regardless of applicability — meaning periods
without presentation would show "Presentation —" when they shouldn't. Phase 7
fixed this in the model method, making the template filtering in
`submitters_v2.html` (which was doing nothing anyway) irrelevant.

## Step 2 — Verification checklist

- **Dimitri Verai case (no presentation period):** `period.has_presentation = False`
  → `presentation_grade_available` returns `False` → `grade_display_data()` excludes
  Presentation from the list → AVD capsule shows no Presentation item. ✓ No regression.

- **Period with presentation, not yet graded:** `period.has_presentation = True`,
  `self.presentation_grade = None` → `grade_display_data()` includes
  `{"label": "Presentation", "grade": None, ...}` → `_grade` template's
  `{% else %}` branch renders `sv2-mv-dim &mdash;`. Matches `submitters_v2.html`. ✓

- **Supervision and Report equivalents:**
  - Supervision follows the same logic via `uses_supervision_grade` column.
  - Report follows via `number_markers > 0`. For the AVD dashboard's population
    (records with reports submitted), `report_grade_available` is almost certainly
    True for all records; "Report —" would show if the report grade hasn't been
    assigned yet. Both cases are handled correctly by the same template logic.
