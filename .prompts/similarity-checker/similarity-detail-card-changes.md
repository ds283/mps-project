# Implementation prompt — similarity concern detail redesign

## Overview

This prompt asks you to implement three related changes to the MPS-Project platform:

1. Add a `initials` property to the `User` model.
2. Update `CLAUDE.md` to enforce canonical use of that property.
3. Redesign `similarity_concern_detail.html` to surface richer context in the two-column student panels.

Work through the tasks in the order given. Do not begin task 3 until tasks 1 and 2 are complete, because task 3 depends
on the Jinja2 accessor established in task 1.

---

## Task 1 — Add `User.initials` property

### Location

Find the `User` model class. It will be in a file named `users.py` somewhere under the application package (likely
`app/models/users.py` or similar). Do not create a new file; edit the existing one.

### What to add

Add the following read-only property to the `User` class:

```python
@property
def initials(self) -> str:
    """
    Return up to two uppercase initials derived from the user's name.

    Algorithm
    ---------
    Split on whitespace and filter empty tokens.  Take the first character of
    the first token and the first character of the last token (when they differ),
    then upper-case both.  If only one token is present, return its first
    character upper-cased.  If the name is empty or None, return '?'.

    Examples
    --------
    'David Seery'        -> 'DS'
    'Anne-Marie Collins' -> 'AC'
    'Madonna'            -> 'M'
    ''                   -> '?'
    None                 -> '?'
    """
    name: str = self.name or ''
    tokens = [t for t in name.split() if t]
    if not tokens:
        return '?'
    first = tokens[0][0].upper()
    if len(tokens) == 1:
        return first
    last = tokens[-1][0].upper()
    return first + last
```

Place the property near other name-related properties on the class (search for `def name` or `first_name`/`last_name`
columns to find the right neighbourhood).

### Tests

After adding the property, verify your implementation by running the existing test suite:

```
pytest tests/ -x -q
```

If there is no dedicated test file for `User`, add one at `tests/models/test_user_initials.py` with the following
parametrised cases:

```python
import pytest
from app.models.users import User  # adjust import path if needed


@pytest.mark.parametrize("name,expected", [
    ("David Seery", "DS"),
    ("Anne-Marie Collins", "AC"),
    ("Madonna", "M"),
    ("J K Rowling", "JR"),
    ("", "?"),
])
def test_initials(name, expected):
    u = User.__new__(User)  # bypass __init__, we only need the property
    object.__setattr__(u, '_name_override', name)
    # patch: temporarily give the instance a .name property
    type(u).name = property(lambda self: name)
    assert u.initials == expected
```

Adjust the import path and patching strategy to match the actual project layout. The important thing is that all five
cases pass.

---

## Task 2 — Update CLAUDE.md

`CLAUDE.md` lives at the repository root. If the file does not yet exist, create it. If it already exists, append the
new section without altering any existing content.

Add the following section verbatim (you may add it under a top-level `## UI conventions` heading if one already exists,
or create that heading if it does not):

```markdown
## UI conventions

### Staff initials avatars

Whenever a staff member's initials are displayed in a UI component (avatar
circles, monogram badges, etc.), always derive them from `user.initials` —
the canonical `@property` defined on the `User` model in `app/models/users.py`
(or the equivalent path in this project).

**Never** compute initials ad hoc in a template, view function, or JavaScript
snippet (e.g. splitting on spaces or taking `name[0]`). All initials
derivation logic lives in one place so that edge cases (single names,
hyphenated names, empty values) are handled consistently across every view.

In Jinja2 templates the accessor is simply:

```jinja
{{ role.user.initials }}
```

In Python (view functions, task code, etc.):

```python
initials = user.initials
```

```

---

## Task 3 — Redesign `similarity_concern_detail.html`

### File to edit

