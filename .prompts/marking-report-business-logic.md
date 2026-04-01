## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

The next step in the refactoring is to implement the business logic related to moving MarkingReport and SubmitterReport
instances between lifecycle states when a marking report is submitted.

This is a large task. Please write a plan file and maintain a status file in the top level of the Git repository, so
that state can be tracked across several rate limit windows if needed.

## TASK 1 - Track weight of each marking report

Add a `weight` field to `MarkingReport`. It should be initialized from the `weight` field of the parent `SubmissionRole`
when the `MarkingReport` is created, but can later be edited independently.

Adjust the `MarkingReport` inspector served by marking_report_data() in @app/ajax/convenor/markingevent.py to show this
weight field. Allow it to be edited using a new properties editor. Make a link to this editor available on the dropdown
menu, below the "Edit report" entry.

## TASK 2 - Adjust the way MarkingReport instances are created.

MarkingReport instances are added to the database in initialize_marking_workflow() in @app/tasks/markingevent.py.

Please adjust the way this is done for ROLE_SUPERVISOR and ROLE_RESPONSIBLE_SUPERVISOR workflows.

- If the workflow specifies ROLE_SUPERVISOR, then:
    - If the `SubmissionRecord` has only ROLE_RESPONSIBLE_SUPERVISOR roles attached, generate a `MarkingReport` for each
      of these roles.
    - If the `SubmissionRecord` has only ROLE_SUPERVISOR roles attached, generate a `MarkingReport` for each of these
      roles.
    - If the `SubmissionRecord` has **both** ROLE_RESPONSIBLE_SUPERVISOR and ROLE_SUPERVISOR roles attached, then
      generate a `MarkingReport **only** for ROLE_SUPERVISOR cases. This is because the supervisor is responsible for
      the marking of the submission. The report will be routed to a ROLE_RESPONSIBLE_SUPERVISOR for final approval. See
      Task 3 below.
- If the workflow specifies ROLE_RESPONSIBLE_SUPERVISOR, generate a `MarkingReport` only for ROLE_RESPONSIBLE_SUPERVISOR
  `SubmissionRole`s

## TASK 3 - Lifecycle states of MarkingReport and SubmitterReport instances.

When a MarkingReport is submitted, the `grade_submitted_timestamp` field is set. The marker has 24 hours from that time
to edit their report. After that, if they need further time, the convenor must return the report to the marker by using
the "Clear grade" menu option.

When the 24 hour window closes, we wish to take a number of actions. These should be implemented by a Celery workflow.

It will be necessary to decide how to schedule the task. Please consider the following options, and explore further
options if appropriate, and make a recommendation.

- Option A. Periodically poll for MarkingReport instances that require action using a background Celery task. This is
  easy but inefficient.
- Option B. Schedule a task to run at the `grade_submitted_timestamp` + 24 hour point using `DatabaseSchedulerEntry`
  from @app/models/scheduler.py. Generate a `CrontabSchedule` for the target time, and then expire the
  `DatabaseSchedulerEntry` after the task has run using its `expires` field.

However the task is scheduled, it should perform the following operations:

### Lifecycle of the just-submitted `MarkingReport`

#### If the `MarkingReport` belongs to a `SubmissionRole` with ROLE_MARKER:

In this case the marker can sign off on their own report.

- set the `MarkingReport.signed_off_id` field to the `User.id` of the owner of the `SubmissionRole`
- set the `MarkingReport.signed_off_timestamp` field to the current time

#### If the `MarkingReport` belongs to a `SubmissionRole` with ROLE_RESPONSIBLE_SUPERVISOR:

In this case the marker can sign off on their own report.

- set the `MarkingReport.signed_off_id` field to the `User.id` of the owner of the `SubmissionRole`
- set the `MarkingReport.signed_off_timestamp` field to the current time

#### If the `MarkingReport` belongs to a `SubmissionRole` with ROLE_SUERVISOR_PROPERTY:

In this case there should also be ONE OR MORE `SubmissionRole`s with ROLE_RESPONSIBLE_SUPERVISOR attached to the parent
`SubmissionRecord`. We need to find all of these roles and link them to the `MarkingReport` so that they can sign off.

Note that after the adjustment in TASK 2 above, the owners of these `SubmissionRole` instanes may NOT yet be associated
with the MarkingWorkflow in any way.

One possible option is:

- Option A. Add a new collection on MarkingRecord linked to an association table. Add any `SubmissionRole` instances for
  ROLE_RESPONSIBLE_SUPERVISOR to this collection.

Please consider this option and explore further options if appropriate.

For all roles linked to the `MarkingReport`, generate an `EmailWorkflow` instance and attach `EmailWorkflowItem`
instances for all users linked as reponsible supervisors. Use the MARKING_NEEDS_SIGN_OFF template. Ensure all
`EmailWorkflowItem` instances are encapsulated within the same `EmailWorkflow`. Defer sending for 1 hour.
Attach the student's `StudentData` as the subject payload and the `MarkingReport` instance as the body payload.

### Lifecycle of the parent `SubmitterReport`

In implementing this section, please consider that further steps in the lifecycle will remain to be implemented after
this task. Your planned implementation should be extensible enough to accommodate insertion of new lifecycle states
easily.

The task should then inspect the state of the `SubmitterReport` that owns the just-submitted `MarkingReport`.
This logic will also need to run when a ROLE_RESPONSIBLE_SUPERVISOR user signs off on a report, or when feedback is
later submitted, so it may need to be broken out separately.

- If all attached `MarkingReport` instances have `report_submitted`, `feedback_submitted` and `signed_off_id` set, then
  consider whether the submitted reports agree within the required tolerance, as specified below.
- If all attached `MarkingReport` instances have `report_submitted` and `signed_off_id` set, but some are awaiting
  `feedback_submitted`, then the SubmitterReport advances to the AWAITING_FEEDBACK stage.
- If all attached `MarkingReport` instances have `report_submitted`, but some are awaiting `signed_off_id`, then the
  SubmitterReoprt advances to the AWAITING_RESPONSIBLE_SUPERVISOR_SIGNOFF stage.

To check for whether reports agree within the required tolerance:

- If the `LiveMarkingScheme` for this `MarkingWorkflow` **does not** have the `uses_tolerance` flag set, then no
  tolerance check is required. Combine the grades from each `MarkingReport` as an average weighted by the weight
  assigned to each `MarkingReport` and advance the `SubmitteReport` to the READY_TO_SIGN_OFF state.
  Set `grade_generated_by_id` to the id of the convenor, and attach a `grade_generated_timestamp` set to the current
  time.
- If the `LiveMarkingScheme` for this `MarkingWorkflow` **does** have the `uses_tolerance` flag set, the
  `SubmitterReport` must be marked as out-of-tolerance and this setting persisted in the database. This likely requires
  a new field. This lifecycle state should be clearly highlighted to the user on the `SubmitterReport` inspector page.
- Generate a new `EmailWorkflow` instances and attach `EmailWorkflowItem` instances for all users in the
  `notify_on_moderation_required` collection on the parent `MarkingWorkflow`. Defer the emails to be sent until 9am on
  the following day. Supply the `SubmitterReport` instance to the `EmailWorkflowItem` as its body payload. Provide the
  `StudentData` of the student as the subject payload. Ensure that a single `EmailWorkflow` encapsulates all
  `EmailWorkflowItem` instances generated at this point.
- If there are already one or more roles with ROLE_MODERATOR assigned to the parent `SubmissionRecord`, select one of
  these randomly and assign this role as the moderator for this `SubmitterReport`. See below. Once assigned,
  move this `SubmitterReport` to the AWAITING_MOERATOR_REPORT state.
- If there are no roles with ROLE_MODERATOR assigned to the parent `SubmissionRecord`, advance this `SubmitterReport`
  to the NEEDS_MODERATOR_ASSIGNED state.

To assign a moderator to this `SubmitterReport`:

- A new `ModeratorReport` model is required. This should capture a numerical `grade` field, a `report` field giving the
  moderator's report, and `report_submitted` and `submitted_timestamp` fields capturing whether the report has been
  submitted. We also need an FK relationship to the owning `SubmitterRole` and the parent `SubmitterReport`. Generate
  convenience properties to access the parent `SubmitterReport` and `MarkingWorkflow`.
- Create a new blank instance of the `ModeratorReport` and link to the moderator's `SubmitterRole` and
  `SubmitterReport`.
- Generate an `EmailWorkflow` instance and attach and `EmailWorkflowItem` for the newly assigned moderator.
  Use the `StudentData` instance as the subject payload and the `SubmitterReport` instance as the body payload.
  Ensure that a single `EmailWorkflow` encapsulates all `EmailWorkflowItem` instances generated at this point.
  Use the MARKING_MODERATOR template type.
- Advance the lifecycle state of the `SubmitterReport` to the AWAITING_MODERATOR_REPORT state.

You must also run this logic when a marker changes their feedback using faclulty.edit_marking_feedback(), and
when a moderator submits their report.

## TASK 4 - `SubmitterReport` instances i the NEEDS_MODERATOR_ASSIGNED state require a CTA on the

`SubmitterReport` inspector.

This should offer the convenor an opportuity to select any user with the `active` flag set, with an enrolment in the
project class (as recorded by `EnrollmentRecord`) with `supervisor_state == SUPERVISOR_ENROLLED` or
`marker_state == MARKER_ENROLLED`. This can be presented as a relatively simple form, surfacing any helpful context,
using a QueryMultpleSelectField rendered by select2.

Once a moderator has been selected, a new `SubmissionRole` should be generated for this `User` with ROLE_MODERATOR, and
attached to the parent `SubmissionRecord`.

Once proceed to generate assign this `SubmssionRole` as the moderator for this `SubmitterReport`, as described in
TASK 3.

For `SubmittingReport`s in the NEEDS_MODERATOR_ASSIGNED or AWAITING_MODERATOR_REPORT states, provide an option on the
dropdown menu to "Assign moderator" that will allow the convenor to select an additional moderator, re-using the UI
above.

## TASK 5 - Call to action for sign off by ROLE_RESPONSIBLE_SUPERVISOR users

If a user has any `SubmitterReport` instances assigned to them requiring sign-off, then these need to be surfaced on the
user's dashboard.

Implement a new nav pill similar to the "Marking" pill on the faculty member's dashboard. In the linked pane, generate
call-to-action notifications similar to those used for the `MarkingReport` instances.

The link should take the user to the view_marking_report() view, but provide a button at the button labelled "Approve
report". When this is clicked, we must:

- Set the `SubmitterReport.signed_off_id` field to the `User.id` of the user who clicked the button
- Set the `SubmitterReport.signed_off_timestamp` field to the current time
- Remove all responsible supervisors from the collection on the `SubmitterReport` (or however we decided to keep track
  of these assignments)
- Proceed to re-evaluate the lifecycle state of the `SubmitterReport` as described in TASK 3.

## TASK 6 - Call to action for a moderator report

If any user has an unsubmitted `ModeratorReport` instance assigned to them, this needs to be surfaced on the user's
dashboard.

Implement a new nav pill similar to the "Marking" bill, but labelled as "Moderation". In the linked pane, generate
call-to-action notifications similar to those used for the `MarkingReport` instances. Do not show reports that have been
submitted, for which `report_submitted` is True. Link each notification to a form where the moderator can return their
report

You should also generate a section listing moderating assignments on the dashboard for each enrolment. This should be
similar to the marker_assignments() part of @app/templates/faculty/dashboard/submitter_card.html, but surface
information from the `ModeratorReport` and link to the moderator report form. Do not allow the moderator to view any
documents associated with the SubmissionReport, except by downloading the student's report via their report form.

The report form should include a card offering the student's report for download, matching what is on the
`MarkingReport` form @app/templates/faculty/marking_form.html. Also offer any attachments associated with the
`MarkingWorkflow`. Do not surface any attendance data. List the marking reports and feedback for each `MarkingReport`
associated with the out-of-tolerance `SubmitterReport`. This data is read-only. Include any feedback that has been added
by the marker. Clearly highlight the conflated grade assigned by each marker.

The form should include fields allowing the moderator to explicitly assign a moderated grade (not conflated, just
assigned numerically), and a justification as a text box.

After submission, persist these values in the `ModeratorReport` instance. The assigned grade should be copied to the
`SubmitterReport.grade` field if it is None. If it is not None, leave the existing value in place. This allows for the
return of multiple moderation reports.

If the grade is automatically copied into the `grade` field, set `grade_generated_by_id` to the moderator's id, and
attach a `grade_generator_timestamp` set to the current time. Move the `SubmitterReport` to the `READY_TO_SIGN_OFF`
stage.

If there is already an existing grade, set the `SubmitterReport` to the REQUIRES_CONVENOR_INTERVENTION state.

## TASK 7 - Surface moderation reports on the `SubmitterReport` inspector

Adjust the row formatter so that data from any submitted `MarkingReport` instances is displayed in a new column in the
table labelled "Reports". Show the name of each marker, whether the report has been submitted or is still awaited,
when the grade was submitted, and clearly highlight the grade assigned by each marker.

Adjust the row formatter so that data from any moderation reports is displayed in the "Reports" column. Visually
separatae these from the `MarkingReport` instances. Include an indition whether the `ModeratorReport` has been submitted
or is still awaited, when it was generated, the largest % value by which the `MarkingReport` instances disagree.
Clearly highlight the grade recommended by the moderator.

Provide an "Accept" button for each `ModeratorReport` that allows the convenor to accept the recommended grade from that
moderator. This should:

- copy the moderator's recommended grade into `SubmitterReport.grade`
- set `grade_generated_by_id` to the convenor
- attach a `grade_generated_timestamp` set to the current time
- move the `SubmitterReport` to the `READY_TO_SIGN_OFF` state.

## TASK 8

Write a summary of this lifecycle business logic into the `SubmitterReportWorkflowStates` class, so that it is
accessible for future agents and also human maintainers.