## PREAMBLE

This task is to plan and implement a feature to offer a choice of email template to use when sending emails.

This relates to the following action buttons:
folder.

- "Send remniders" in @app/templates/admin/presentations/availability/waiting.html
- "Send reminders" in @app/templates/convenor/dashboard/overview_cards/waiting_confirmations.html
- "Send reminder" in @app/ajax/admin/presentations/outstanding_availability.py
- "Send reminder" in @app/ajax/convenor/outstanding_confirm.py
- The buttons that lead to generation of EmailWorkflows defined on GoLiveFormFactory,
  IssueFacultyConfirmRequestFormFactory, OpenFeedbackFormFactory, TestOpenFeedbackForm
- The buttons that lead to generation of EmailWorkflows defined on AvailabilityFormFactory
- The "email to selectors" and "email to supervisors" menu options (both final and draft) defined in
  @app/admin/matching/matches.py
- The "email to submitters" and "email to assesors" menu options defined in @app/ajax/admin/presentation/schedules.py

### TASK 1

For all of these buttons or events, determine the `type` of the EmailTemplate that is used in the generated workflow.

### TASK 2

Each of these workflows should be adjusted to allow the user to specify which EmailTemplate is to be used.
The EmailTemplate must be of the correct type, but is allowed to be at any level of override.
Events generated from convenor workflows where there is a clear ProjectClass or ProjectClassConfig instance
that provides the context could allow a template with a pclass-level or tenant-level override, or at the
global fallback level.

Events generated from other workflows should allow a tenant-level override where there is a Tenant instance
in the context, or at the global fallback level.

For events generated from PresentationAssessment instances of ScheduleAttempt instances, assume that all project classes
are associated with a single tenant. Enforce this by validators on the form where the PresentationAssessment is
set up.

For events generated from MatchingAttempt instances, assume that all project classes are associated with a single
tenant. Enforce this by validators on the form where the MatchingAttempt is set up.

Where the email generation event is triggered by submission of an existing form, the form can be modified to
allow specification of the EmailTemplate to use. Style the selection field using the select2 library. Use the
'select2--small' styling on the selectionCssClass and dropdownCssClass properties.

Where the email generation event is triggered by an <a> link directly on a template or on a dropdown menu, the
workflow should be changed the chain through an intermediate form where the user is offered a choice of templates.

The choice of templates can include inactive ones.

Build labels for the offered tempates using the BuildWorkflowTemplateLabel function.

### TASK 3

Once a template has been selected, it needs to be passed down to the Celery workflows that generate the
EmailWorkflow item and set its `template` property. The orchestration for these workflows needs to be changed
so that the selected template is passed through corre