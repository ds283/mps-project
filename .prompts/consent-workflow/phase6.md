# Consent workflow — Phase 6: Email templates and implementation notes

## Objective

Create the three `EmailTemplate` database records needed by the consent
workflow, and document the overall implementation sequence, testing strategy,
and known outstanding items.

This phase is primarily a **data migration / admin task** rather than a code
change. Email templates are stored in the database and managed via the admin
UI, but seed templates must be inserted by migration for the system to function
correctly.

---

## Background

Three email template types were registered in Phase 1:

| Constant                              | Value | Purpose                                                       |
|---------------------------------------|-------|---------------------------------------------------------------|
| `CONSENT_INVITATION`                  | 70    | Sent to student when convenor dispatches invitations          |
| `CONSENT_REMINDER`                    | 71    | One automatic reminder to non-responding students             |
| `CONSENT_SUPERVISOR_APPROVAL_REQUEST` | 72    | Sent to supervisor when student first grants exemplar consent |

Each template type supports per-tenant and per-project-class specialisation
(via `EmailTemplate.tenant_id` and `EmailTemplate.pclass_id`). The seed
templates created here are global (both FK fields null), so they apply to all
tenants and project classes unless overridden.

---

## Changes

### 1. Alembic data migration: seed email templates

Create a new Alembic migration (data-only, no schema changes) that inserts
the three seed templates. Use the existing pattern for data migrations in this
codebase — check the most recent data migration for the `op.execute` or
`op.bulk_insert` pattern used.

The templates use Jinja2 HTML body syntax, consistent with the existing
template format. Check an existing `EmailTemplate` row in the database (or in
a previous migration) to confirm the expected `subject` and `html_body` field
format.

**Template 70 — Consent invitation (student)**

Subject:

```
Your project report — permissions for future use
```

Body (Jinja2 HTML, minimal — the full wording will be edited via the admin UI):

```html
<p>Dear {{ record.owner.student.user.first_name or "student" }},</p>

<p>Your project report for <strong>{{ pclass_name }} {{ year_a }}–{{ year_b }}</strong>
    has been marked and your grade has been confirmed.</p>

<p>We would like to ask whether you are willing to allow your report to be used
    in the following ways. Both are entirely optional and independent of each other.
    Declining has no effect on your assessment.</p>

<ul>
    <li><strong>Teaching exemplar</strong> — your report (with your name removed,
        candidate number visible) may be shared with future cohorts as a graded example
        of the standard of work at your grade level.
    </li>
    <li><strong>Open day and promotional events</strong> — your project title and
        abstract may be displayed at University open days. Your name will not be shown.
    </li>
</ul>

<p>To indicate your preferences, please follow this link:</p>

<p><a href="{{ consent_url }}">Manage your report permissions</a></p>

<p>You can change your preferences at any time using the same link.
    <strong>Please keep this link in a safe place</strong> — it is your permanent
    way to manage these preferences, even after you leave the University.</p>

<p>If you have any questions, please contact the School office.</p>
```

**Template 71 — Consent reminder (student)**

Subject:

```
Reminder: your project report permissions
```

Body:

```html
<p>Dear {{ record.owner.student.user.first_name or "student" }},</p>

<p>We recently wrote to ask whether your project report for
    <strong>{{ pclass_name }} {{ year_a }}–{{ year_b }}</strong>
    could be used as a teaching exemplar or at open days.</p>

<p>We have not yet received a response. If you are happy for us to use your
    report, or if you would like to decline, please follow this link:</p>

<p><a href="{{ consent_url }}">Manage your report permissions</a></p>

<p>If you have already responded, please disregard this message.</p>
```

**Template 72 — Supervisor approval request**

Subject:

```
Student consent for exemplar use — {{ pclass_name }} {{ year_a }}–{{ year_b }}
```

Body:

