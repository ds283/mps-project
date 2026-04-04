## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

This task builds out functionality for the `SubmitterReport` workflow states `READY_TO_SIGN_OFF` and `COMPLETED`.

In line with project policy, DO NOT generate Alembic migrations for changes of database schema. I will generate these
manually.

### TASK 1.

Please verify that the logic in advance_marking_workflow() and advance_submitter_report() can not advance the lifecycle
state of `SubmitterReport` past `REQUIRES_CONVENOR_INTERVENTION` if there is an outstanding Turnitin issue, requiring
attention, that has not been resolved.

### TASK 2. Database schema changes.

- Add a new `completed_by_id` field and `completed_timestamp` field to the `SubmitterReport` model. `completed_by_id`
  should be a FK linking to the `User` model. Create a `completed_by` SQLAlchemy relationship to this model.
  `completed_by_id` and `completed_timestamp` should be set whenever a `SubmitterReport` moves into the `COMPLETED`
  state. Previous values should be overwritten.

### TASK 3. Progression from `READY_TO_SIGN_OFF` to `COMPLETED`

- The workflow state advance logic should explicitly check the `SubmissionReport.grade` field before advancing any
  `SubmitterReport` to the `READY_TO_SIGN_OFF` or `COMPLETED` states. A `SubmitterReport` instance cannot enter either
  of these states if it does not have a properly assigned grade.
- Where `SubmitterReport` instances are in the `READY_TO_SIGN_OFF` state, they can be individually progressed to the
  `COMPLETED` state by convenor action. Please generate UI elements to offer this in the web interface, and suitable
  routes to implement it. Ensure that the change is logged with `log_db_commit()`, using the identity of the convenor,
  so that these events are attributable in the audit log.
    - when the `READY_TO_SIGN_OFF` -> `COMPLETED` transition is available, add an option to the drop-down "Actions" menu
      for that `SubmitterReport`
    - consider whether there is also space to add a direct action button in the DataTables row for that
      `SubmitterReport`
- Where **all** `SubmitterReport` instances are in the `READY_TO_SIGN_OFF` state, the UI should surface this information
  to the convenor as a call-to-action notification. This should be shown on the `SubmitterReport` inspector, and the
  `MarkingWorkflow` inspector. The notification should include an action button to progress all `SubmitterReport`
  instances to the `COMPLETED` state simultaneously. As above, ensure this action is logged with `log_db_commit()`.

In what follows, please remember that:

- "root" users can see and edit any `MarkingEvent`
- "admin" users should be able to see and edit only `MarkingEvent`s for project classes belonging to a tenant that they
  are subscribed to via the `User.tenants` relationship.

The semantics of the `COMPLETED` state are:

- When a `SubmitterReport` is in the `COMPLETED` state, all edit operations on it and its dependent `MarkingReport`s are
  disabled. This is true for all users, including those with "admin" or "root' roles. A `SubmitterReport` must be
  explcitly returned to the convenor for editing before any changes can be made.

Please

- Adjust all UI elements to reflect the semantics of the `COMPLETED` state. Menu options leading to edit operations
  should be disabled, and action buttons should be hidden.
- Where the user as an "admin" or "root" role, a UI element should be added for each `SubmitterReport` row in the
  `SubmitterReport` inspector that returns the `SubmitterReport` to the convenor for editing. Each action must be
  logged using `log_db_commit()` so that such events are attributable later (and timestamped).
- Where at least one `SubmitterReport` is in the `COMPLETED` state, a UI element should be added to the
  `MarkingWorkflow` inspector to return **all** items in the workflow to the convenor for editing. The UI element should
  only be offered to users with "admin" or "root" roles.
- Add visual elements to the user interface to highlight where `SubmitterReport`s are in the `COMPLETED` state.

### TASK 4. Conflation of target marks at `MarkingEvent` level

- Having **all** `MarkingWorkflows`s in a `MarkingEent` in the `COMPLETED` state is a critical precondition for
  activation of the conflation workflows described below. Let us say that a `MarkingWorkflow` itself is `COMPLETED` in
  this state. Please consider whether this state should be persisted in the database as a flag attached to the
  `MarkingWorkflow` model (e.g. labelled `completed`), and make a recommendation:
    - Pros: we do not have to inspect all `SubmitterEvent` instances to determine this state; it can be used easily in
      queries on `MarkingWorkflow` instances
    - Cons: `SubmitterReport` instances may drift out of sync with the flag. The state of the flag must be carefully
      managed when `SubmitterReport` instances move in and out of the `COMPLETED` state to ensure it does not become
      stale.
- When a `MarkingWorkflow` is in the `COMPLETED` state, this information should be surfaced to the convenor by a UI
  element on the `MarkingWorkflow` inspector, perhaps similar to the "State summary" on the `SubmitterReport` inspector.