`app/templates/similarity_concern_detail.html` (or wherever the file lives in
the project's template directory — locate it with `find . -name
"similarity_concern_detail.html"`).

### Design reference

The redesign uses a **CSS subgrid** layout so that the nine section rows inside
each student panel align horizontally across both columns. The nine rows, in
order, are:

1. Panel header (student name, candidate number, class, year)
2. Project (name, owner, "not supervisor" badge if applicable)
3. Convenor banner
4. Staff list
5. Workflow links (SubmitterRecord, ConflationRecord)
6. Report download
7. Turnitin scores (separator from row above)
8. Risk factors
9. Section text extract

The outer two-column grid must declare `grid-template-rows: repeat(9, auto)`.
Each `.panel` element must set `grid-row: 1 / -1` and
`grid-template-rows: subgrid` so both panels share the parent's row tracks.

### Detailed requirements for each row

#### Row 1 — Panel header

Identical to the existing header, but add a 3px left border accent:
- Student A: `border-left: 3px solid var(--db-orange-600)`
- Student B: `border-left: 3px solid var(--bs-info)` (or the equivalent blue
  in the project's colour scheme)

#### Row 2 — Project

Render:
- `record.project.name` as the project title (bold, 12 px)
- Below that: `record.project.owner.user.name` prefixed with "Owner:" if the
  owner is not already in the supervision team. Determine this by checking
  whether `record.project.owner_id` is in `record.supervisor_role_ids`. If
  the owner is absent from the supervision team, append a muted "not
  supervisor" badge.

Template sketch:
```jinja
{% set project = record.project %}
{% if project %}
  <div class="fw-semibold" style="font-size:0.85em;">{{ project.name }}</div>
  {% if project.owner %}
    <div class="text-body-secondary" style="font-size:0.78em;">
      Owner: {{ project.owner.user.name }}
      {% if project.owner_id not in record.supervisor_role_ids %}
        <span class="badge bg-secondary-subtle text-secondary-emphasis ms-1"
              style="font-size:0.7em;">not supervisor</span>
      {% endif %}
    </div>
  {% endif %}
{% endif %}
```

#### Row 3 — Convenor banner

Display the historical convenor from `record.period.config.convenor.user.name`
(the `ProjectClassConfig` instance for that submission year, **not**
`record.period.config.project_class.convenor`). Style as a small teal/success
banner.

```jinja
{% set convenor = record.period.config.convenor %}
{% if convenor %}
  <div class="d-flex align-items-center gap-2 p-2 rounded"
       style="background:var(--bs-success-bg-subtle);
              border:0.5px solid var(--bs-success-border-subtle);
              font-size:0.78em; color:var(--bs-success-text-emphasis);">
    <i class="fas fa-user-check fa-sm"></i>
    Convenor ({{ record.period.config.year }}/{{ record.period.config.year + 1 }}):
    <strong>{{ convenor.user.name }}</strong>
  </div>
{% endif %}
```

#### Row 4 — Staff list

Iterate over `record.roles`, filtering to supervisor, marker, and moderator
role types (exclude presentation assessors, exam board, external examiners).
For each role render:

- An initials avatar circle (32 px, circular, coloured by role type)
- `role.user.name`
- A role-type badge
- A "Marking record" link (see row 5 for URL construction)

**Use `role.user.initials` for the avatar text.** Do not compute initials
inline.

Role type colours for the avatar background (use Bootstrap subtle variants so
they adapt to dark mode):

- Supervisor / responsible supervisor: `--bs-warning-bg-subtle` / `--bs-warning-text-emphasis`
- Marker: `--bs-info-bg-subtle` / `--bs-info-text-emphasis`
- Moderator: `--bs-secondary-bg-subtle` / `--bs-secondary-text-emphasis`

Role badge labels (draw these from `role.role_as_str`):

- `ROLE_RESPONSIBLE_SUPERVISOR` → badge class `bg-warning-subtle text-warning-emphasis`
- `ROLE_SUPERVISOR` → same
- `ROLE_MARKER` → `bg-info-subtle text-info-emphasis`
- `ROLE_MODERATOR` → `bg-secondary-subtle text-secondary-emphasis`

Template sketch:

```jinja
{% for role in record.roles %}
  {% if role.role in [
      SubmissionRole.ROLE_SUPERVISOR,
      SubmissionRole.ROLE_RESPONSIBLE_SUPERVISOR,
      SubmissionRole.ROLE_MARKER,
      SubmissionRole.ROLE_MODERATOR
  ] %}
    <div class="d-flex align-items-center gap-2 px-2 py-1 rounded mb-1"
         style="background:var(--bs-body-bg); font-size:0.82em;">
      {# avatar #}
      <div style="width:28px; height:28px; border-radius:50%;
                  background:var(--bs-{{ role_avatar_bg[role.role] }}-bg-subtle);
                  color:var(--bs-{{ role_avatar_bg[role.role] }}-text-emphasis);
                  display:flex; align-items:center; justify-content:center;
                  font-size:0.7em; font-weight:500; flex-shrink:0;">
        {{ role.user.initials }}
      </div>
      <span style="flex:1;">{{ role.user.name }}</span>
      <span class="badge bg-{{ role_badge[role.role] }}-subtle
                   text-{{ role_badge[role.role] }}-emphasis"
            style="font-size:0.7em;">{{ role.role_as_str }}</span>
      {# marking record link — see row 5 #}
    </div>
  {% endif %}
{% endfor %}
```

Pass a `role_avatar_bg` and `role_badge` mapping from the view function, or
define it as a Jinja2 variable at the top of the template block.

#### Row 5 — Workflow links

For each `record`, surface links to:

1. The `SubmitterReport` instances associated with `MarkingWorkflow` instances
   that contain this `SubmissionRecord`. Query via the back-references already
   present on the model — for example:

   ```python
   # In the view function, pass these to the template:
   submitter_reports_a = (
       SubmitterReport.query
       .join(MarkingWorkflow, SubmitterReport.workflow_id == MarkingWorkflow.id)
       .filter(MarkingWorkflow.submission_records.any(id=record_a.id))
       .all()
   )
   ```

   Render each as a pill link:
   ```jinja
   {% for sr in submitter_reports %}
     <a href="{{ url_for('some_blueprint.submitter_report_view', sr_id=sr.id,
                         url=..., text=...) }}"
        class="badge bg-info-subtle text-info-emphasis text-decoration-none me-1">
       <i class="fas fa-list fa-xs me-1"></i>SubmitterReport #{{ sr.id }}
       <i class="fas fa-external-link-alt fa-xs ms-1"></i>
     </a>
   {% endfor %}
   ```

2. The `ConflationRecord` instances for this submission. Use whatever
   back-reference or query already exists in the codebase — search for
   `ConflationRecord` to find the relevant model and URL endpoint.

Also render a "Marking record" link per staff member (from row 4) pointing to
their individual `MarkingRecord` for the relevant workflow. Use `url=` and `text=`
query parameters set to an appropriate values on all links so the destination page can
offer a "Back to concern" button. Your implementation should match existing exmaples
in the codebase. Style your return buttons similarly to those already visible on the
Similarity dashboard and its dependent templates.

#### Row 6 — Report download

Prefer `record.processed_report` over `record.report`. If neither exists,
omit this row's content (leave the grid cell empty so alignment is preserved).

For thumbnail display:

- If `record.processed_report.medium_thumbnail` is not None, render it as an
  `<img>` (max 36×46 px).
- Else if `record.processed_report.small_thumbnail` is not None, render that.
- Else render a PDF file icon (`<i class="fas fa-file-pdf text-danger">`).

Apply the same fallback chain to `record.report` when `processed_report` is
None.

Display filename (`asset.target_name`), word count from
`record.language_analysis_data.get('metrics', {}).get('word_count')` if
available, upload timestamp, and a download link to the existing asset
download endpoint.

#### Row 7 — Turnitin (with separator)

Identical to the existing Turnitin row but separated from row 6 by a top
border (`border-top: 1px solid var(--bs-border-color-translucent)`).

#### Row 8 — Risk factors

Iterate over `record.get_present_risk_factors()`. For each factor:

- Show the human-readable label from `SubmissionRecord.RISK_FACTOR_LABELS`
- Show a resolved/unresolved badge
- For `RISK_AI_USE` and `RISK_AI_COMPLIANCE`, also show the key metrics
  one-liner:
  ```
  MATTR {mattr:.2f} · MTLD {mtld:.1f} · sentence CV {cv:.2f} · B = {b:.2f}
  ```
  sourced from `record.language_analysis_data['metrics']`, and the LLM
  verdict string from `record.language_analysis_data.get('llm_result',
  {}).get('summary', '')`. Style the verdict box amber/flagged when the
  summary indicates concern, green/ok otherwise — the simplest heuristic is
  to check whether `risk_factors_data[RISK_AI_USE].get('resolved')` is True.

#### Row 9 — Section text extract

Identical to the existing section text block (`concern_chunks.a` /
`concern_chunks.b`).

### CSS — subgrid

Add the following CSS to the template's `<style>` block (or the relevant
project-level CSS file if one is used). Do not use inline styles for the grid
structure.

```css
/* Similarity concern detail — two-column subgrid */
.similarity-col2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: repeat(9, auto);
    gap: 0 0.625rem; /* 10px column gap */
    margin-bottom: 1rem;
    align-items: stretch;
}