```html
<p>Dear {{ role.user.first_name or "colleague" }},</p>

<p>A student you supervised on <strong>{{ pclass_name }} {{ year_a }}–{{ year_b }}</strong>
    has given consent for their project report to be used as a teaching exemplar
    for future cohorts.</p>

<p>Before the report can be used in this way, we need your approval that you
    consider it suitable — for example, that it does not overlap too closely with
    projects you expect to run in future years.</p>

<p>To review the report and indicate your decision, please log in to the
    MPS projects system and visit your
    <a href="{{ approval_url }}">My students</a> page.</p>

<p>You only need to respond once. If the student subsequently changes their
    consent preferences, you will not be contacted again unless you choose to
    update your decision yourself.</p>
```

### 2. Migration description

```
"Add seed EmailTemplate records for consent workflow (types 70, 71, 72)"
```

---

## Implementation sequence summary

The phases should be executed in order. Each phase is independently deployable
but depends on the database state from the previous one:

| Phase                   | Depends on     | Can be tested without                                     |
|-------------------------|----------------|-----------------------------------------------------------|
| 1 — Schema              | Nothing        | All subsequent phases                                     |
| 2 — Token route         | Phase 1        | Phase 3 (can test with manual DB insert of consent_token) |
| 3 — Convenor dispatch   | Phases 1, 2, 6 | Phase 4, 5                                                |
| 4 — Faculty My students | Phases 1, 2    | Phase 3 (approval UI works independently)                 |
| 5 — Convenor badges     | Phase 1        | All others                                                |
| 6 — Email templates     | Phase 1        | Phase 3, 4 will log warnings but not crash                |

---

## Outstanding items not covered by these prompts

The following are known gaps that require separate work:

1. **`User.name` / `is_anonymised` property** — The handoff document (§6)
   specifies that `User.name` should return `f"Anonymised student [{self.uuid[:8]}]"`
   when `first_name is None`, and that an `is_anonymised` property should be
   added. This is referenced in Phase 4 templates but not implemented by these
   prompts. Implement as a separate schema/model phase.

2. **`User.is_anonymised` suppression in Phase 4 template** — The "My feedback"
   button and email link in `my_students.html` reference `user.is_anonymised`.
   Until that property is added, use `record.owner.student.user.first_name is none`
   as an inline guard.

3. **CSRF exemption for `consent_by_token`** — Phase 2 notes that
   `consent_by_token` must either be `@csrf.exempt` or render a CSRF token
   without a session. Confirm the correct approach by checking how other
   unauthenticated POST routes are handled in the codebase (if any exist),
   or consult the Flask-WTF configuration in `app/__init__.py`.

4. **`departed_at` on `StudentData`** — Required to anchor the Tier 2 clock
   (§2 of handoff doc). Not part of this workflow but should be implemented
   before the anonymisation jobs are scheduled.

5. **Tier 1 / Tier 2 anonymisation jobs** — The Celery beat tasks that null
   credentials at graduation and apply Tier 2 nulling after 6 years are not
   part of this implementation. The consent workflow is fully functional without
   them; they are a separate compliance task.

6. **`consent_token` generation at account deactivation** — When a student's
   account is deactivated (Tier 1), their `User.consent_token` should be
   generated if not already set (it may have been set earlier by the invitation
   dispatch). This belongs in the Tier 1 anonymisation job.

7. **Inclusion of consent URL in existing farewell emails** — If the system
   already sends a departure/deactivation email to students, that email should
   include the `consent_url` (built from `User.consent_token`). This is a
   separate template edit.

8. **Admin UI for email template management** — The seed templates in Phase 6
   provide minimal working bodies. The admin interface for editing templates
   (already existing) should be pointed out to the convenor so they can tailor
   the wording. No code change needed, but an operational note for deployment.

9. **`report_exemplar` flag semantics** — The existing `report_exemplar`
   Boolean on `SubmissionRecord` was previously used as a convenor-set editorial
   flag. Now that `exemplar_fully_approved` encodes the consent+approval state,
   decide whether `report_exemplar` should be (a) deprecated, (b) retained as
   the convenor's final publication decision layered on top of `exemplar_fully_approved`,
   or (c) removed. Until a decision is made, leave it unchanged.