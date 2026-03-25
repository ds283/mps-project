## Setup

Plan a function to implement to following complicated database migration.

The objective is to migrate from the current structure, where grades and feedback are stored directly on SubmissionRole
instances, to a new framework based on MarkingEvent, MarkingWorkflow, SubmitterReport, and MarkingReport.

This function should be inserted in @file:initdb.py and should be called from @file:serve.py inside the "with
app.app_context()" just before the WSGI server is run.

## Migration steps

For each closed SubmissionPeriodRecord (that is, has the "closed" field set to True), carry out the following steps.

* If this SubmissionPeriodRecord is marked as "has_presentation" and the "has_deployed_schedule" property evaluates to
  True, insert a FIRST MarkingEvent instance linked to this SubmissionPeriodRecord with name "Presentation grading".
  Mark this MarkingEvent as closed=True.

    - Insert a single MarkingWorkflow linked to this new MarkingEvent with name "Presentation grading" and scheme_id set
      to None.

    - For all SubmissionRecord instances belonging to the SubmissionPeriodRecord, add SubmitterReport instances linked
      to this FIRST MarkingWorkflow. Set grade = 0.0, signed_off_id = None, feedback_sent=False, feedback_push_id=None,
      feedback_push_timestamp=None.

    - For all SubmissionRole instances attached to this SubmissionRecord (and hence the new SubmitterReport) with role =
      ROLE_PRESENTATION_ASSESSOR, add MarkingReport instances linked to the SubmissionRole and the SubmitterReport. Set
      report=None, distributed=None, report_submitted=False, signed_off_id=None, signed_off_timestamp=None, grade=None,
      feedback_positive=None, feedback_improvement=None, feedback_submitted=False, feedback_timestamp=None

* Now we begin a new step. If one does not already exist, insert a SECOND MarkingEvent instance linked to this
  SubmissionPeriodRecord, and with name matching the display_name of the SubmissionPeriodRecord. Mark this MarkingEvent
  as closed=True.

* If the number_markers field of the SubmissionPeriodRecord is 1, proceed as follows:

    - Insert a SINGLE MarkingWorkflow linked to this new MarkingEvent with name "Report grading" and scheme_id set to
      None.

    - For all SubmissionRecord instances belonging to the SubmissionPeriodRecord, add SubmitterReport instances linked
      to this SINGLE MarkingWorkflow.

    - For all SubmissionRole instances attached to this SubmissionRecord/SubmitterReport with role = ROLE_SUPERVISOR,
      ROLE_RESPONSIBLE_SUPERVISOR, or ROLE_MARKER, add MarkingReport instances linked to the SubmissionRole and the
      SubmitterReport.

    - Check that the SubmissionRole.grade field is None in each case and raise an exception if not. Set the
      MarkingReport.grade field to be None. Set the SubmitterReport.grade field to be None.

    - For the SubmissionRole instances of any role type, copy SubmissionRole.positive_feedback ->
      MarkingReport.feedback_positive, SubmissionRole.improvement_feedback -> MarkingReport.feedback_improvement,
      SubmissionRole.submitted_feedback -> MarkingReport.feedback_submitted, SubmissionRole.feedback_timestamp ->
      MarkingReport.feedback_timestamp.

    - Copy the SubmissionRecord.grade_generated_id to the SubmitterReport.grade_generated_id field, and the
      SubmissionRecord.grade_generated_timestamp to the SubmitterReport.grade_generated_timestamp field. Copy the
      elements in the SubmissionRecord.feedback_reports list to the SubmitterReport.feedback_reports field. Also copy
      the feedback_sent, feedback_push_id, and feedback_push_timestamp fields.

* If the number_markers field of the SubmissionPeriodRecord is 2, proceed as follows:

    - Insert a FIRST MarkingWorkflow likned to this MarkingEvent with name "Report grading" and scheme_id set to None.

    - For all SubmissionRecord instances belonging to the SubmissionPeriodRecord, add SubmitterReport instances linked
      to this FIRST MarkingWorkflow.

    - For all SubmissionRole instances attached to this SubmissionRecord/SubmitterReport with role = ROLE_MARKER, add
      MarkingReport instances linked to the SubmissionRole and SubmitterReport. Copy the SubmissionRole.grade field to
      the MarkingReport.grade field. Copy the SubmissionRecord.report_grade field to the SubmitterReport.grade field.

    - Also copy SubmissionRole.positive_feedback -> MarkingReport.feedback_positive,
      SubmissionRole.improvement_feedback -> MarkingReport.feedback_improvement, SubmissionRole.submitted_feedback ->
      MarkingReport.feedback_submitted, SubmissionRole.feedback_timestamp -> MarkingReport.feedback_timestamp.

    - Copy the SubmissionRecord.grade_generated_id to the SubmitterReport.grade_generated_id field, and the
      SubmissionRecord.grade_generated_timestamp to the SubmitterReport.grade_generated_timestamp field. Copy the
      elements in the SubmissionRecord.feedback_reports list to the SubmitterReport.feedback_reports field. Also copy
      the feedback_sent, feedback_push_id, and feedback_push_timestamp fields.

    - Insert a SECOND MarkingWorkflow linked to this MarkingEvent with the name "Supervisor observations" and scheme_id
      set to None.

    - For all SubmissionRecord instances belonging to the SubmissionPeriodRecord, add SubmitterReport instances linked
      to this SECOND MarkingWorkflow.

    - For all SubmissionRole instances attached to this SubmissionRecord/SubmitterReport with role = ROLE_SUPERVISOR or
      ROLE_RESPONSIBLE_SUPERVISOR, add MarkingReport instances linked to the SubmissionRole and SubmitterReport. Copy
      the SubmissionRole.grade field to the MarkingReport.grade field. Copy the SubmissionRecord.supervision_grade field
      to the SubmitterReport.grade field.

    - Also copy SubmissionRole.positive_feedback -> MarkingReport.feedback_positive,
      SubmissionRole.improvement_feedback -> MarkingReport.feedback_improvement, SubmissionRole.submitted_feedback ->
      MarkingReport.feedback_submitted, SubmissionRole.feedback_timestamp -> MarkingReport.feedback_timestamp.

    - Copy the SubmissionRecord.grade_generated_id to the SubmitterReport.grade_generated_id field, and the
      SubmissionRecord.grade_generated_timestamp to the SubmitterReport.grade_generated_timestamp field. Set the
      SubmissionRecord.feedback_reports list to be empty. Also copy the feedback_sent, feedback_push_id, and
      feedback_push_timestamp fields.

MAKE SURE that ALL modifications are idempotent, so that this migration can be run multiple times without multiple
redundant records being inserted.