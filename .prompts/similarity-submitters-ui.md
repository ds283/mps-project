I need to add a compact similarity-concern strip to the submitters inspector in the MPS-Projects Flask application. The
goal is to let a convenor review an open similarity concern directly from the submitters list without a detour through
the global Similarity Dashboard.

### Background

`app/templates/ajax/convenor/submitters_macros.html` contains a `project_tag` macro that renders each submission record
row. It already shows risk-factor badges (including `similarity_flagged`) and a "Resolve N risk factors…" CTA. The
`SimilarityConcern` model is in `app/models/similarity.py`. The concern-detail page is at the
`dashboards.similarity_concern_detail` endpoint (takes `concern_id`).

### Change 1 — add a threshold constant to the shared LLM thresholds module

In `app/shared/llm_thresholds.py`, add the following two constants alongside the existing ones:

```python
# Similarity concern cosine thresholds
SIMILARITY_INLINE_MIN_COSINE = 0.78  # minimum score to show inline in submitters list
SIMILARITY_DANGER_COSINE = 0.88  # threshold for danger (red) badge
```

### Change 2 — add two properties to `SubmissionRecord`

In `app/models/submissions.py`:

1. Import the new constants at the top of the file alongside the existing `llm_thresholds` imports:

```python
from ..shared.llm_thresholds import (

...
existing
imports...,
SIMILARITY_INLINE_MIN_COSINE,
SIMILARITY_DANGER_COSINE,
)
```

2. Add the following two properties to the `SubmissionRecord` class, near the other relationship-derived properties (
   e.g. alongside `has_issues`, `errors`, `warnings`).

Use the existing `lazy="dynamic"` backrefs that `SimilarityConcern` registers on `SubmissionRecord`:

- `similarity_concerns_as_a` (concerns where this record is `record_a`)
- `similarity_concerns_as_b` (concerns where this record is `record_b`)

No import of `SimilarityConcern` is needed — the backrefs are already registered by SQLAlchemy.

```python
@property
def open_similarity_concerns(self):
    """All unreviewed SimilarityConcerns involving this record, highest cosine first."""
    concerns = (
            list(self.similarity_concerns_as_a.filter_by(reviewed=False).all()) +
            list(self.similarity_concerns_as_b.filter_by(reviewed=False).all())
    )
    concerns.sort(
        key=lambda c: c.transformer_cosine if c.transformer_cosine is not None else -1.0,
        reverse=True,
    )
    return concerns


@property
def inline_similarity_concerns(self):
    """Unreviewed concerns at or above SIMILARITY_INLINE_MIN_COSINE, for inline display."""
    return [
        c for c in self.open_similarity_concerns
        if c.transformer_cosine is not None and c.transformer_cosine >= SIMILARITY_INLINE_MIN_COSINE
    ]
```

### Change 3 — expose `SIMILARITY_DANGER_COSINE` to templates

The template needs to compare cosine scores against `SIMILARITY_DANGER_COSINE` without hardcoding the value. Locate the
Jinja2 environment setup (typically in `app/__init__.py` or a `template_filters.py` / `context_processors.py` module)
where other constants are injected into the template context. Add `SIMILARITY_DANGER_COSINE` there:

```python
from .shared.llm_thresholds import SIMILARITY_DANGER_COSINE


@app.context_processor
def inject_similarity_thresholds():
    return dict(SIMILARITY_DANGER_COSINE=SIMILARITY_DANGER_COSINE)
```

If a context processor already exists for similar purposes, add the constant to it rather than creating a new one.

### Change 4 — add the inline concern strip to the macro

In `app/templates/ajax/convenor/submitters_macros.html`, inside the `project_tag` macro, inside the
`{% if r.language_analysis_complete %}` branch, immediately after the closing `</div>` of the risk-factor badges block (
before the `{% if rf.has_unresolved %}` CTA block), insert:

```jinja2
{# SIMILARITY CONCERN STRIP — direct links to avoid dashboard detour #}
{% set inline_concerns = r.inline_similarity_concerns %}
{% if inline_concerns %}
    <div class="d-flex flex-column gap-1 mt-1">
        {% for concern in inline_concerns %}
            {% set other = concern.record_b if concern.record_a_id == r.id else concern.record_a %}
            <div class="d-flex flex-row flex-wrap align-items-center gap-2 px-2 py-1 rounded small"
                 style="background-color: var(--db-orange-50); border: 1px solid var(--db-orange-200);">
                <i class="fas fa-search fa-fw" style="color: var(--db-orange-600);"></i>
                <span class="fw-semibold">{{ other.owner.student.user.name }}</span>
                <span class="text-body-secondary">
                    {{ other.period.config.project_class.abbreviation }}
                    {{ "%d/%d" | format(other.period.config.year, other.period.config.year + 1) }}
                </span>
                <span class="badge"
                      style="background-color: var(--db-orange-100); color: var(--db-orange-800);">
                    {{ concern.chunk_type | replace('_', ' ') }}
                </span>
                {% if concern.transformer_cosine >= SIMILARITY_DANGER_COSINE %}
                    <span class="badge bg-danger-subtle text-danger-emphasis">{{ "%.2f" | format(concern.transformer_cosine) }}</span>
                {% else %}
                    <span class="badge bg-warning-subtle text-warning-emphasis">{{ "%.2f" | format(concern.transformer_cosine) }}</span>
                {% endif %}
                <a href="{{ url_for('dashboards.similarity_concern_detail', concern_id=concern.id) }}#review"
                   class="btn btn-xs btn-db-orange ms-auto">
                    Review <i class="fas fa-arrow-right ms-1"></i>
                </a>
            </div>
        {% endfor %}
    </div>
{% endif %}
```

### What NOT to change

- Do not touch `similarity.py`, `_similarity_risk_factor_card.html`, `similarity_dashboard.html`, or
  `similarity_concern_detail.html`.
- Do not modify the risk-factor badge logic or the "Resolve risk factors" CTA — the strip is additive.
- Do not introduce any new routes or view functions.

### Verification

After making the changes, check that:

1. `SIMILARITY_INLINE_MIN_COSINE` and `SIMILARITY_DANGER_COSINE` are present in `llm_thresholds.py`.
2. Both properties are accessible on `SubmissionRecord` without circular import errors.
3. `SIMILARITY_DANGER_COSINE` is available in all Jinja2 template contexts.
4. The strip is absent when `inline_similarity_concerns` returns an empty list.
5. The "Review →" button href resolves to the correct URL for each concern.