.similarity-panel {
    display: grid;
    grid-row: 1 / -1;
    grid-template-rows: subgrid;
    border: 0.5px solid var(--bs-border-color);
    border-radius: 0.625rem;
    overflow: hidden;
}

/* Each direct child of .similarity-panel occupies exactly one row track */
.similarity-panel > * {
    padding: 0.5rem 0.75rem;
    min-width: 0; /* prevent grid blowout */
}

.similarity-panel-header {
    padding: 0.5rem 0.75rem;
    background: var(--bs-tertiary-bg);
    border-bottom: 1px solid var(--bs-border-color-translucent);
}

.similarity-panel-divider {
    padding: 0.5rem 0.75rem 0.375rem;
    border-top: 1px solid var(--bs-border-color-translucent);
}
```

Replace the existing `<div class="row g-3 mb-4">` two-column wrapper and its
inner card divs with elements using these new classes. Ensure each panel has
exactly nine direct children — one per row — in the order listed above. Empty
rows (e.g. when no risk factors exist) must still be present as empty `<div>`
elements so the row count stays at nine and alignment is preserved.

### View function changes

The view function that renders `similarity_concern_detail.html` will need to
pass additional context variables. Locate it (search for
`similarity_concern_detail` in the blueprints/views files) and add:

```python
from .markingevent import ConflationRecord, MarkingWorkflow, SubmitterReport