- When **all** `MarkingWorkflow`s in `MarkingEvent` are complete, let us say that the `MarkingEvent` is itself
  **complete**. This should be surfaced to the covenor by a call-to-action notification displayed on the `MarkingEvent`
  inspector, and possibly also on the `MarkingWorkflow` inspector for that `MarkingEvent`. The notification should
  include an action button to calculate conflated target marks.
- Please consider whether **this** state should likewise be persisted in the database as a flag attached to the
  `MarkingEvent` model, and make a recommendation. The pros and cons are much the same as described above for persisting
  whether a `MarkingWorkflow` is in the `COMPLETED` state.

The semantics for calculation of the target marks are:

- Iterate through all `SubmissionRecord` instances associated with the `MarkingEvent`. Every such `SubmissionRecord`
  instance has correpsonding `SubmitterReport` instances in each `MarkingWorkflow`. At this point in the lifecycle,
  every one of these `SubmitterReport` instances should be in the `COMPLETED` state and has a calculated
  `SubmitterReport.grade`.
- For each `SubmssionRecord`, gather all the corresponding `SubmitterReport` instances. Build a dictionary that assigned
  the corresponding `SubmitterReport` grade to an identifier corresponding to the `key` field of the `MarkingWorkflow`,
  i.e., {"<MarkingWorkflow.key>": <grade for SubmitterReport in that workflow>, ...}.
- Now for each element defined in the `MarkingEvent.targets` field, evaluate the conflation rule corresponding to this
  target. Store the result in a dictionary {"target name": <evaluated conflation rule>, ...}.
- After evaluating all targets, persist the result in the database. To do this we will need a new model
  `ConflationReport`. This should have fields
    - `id` integer primary key
    - `marking_event_id` integer foreign key to `MarkingEvent`
    - `conflation_report` JSON field containing the result of the conflation rule evaluation.
    - 'generated_by_id`: FK to `User`
    - `generated_timestamp`: timestamp for the generation of this report
- also, add `generated_by` SQLAlchemy relationship to `User` determined by `generated_by_id`.
- Where available, the UI should display the result for each target a new column in the `MarkingEvent` inspector.
  If target values are not yet available, show "Not yet conflated".

The conflation workflow can be re-run multiple times, in which case the previous set of `ConflationReport` instances
should be discarded.

- If conflation fails for any `SubmissionRecord`, because it is not possible to find a corresponding `SubmitterReport`
  instance in each `MarkingWorkflow`, then the whole conflation workflow should fail, and all `ConflationReport`
  instances should be discarded. This prevents inconsistent results being generated.

Please consider whether the `ConflationReport` instances should be discarded whenever a `MarkingWorkflow` on which they
depend moves out of the `COMPLETED` state (because a constituent `SubmitterReport` has been returned to the convenor for
editing). In this case the target values are at risk of becoming stale and will need to be re-generated. Consider the
pros and cons of doing so, compared to simply adding a UI element to indicate that the target values may be out of
date.

### TASK 5. Propagation of target marks to `SubmissionRecord` instances

Once conflated target marks have been calculated, options should be surfaced to the convenor for handling certain
special targets:

- a target named "report": this target can be copied to the `SubmissionRecord.report_grade` field.
- a target named "supervisor: this target can be copied to the `SubmissionRecord.supervision_grade` field.

In addition, you should add a `SubmissionRecord.presentation_grade` field, with the same properties as `report_grade`
and `supervision_grade`. Adjust the project_tag() macro in @app/templates/convenor/submitters_macros.html to display
this grade, if `uses_presentations` is set for this ProjectClassConfig, alongside the report and supervisor grades.

Then:

- where the `MarkingEvent` omputes a target named "presentation": this target can be copied to the
  `SubmissionRecord.presentation_grade` field.

These options allow conflated marks from a MarkingEvent to be back-populated to the `SubmissionRecord`.

It is probably also necesasry to change the `grade_generated_id` and `grade_generated_timestamp` fields so that we have
one field for each type of grade, i.e. `report_generated_id`, `report_generated_timestamp`, etc., and corresponding
`grade_generated_by` SQLAlchemy relationships to `User` instances. These should be updated whenever a grade is
back-populated.

Implement suitable UI elements to allow the convenor to initiate the back population event. Please recommend a possible
layout.

### TASK n. Update documentation of lifecycle states

Update the comment giving a detailed description of the lifecycle states in the definition of the
`SubmitterReportWorkflowStates` class. This should document the lifecycle states in a way that can be read by a future
agent or human maintainer.

Please consider whether the comment block headed "# REQUIRES_CONVENOR_INTERVENTION: blocking state" also requires
updating.