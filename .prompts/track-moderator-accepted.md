## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

Some workflows trigger a moderation step, in which

In line with project policy, DO NOT attempt to generate any Alembic database migrations, even writing them manually.
I will generate migrations myself.

## TASK 1. Track which `ModeratorReport` has been accepted.

Once a `SubmittingReport` triggers a moderation event, one or more moderators are invited to submit `ModeratorReport`
reports and recommend an assigned grade. This information is captured on the `ModeratorReport` model. When the first
`ModeratorReport` instance is submitted, the recommended grade is automatically assigned to the `SubmittingReport`.
The `SubmittingReport` is then moved to the `READY_TO_SIGN_OFF` state.

Further submission of `ModeratorReport` reports do not change the grade, but the `SubmittingReport` is moved to its
`REQUIRES_CONVENOR_INTERVENTION` state. The UI surfaces options for the convenor to postively accept a recommendation.
When this is done, the `ModeratorReport.grade` recommendation is copied to the `SubmittingReport.grade` field and
the `SubmittingReport` is moved to the `READY_TO_SIGN_OFF` state.

We would like to track which `ModeratorReport` has been accepted. Please consider options for tracking this information.

Possibilities include:

- Add an `accepted` field to the `ModeratorReport` model and use this to track which report has been accepted. This
  approach is simple but has the disadvantage that multiple `ModeratorReport` instances could accidentally end up in the
  `accepted` state.
- Add a FK relationship on `SubmitterReport` to link to the accepted `ModeratorReport`. This approach makes it
  impossible to have more than one report in the accepted state.

Please also:

- Add `moderator_accepted_id` and `moderator_accepted_timestamp` fields to the `SubmittingReport` model.
  `moderator_accepted_id` should be an FK linking to the `SubmissionRole` instance belonging to the moderator. When an
  acceptance event occurs, implicitly or explicitly, these fields should be updated. These events can occur on
  submission of a `ModeratorReport` report in faculty.moderator_report_form() in @app/faculty/views.py, or when a
  convenor accepts a recommendation in convenor.accept_moderator_grade() in @app/convenor/markingevent.py. Also as a
  `moderator_accepted_by` relationship to the `SubmissionRole` belonging to the moderator.

Once an approach for tracking the accepted `ModeratorReport` has been chosen, please:

- Construct a plan to implement this tracking, based on instrumenting the faculty.moderator_report_form() and
  convenor.accept_moderator_grade() routes. Please check that there are no other pathways by which the accepted
  `ModeratorReport` can be changed.

## TASK 2. Provide missing attachments to moderation invitations

The _emit_moderator_assignment_email() function in @app/tasks/markingevent.py sends an email invitation to a newly
assigned moderator. However, it does not include the attachments for the student's processed report, and any attachments
that were specified by the convenor when setting up the parent `MarkingWorkflow` instance. These are held in the
`MarkingWorkflow.attachments` collection.

Please refactor _emit_moderator_assignment_email() to include these attachments. The attachments that should be included
are those attached by the dispatch_emails() task in @app/tasks/marking.py.
