# Consent workflow — Phase 1: Schema additions

## Objective

Add all new database fields required for the student consent workflow. This phase
is purely additive: no routes, templates, or business logic — only model changes,
a new audit table, and new `EmailTemplate` type constants.

---

## Reconnaissance

Before writing any code, read the following files in full and confirm your
understanding by listing the relevant items noted below:

1. `app/models/submissions.py`
    - Locate the `SubmissionRecord` class definition (search for
      `__tablename__ = "submission_records"`).
    - Note the block of existing report-related fields starting at
      `report_id`, including `report_exemplar`, `report_embargo`,
      `report_secret`, and `exemplar_comment`.
    - Note the `language_analysis` field and adjacent boolean flags
      (`language_analysis_started`, `language_analysis_complete`) —
      the new consent fields should be grouped after `exemplar_comment`
      and before the language analysis block.

2. `app/models/emails.py`
    - Locate `class EmailTemplateTypesMixin`.
    - Note the highest integer constant currently defined (currently 65:
      `MARKING_SUPERVISOR_REMINDER = 65`). New constants must be ≥ 70.
    - Note the `_TYPE_NAMES` dict immediately below the mixin — every
      new constant must have an entry added here.

3. `app/models/users.py` (or wherever `class User` is defined — search
   `app/models/` for `__tablename__ = "users"`).
    - Note existing columns so you can append `consent_token` in the
      right location (after the `box_*` fields, before any relationships).

4. `app/models/__init__.py`
    - Confirm that `SubmissionRecord` and `User` are exported, and note
      the pattern for adding a new model class (`ConsentAuditEvent`) to
      the exports.

---

## Changes

### 1. `app/models/submissions.py` — new fields on `SubmissionRecord`

Insert the following block **after** `exemplar_comment` and **before**
`language_analysis`. Add it as a clearly labelled section comment
`# CONSENT WORKFLOW`:

```python
# CONSENT WORKFLOW

# --- Exemplar consent ---
# Null = student has never consented. Set once on first grant; never reset
# on subsequent withdrawal/re-grant cycles. Used as the sentinel to trigger
# the one-time supervisor approval email.
exemplar_consent_granted_at = db.Column(db.DateTime(), default=None, nullable=True)

# True = student has currently withdrawn consent. Active consent state is:
#   exemplar_consent_granted_at IS NOT NULL AND exemplar_consent_withdrawn == False
exemplar_consent_withdrawn = db.Column(db.Boolean(), default=False, nullable=False)

# Timestamp of the most recent withdrawal (convenience field; full history
# is in ConsentAuditEvent).
exemplar_consent_withdrawn_at = db.Column(db.DateTime(), default=None, nullable=True)

# Supervisor approval for exemplar use. None = not yet actioned (or not yet
# requested because student has never consented). True = approved. False = declined.
# Set on first supervisor response; can be updated via the faculty My Students UI.
# NOT reset when the student withdraws and re-grants consent.
exemplar_supervisor_approved = db.Column(db.Boolean(), default=None, nullable=True)

# Timestamp of the most recent supervisor approval/decline action.
exemplar_supervisor_actioned_at = db.Column(db.DateTime(), default=None, nullable=True)

# --- Open day consent --- (parallel structure; no supervisor approval step)
openday_consent_granted_at = db.Column(db.DateTime(), default=None, nullable=True)
openday_consent_withdrawn = db.Column(db.Boolean(), default=False, nullable=False)
openday_consent_withdrawn_at = db.Column(db.DateTime(), default=None, nullable=True)

# --- Invitation tracking ---
# Set by the Celery callback after the consent invitation EmailWorkflowItem
# is successfully delivered. Null = not yet invited. The convenor UI uses
# this to distinguish "eligible but uninvited" from "invited, awaiting response".
consent_invitation_sent_at = db.Column(db.DateTime(), default=None, nullable=True)

# Timestamp of the one automatic reminder. The convenor can manually re-dispatch
# after this but is warned a reminder has already been sent.
consent_reminder_sent_at = db.Column(db.DateTime(), default=None, nullable=True)
```

Also add the following **properties** to `SubmissionRecord`, grouped with
the existing property methods:

```python
@property
def consent_eligible(self) -> bool:
    """
    True if this record is eligible to receive a consent invitation:
    the submission period is closed AND report_grade is not None.
    """
    return (
            self.period is not None
            and self.period.closed
            and self.report_grade is not None
    )


@property
def exemplar_consent_active(self) -> bool:
    """True if the student has given active (non-withdrawn) exemplar consent."""
    return (
            self.exemplar_consent_granted_at is not None
            and not self.exemplar_consent_withdrawn
    )


@property
def openday_consent_active(self) -> bool:
    """True if the student has given active (non-withdrawn) open day consent."""
    return (
            self.openday_consent_granted_at is not None
            and not self.openday_consent_withdrawn
    )


@property
def exemplar_fully_approved(self) -> bool:
    """
    True if the record is eligible for exemplar use: student has active consent
    AND the supervisor has approved.
    """
    return self.exemplar_consent_active and self.exemplar_supervisor_approved is True
```

### 2. `app/models/users.py` — `consent_token` on `User`

Add the following column to `User`, after the `box_*` token fields and
before the first `db.relationship`:

```python
# Token for the unauthenticated consent management route /consent/<token>.
# Generated eagerly when the consent invitation email is dispatched.
# Persists through Tier 1 and Tier 2 anonymisation — must never be nulled.
consent_token = db.Column(
    db.String(36, collation="utf8_bin"),
    unique=True,
    index=True,
    default=None,
    nullable=True,
)
```

