## offer-templates task state

### Infrastructure

- [x] Add GetWorkflowTemplates() to app/shared/forms/queries.py
- [x] Add ChooseEmailTemplateForm to app/shared/forms/forms.py
- [x] Create app/templates/shared/choose_email_template.html

### Single-tenant validators (Task 2a)

- [x] MatchingAttempt form validator (app/admin/forms.py)
- [x] PresentationAssessment form validator (app/admin/forms.py)

### Form-based triggers (Task 2b)

- [x] GoLiveFormFactory: add 3 template fields (app/convenor/forms.py)
- [x] GoLive view: inject query_factory + pass template_ids (app/convenor/lifecycle.py)
- [x] GoLive Jinja2 template: render 3 selectors with section headings + Select2
- [x] IssueFacultyConfirmRequestFormFactory: add 1 template field (app/convenor/forms.py)
- [x] Issue confirm view: inject + pass template_id (app/convenor/lifecycle.py)
- [x] Issue confirm Jinja2 template: render selector + Select2
- [x] OpenFeedbackFormFactory: add 1 template field (app/convenor/forms.py)
- [x] OpenFeedback view: inject + pass template_id (app/convenor/marking_feedback.py)
- [x] OpenFeedback Jinja2 template: render selector + Select2
- [x] TestOpenFeedbackForm: add 1 template field (app/convenor/forms.py)
- [x] TestOpenFeedback view: inject + pass template_id (app/convenor/marking_feedback.py)
- [x] TestOpenFeedback Jinja2 template: render selector + Select2
- [x] AvailabilityFormFactory: add 1 template field (app/admin/forms.py)
- [x] Availability view: inject + pass template_id (app/admin/assessments.py)
- [x] Availability Jinja2 template: render selector + Select2

### Intermediate form routes (Task 2c)

- [x] Confirmation reminder bulk: intermediate route (app/convenor/lifecycle.py)
- [x] Confirmation reminder bulk: update button href (waiting_confirmations.html)
- [x] Confirmation reminder individual: intermediate route (app/convenor/lifecycle.py)
- [x] Confirmation reminder individual: update menu href (outstanding_confirm.py)
- [x] Availability reminder bulk: intermediate route (app/admin/assessments.py)
- [x] Availability reminder bulk: update button href (waiting.html)
- [x] Availability reminder individual: intermediate route (app/admin/assessments.py)
- [x] Availability reminder individual: update menu href (outstanding_availability.py)
- [x] Matching selector email: intermediate route (app/admin/matching.py)
- [x] Matching selector email: update menu href (app/ajax/admin/matching/matches.py)
- [x] Matching supervisor email: intermediate route (app/admin/matching.py)
- [x] Matching supervisor email: update menu href (app/ajax/admin/matching/matches.py)
- [x] Schedule submitter email: intermediate route (app/admin/scheduling.py)
- [x] Schedule submitter email: update menu href (app/ajax/admin/presentations/schedules.py)
- [x] Schedule assessor email: intermediate route (app/admin/scheduling.py)
- [x] Schedule assessor email: update menu href (app/ajax/admin/presentations/schedules.py)

### Celery task changes (Task 3)

- [x] app/tasks/go_live.py: golive_notify_faculty
- [x] app/tasks/go_live.py: golive_notify_selectors
- [x] app/tasks/go_live.py: golive_finalize
- [x] app/tasks/issue_confirm.py: issue_notifications
- [x] app/tasks/issue_confirm.py: reminder_email (bulk)
- [x] app/tasks/issue_confirm.py: reminder_email / send_reminder_email (individual)
- [x] app/tasks/marking.py: send_marking_emails
- [x] app/tasks/availability.py: issue_assessor_email
- [x] app/tasks/availability.py: send_reminder_email
- [x] app/tasks/matching_emails.py: publish_email_to_selector
- [x] app/tasks/matching_emails.py: publish_email_to_supervisor
- [x] app/tasks/scheduling.py: publish_to_submitters
- [x] app/tasks/scheduling.py: publish_to_assessors
