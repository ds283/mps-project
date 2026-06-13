# Consent workflow — Phase 5: Convenor visibility on submitters_v2

## Objective

Surface consent and approval state as compact badges on each student card in
`submitters_v2.html`, so convenors can see at a glance which students have
consented, which are awaiting supervisor approval, and which have fully approved
exemplars. No new routes or models are needed in this phase.

---

## Reconnaissance

Read the following before writing any code:

1. `app/templates/convenor/dashboard/submitters_v2.html`
    - Read the full template to understand the card-per-student structure.
    - Locate the status strip section (where existing chips like "Report uploaded",
      "LLM result", "Similarity" etc. are rendered).
    - Identify the exact insertion point for consent badges — they belong at the
      end of the status strip, after existing chips.
    - Note the chip CSS classes in use (from `convenor-ui-patterns.md`):
      success-subtle, warning-subtle, secondary-bg patterns.

2. `app/convenor-ui-patterns.md`
    - Re-read the "Status strip chips" section for the exact CSS token pairs
      to use for each state.

3. `app/models/submissions.py`
    - Confirm the property names added in Phase 1:
      `exemplar_consent_active`, `openday_consent_active`,
      `exemplar_fully_approved`, `exemplar_supervisor_approved`,
      `exemplar_consent_granted_at`, `consent_invitation_sent_at`.

---

## Changes

### `app/templates/convenor/dashboard/submitters_v2.html` — consent badges

Within each student card's status strip, add the following consent badge block
at the end of the strip. The badges should be separated from the preceding chips
by a thin vertical separator (`<span class="mx-1 text-body-tertiary">|</span>`)
if any preceding chips are present.

Implement as a Jinja2 block that iterates over the submission periods for the
student and renders badges per `SubmissionRecord`:

```jinja
{# ---- Consent badges (per SubmissionRecord) ---- #}
{% if record.consent_invitation_sent_at or record.exemplar_consent_granted_at or record.openday_consent_granted_at %}
    <span class="mx-1" style="color: var(--bs-border-color)">|</span>
{% endif %}

{# Invitation status — only show if no consent given yet #}
{% if record.consent_invitation_sent_at and not record.exemplar_consent_granted_at and not record.openday_consent_granted_at %}
    <span class="badge"
          style="background: var(--bs-secondary-bg); color: var(--bs-secondary-color);
                 font-size: var(--cd-text-micro)"
          title="Consent invitation sent {{ record.consent_invitation_sent_at.strftime('%d %b %Y') }}">
        <i class="fas fa-envelope fa-fw"></i> Invited
    </span>
{% endif %}

{# Exemplar consent state #}
{% if record.exemplar_fully_approved %}
    <span class="badge"
          style="background: var(--bs-success-bg-subtle); color: var(--bs-success-text-emphasis);
                 border: 1px solid var(--bs-success-border-subtle); font-size: var(--cd-text-micro)"
          title="Exemplar: student consented, supervisor approved">
        <i class="fas fa-check fa-fw"></i> Exemplar approved
    </span>
{% elif record.exemplar_consent_active and record.exemplar_supervisor_approved is none %}
    <span class="badge"
          style="background: var(--bs-warning-bg-subtle); color: var(--bs-warning-text-emphasis);
                 border: 1px solid var(--bs-warning-border-subtle); font-size: var(--cd-text-micro)"
          title="Exemplar: student consented, awaiting supervisor approval">
        <i class="fas fa-clock fa-fw"></i> Exemplar pending
    </span>
{% elif record.exemplar_consent_active and record.exemplar_supervisor_approved == false %}
    <span class="badge"
          style="background: var(--bs-secondary-bg); color: var(--bs-secondary-color);
                 font-size: var(--cd-text-micro)"
          title="Exemplar: student consented, supervisor declined">
        <i class="fas fa-times fa-fw"></i> Exemplar declined
    </span>
{% endif %}

{# Open day consent state #}
{% if record.openday_consent_active %}
    <span class="badge"
          style="background: var(--bs-success-bg-subtle); color: var(--bs-success-text-emphasis);
                 border: 1px solid var(--bs-success-border-subtle); font-size: var(--cd-text-micro)"
          title="Open day: student consented">
        <i class="fas fa-check fa-fw"></i> Open day
    </span>
{% endif %}
```

Note that `record.exemplar_supervisor_approved == false` in Jinja2 tests for
the Python `False` value — confirm this works correctly in the Jinja2 version
in use, or use `record.exemplar_supervisor_approved is sameas false` if needed.

### No route changes

The consent badge data is computed from properties on `SubmissionRecord` that
are already available in the template context. No changes to the convenor route
are needed.

---

## Verification

```bash
# Template renders without error for the convenor submitters view
# Navigate to the convenor dashboard → Submitters for a project class
# with at least one record that has consent data set.

# Confirm badge rendering for each state by temporarily setting field values
# on a test record:
python3 -c "
from app import create_app
app = create_app()
with app.app_context():
    from app.models import SubmissionRecord
    from datetime import datetime
    r = SubmissionRecord.query.filter(
        SubmissionRecord.report_grade.isnot(None)
    ).first()
    if r:
        r.consent_invitation_sent_at = datetime.utcnow()
        r.exemplar_consent_granted_at = datetime.utcnow()
        r.exemplar_consent_withdrawn = False
        # Leave exemplar_supervisor_approved as None to test 'pending' state
        from app.database import db
        db.session.commit()
        print(f'Set test consent state on record #{r.id}')
        print(f'  consent_eligible: {r.consent_eligible}')
        print(f'  exemplar_consent_active: {r.exemplar_consent_active}')
        print(f'  exemplar_fully_approved: {r.exemplar_fully_approved}')
"
```