### 3. `app/models/submissions.py` — new `ConsentAuditEvent` model

Add the following new model class at the **bottom** of `submissions.py`,
after all existing classes and event listeners:

```python
class ConsentAuditEvent(db.Model):
    """
    Immutable audit log of all consent state changes for a SubmissionRecord.
    One row per change event; never updated or deleted.
    """

    __tablename__ = "consent_audit_events"

    # --- Event type constants ---
    EXEMPLAR_GRANTED = 1
    EXEMPLAR_WITHDRAWN = 2
    EXEMPLAR_SUPERVISOR_APPROVED = 3
    EXEMPLAR_SUPERVISOR_DECLINED = 4
    EXEMPLAR_SUPERVISOR_REVOKED = 5
    OPENDAY_GRANTED = 10
    OPENDAY_WITHDRAWN = 11

    _EVENT_LABELS = {
        1: "Exemplar consent granted",
        2: "Exemplar consent withdrawn",
        3: "Exemplar supervisor approved",
        4: "Exemplar supervisor declined",
        5: "Exemplar supervisor approval revoked",
        10: "Open day consent granted",
        11: "Open day consent withdrawn",
    }

    id = db.Column(db.Integer(), primary_key=True)

    # owning submission record
    record_id = db.Column(
        db.Integer(),
        db.ForeignKey("submission_records.id"),
        nullable=False,
        index=True,
    )
    record = db.relationship(
        "SubmissionRecord",
        foreign_keys=[record_id],
        uselist=False,
        backref=db.backref("consent_audit_events", lazy="dynamic"),
    )

    # the user who made the change (student or faculty member);
    # nullable because token-authenticated requests have no session user
    actor_id = db.Column(
        db.Integer(), db.ForeignKey("users.id"), nullable=True
    )
    actor = db.relationship("User", foreign_keys=[actor_id], uselist=False)

    # event type — one of the constants above
    event_type = db.Column(db.Integer(), nullable=False, index=True)

    # UTC timestamp of the event
    timestamp = db.Column(
        db.DateTime(), nullable=False, default=datetime.utcnow, index=True
    )

    # optional free-text note (e.g. reason for supervisor decline)
    note = db.Column(db.Text(), default=None, nullable=True)

    # IP address of the requesting client (best-effort; may be None for
    # server-side Celery-triggered events)
    ip_address = db.Column(
        db.String(45, collation="utf8_bin"), default=None, nullable=True
    )

    @property
    def event_label(self) -> str:
        return self._EVENT_LABELS.get(self.event_type, f"Unknown event ({self.event_type})")
```

### 4. `app/models/emails.py` — new `EmailTemplate` type constants

In `EmailTemplateTypesMixin`, add a new group after `ATTENDANCE_PROMPT = 44`:

```python
# consent workflow
CONSENT_INVITATION = 70
CONSENT_REMINDER = 71
CONSENT_SUPERVISOR_APPROVAL_REQUEST = 72
```

In `_TYPE_NAMES`, add entries for these three constants:

```python
EmailTemplateTypesMixin.CONSENT_INVITATION: "Consent: Student invitation",
EmailTemplateTypesMixin.CONSENT_REMINDER: "Consent: Student reminder",
EmailTemplateTypesMixin.CONSENT_SUPERVISOR_APPROVAL_REQUEST: "Consent: Supervisor approval request",
```

### 5. `app/models/__init__.py` — export `ConsentAuditEvent`

Add `ConsentAuditEvent` to the imports from `submissions` and to `__all__`
(if present), following the existing alphabetical pattern.

---

## Alembic migration

Generate a new Alembic migration for all of the above. The migration must:

- Add all new columns to `submission_records` with the exact types, nullability,
  and defaults specified above.
- Add `consent_token` to `users`.
- Create the `consent_audit_events` table with correct FK constraints and indexes.
- Use `batch_alter_table` if the existing migration history shows this is needed
  for SQLite compatibility (check the most recent migration file for precedent).

The migration description should be:
`"Add consent workflow fields to SubmissionRecord, consent_token to User, ConsentAuditEvent table"`

---

## Verification

After completing all changes, run the following checks:

```bash
# 1. Confirm new columns appear on the model
python3 -c "
from app import create_app
app = create_app()
with app.app_context():
    from app.models import SubmissionRecord, User, ConsentAuditEvent
    sr = SubmissionRecord()
    assert hasattr(sr, 'exemplar_consent_granted_at')
    assert hasattr(sr, 'exemplar_consent_withdrawn')
    assert hasattr(sr, 'openday_consent_granted_at')
    assert hasattr(sr, 'consent_invitation_sent_at')
    assert hasattr(sr, 'consent_reminder_sent_at')
    assert hasattr(sr, 'consent_eligible')
    assert hasattr(sr, 'exemplar_consent_active')
    assert hasattr(sr, 'openday_consent_active')
    assert hasattr(sr, 'exemplar_fully_approved')
    u = User()
    assert hasattr(u, 'consent_token')
    print('All fields present')
"

# 2. Confirm new EmailTemplate constants
python3 -c "
from app.models.emails import EmailTemplateTypesMixin, _TYPE_NAMES
assert EmailTemplateTypesMixin.CONSENT_INVITATION == 70
assert EmailTemplateTypesMixin.CONSENT_REMINDER == 71
assert EmailTemplateTypesMixin.CONSENT_SUPERVISOR_APPROVAL_REQUEST == 72
assert 70 in _TYPE_NAMES
assert 71 in _TYPE_NAMES
assert 72 in _TYPE_NAMES
print('Email template constants OK')
"

# 3. Confirm migration generates without errors
flask db upgrade --sql 2>&1 | tail -20
```