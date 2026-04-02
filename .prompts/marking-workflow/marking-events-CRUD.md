## DESCRIPTION

This task is intended to provide access to the main inspector view for MarkingEvent instances, and to provide the
basic database CRUD functionality to manage them.

General implementation patterns:

- Views that provide lists (of MarkingEvent, MarkingWorkflow, PeriodAttachment, etc.) should use a Datatables
  based front end backed by an AJAX endpoint. Implement an AJAX row formatted in @app/ajax/convneor.
- Use the ServerSideSQLHandler pattern where possible to provide sorting, searching, and pagination in the AJAX
  endpoint. Use ServerSideInMemoryHandler where it is not possible to build a single SQL query that will satisfy
  all requirements.
- Do not use separate "display" and "sortstring" fields in Datatables rows when ServerSideSQLHandler is used.
  These do not format correctly and are not needed. ServerSideSQLHandler will handle and sorting required.
- Use the select2() library to render QuerySelectField and QueryMultipleSelectField fields. Use the
  `select2-small` value for the `selectionCssClasss` and `dropdownCssClass` properties.

This is a large refactoring. Please generate an on-disk progress file and update it as you work, so that state
can easily be recovered if the implementation runs over more than one rate-limit window.

### TASK 1

Design UI elements to appear on the convenor status overview page @app/templates/convenor/dashboard/status.html
and the submission period overview page @app/templates/convenor/dashboard/periods.html. These should surface to the
convenor any MarkingEvent instances that are currently in the database and attached to the current ProjectClassConfig.
The status.html page should provide a summary. The periods.html page should provide more detail.

To maintain unity with the current UI, this probably requires a separate inspector for the list of MarkingEvents,
similar the convenor.inspect_period_units() and associated template
@app/templates/convenor/supervision_events/inspect_period_units.html. Management of MarkingEvent instances would be
done from this inspector rather than direct from the convenor dashboard.

The current layout of SubmissionPeriodUnits in @app/templates/convenor/dashboard/overview_cards/period_settings is
verbose and takes up quite a lot of vertical space. Please design a more compact layout that integrates
nicely with the corresponding MarkingEvent list.

### TASK 2

Design CRUD views to implement creation, update, and deletion of MarkingEvent instances. The delete option should
only be shown to users with the "admin" role who belong to the same Tenant at the ProjectClass, or users with
the "root" role (no matter what Tenant they belong to).

Each MarkingEvent instance is associated with a single SubmissionPeriod. Its `name` should be unique within the
SubmissionPeriod. Enforce this via WTForms validation. See examples such as globally_unique_project_tag()
(used to validate the name when creating a new item) and unique_or_original_project_tag() (used to validate the name
when editing an existing item) in @app/admin/forms.py for an example of how this can be done.

When designing forms for the create and update views, you should share as much configuration as possible. See the
existing mixin pattern in @app/admin/forms.py for examples, e.g. ProjectTagMixin, AddProjectTagForm, and
EditProjectTagForm.

MarkingEvent instances should be created with the `closed` flag cleared. Do not provide a boolean checkbox for this
flag on the update form. Instead, provide an action button in the inspector that will trigger the close event.
This is because closing a MarkingEvent is a one-time event, not something that can be turned on and off at will.
The close button should chain through the @app/templates/admin/danger_confirm.html template to check that the
user really does wish to close the MarkingEvent. For now, leave the close event handler route as a stub that
sets the `closed` flag but takes no other action.

Create new views in @app/convenor/markingevent.py unless they clearly do not fit there.

### TASK 3

For each MarkingEvent, the inspector should summarize the MarkingWorkflow instances that it contains. It should allow
access to another inspector allowing these MarkingWorkflow instances to be viewed, and providing CRUD functionality
to manage them. This could re-use convenor.marking_workflow_inspector() and its Jinja2 template if it is possible
to do so cleanly. Prefer to separate the views, however, if re-use would produce convoluted Python or Jinja2 markup.

The MarkingWorkflow creata/update forms should use the same mixin pattern described in TASKS 2, so that they share
configuration where possible.

The `name` of the MarkingWorkflow should be unique within the MarkingEvent. Enforce this via WTForms validation, as
for MarkingEvent.

The `role` property should be specifiable on creation, but can not be adjusted after the MarkingWorkflow is created.
Do not offer separate options for the ROLE_SUPERVISOR and ROLE_RESPONSIBLE_SUPERVISOR roles; treat these as just one
supervisor role.

The `scheme` property should allow an `active` MarkingScheme associated with the ProjectClass to be selected.
This should only be editable up to the point that any attached MarkingReport has **either** its `distributed` flag
set to True, or has a nonempty `report` field.

It should be possible to select members of the `attachments` collection from PeriodAttachment instances that have
been uploaded and are associated with the SubmissionPeriodRecord of the owning MarkingEvent. The list of attachments
can be displayed on the editing form, with a button on each row to remove the associated attachment.
Adding an attachment may require a separate view to select which attachment to attach.

`notify_on_moderation_required` and `notify_on_validation_required` should allow the user to specify a collection
of User instances. These should only include users belonging to the same Tenant as the ProjectClass.
Group this list by co-convenor, and then the "office", "exam_board" and "external" roles. In future there may be
a "smt" or "smt-reporting" role for management to give visibility into some processes. Your design should be
sufficiently extensible to allow these to be easily added later.

### TASK 4

On creation of a MarkingWorkflow, a Celery workflow should be dispatched to generate the SubmitterReport and
MarkingReport instances associated with it.

A SubmitterReport should be generated for each SubmissionRecord instance associated with the SubmissionPeriodRecord.
Its `workflow_state` should initially be set to "NOT_READY". Provide sensible defaults for all grading and feedback
fields. These should generally be None where possible, but some boolean fields should default to False.

The `feedback_reports` collection should be set empty.

For each SubmitterReport, a number of MarkingReport instances shuold be generated, one for each SubmissionRole
attached to the SubmissionRecord where the role matches the role specified in the MarkingWorkflow **except** that
ROLE_SUPERVISOR and ROLE_RESPONSIBLE_SUPERVISOR should be treated as a single supervisor role. The difference between
these roles emerges only later in the marking workflow.

### TASK 5

Where SubmissionRoles are created (or deleted) from the convenor dashboard while a MarkingEvent is active (i.e.
not `closed`), the corresponding MarkingReport instances should be updated to reflect the new set of SubmissionRoles.
Use the same rules for ROLE_SUPERVISOR and ROLE_RESPONSIBLE_SUPERVISOR as above.

### TASK 6

The MarkingWorkflow inspector should summarize the SubmitterReport and MarkingReport instances associated with it.
It should also allow access to separate SubmitterReport and MarkingReport inspectors, similar to
convenor.submitter_reports_inspector() and convenor.marking_reports_inspector(). Consider whether these can share
code, if this can be done cleanly and without writing convoluted logic. These inspectors should **NOT** allow
editing of the SubmitterReport or MarkingReport instances when invoked from the "Assessment archive" tab.
However, they should allow editing when invoked from the MatchingEvent/MatchingWorkflows of a currently open event.

Show a compact timeline of key `workflow_state` events for a SubmitterReport.

**NOTE** Please update route names in @app/convenor/markingevent.py, if needed, to reflect their actual purpose and
effect.