# ... inside the view function, after record_a / record_b are resolved:
def _submitter_reports(record):
    return (
        SubmitterReport.query
        .join(MarkingWorkflow, SubmitterReport.workflow_id == MarkingWorkflow.id)
        .filter(MarkingWorkflow.submission_records.any(id=record.id))
        .all()
    )


def _conflation_records(record):
    # Adjust query to match actual model relationships
    return (
        ConflationRecord.query
        .filter(ConflationRecord.submission_record_id == record.id)
        .all()
    )


return render_template(
    'similarity_concern_detail.html',
    # ... existing context ...
    submitter_reports_a=_submitter_reports(record_a),
    submitter_reports_b=_submitter_reports(record_b),
    conflation_records_a=_conflation_records(record_a),
    conflation_records_b=_conflation_records(record_b),
)
```

Adapt the query logic to match the actual relationship names found in
`markingevent.py` — do not guess; read the file.

### Acceptance criteria

- [ ] Both student panels align at every section boundary regardless of how
  many staff rows one panel has compared to the other.
- [ ] All staff initials are produced by `role.user.initials` — zero inline
  initials computation in the template.
- [ ] The "Report" heading lines up horizontally across both columns.
- [ ] The "Section text" heading lines up horizontally across both columns.
- [ ] Report thumbnails render when available, fall back to the PDF icon
  gracefully.
- [ ] All workflow links include `url=...` and `text=...` parameters.
- [ ] The page passes `pytest tests/ -x -q` with no new failures.
- [ ] The rendered page is visually consistent with the existing Bootstrap 5.3
  design system used throughout the application (no new CSS frameworks,
  no hardcoded hex colours — use Bootstrap custom properties throughout).