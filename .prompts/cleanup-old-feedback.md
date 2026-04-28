Please explore the uses of old-code methods associated with `SubmissionPeriodRecord`, which we want to eliminate

- `SubmissionPeriod.is_feedback_open`
- `SubmissionPeriod.number_submitters_feedback_pushed`
- `SubmissionPeriod.number_submitters_feedback_not_pushed`
- `SubmissionPeriod.number_submitters_feedback_not_generated`
- `SubmissionPeriod._number_submitters_with_role_feedback`
- `SubmissionPeriod.number_submitters_marker_feedback`
- `SubmissionPeriod.number_submitters_with_presentation_feedback`

We also want to remove the following methods on `SubmissionRecord`

- `SubmissionRecord._role_feedback_valid`
- `SubmissionRecord._role_feedback_submitted`
- `SubmissionRecord.is_supervisor_feedback_valid`
- `SubmissionRecord.is_marker_feedback_valid`
- `SubmissionRecord.is_supervisor_feedback_submitted`
- `SubmissionRecord.is_marker_feedback_submitter`
- `SubmissionRecord.is_presentation_assessor_valid`
- `SubmissionRecord.presentation_assessor_submitted`
- `SubmissionRecord.is_feedback_valid`
- `SubmissionRecord._feedback_state`
- `SubmissionRecord.supervisor_feedback_state`
- `SubmissionRecord.marker_feedback_state`
- `SubmissionRecord.presentation_feedback_late`
- `SubmissionRecord.presentation_feedback_state`
- `SubmissionRecord.supervisor_response_State`
- `SubmissionRecord.feedback_submitted`
- `SubmissionRecord.has_feedback_to_push`
- `SubmissionRecord.number_presentation_feedback`
- `SubmissionRecord.number_submitted_presentation_feedback`
- `SubmissionRecord.can_assign_feedback`

NOTE that the following functions have been updated for the new workflow and MUST be kept

- `SubmissionRecord.has_feedback`

We want to remove the following fields on `SubmissionRecord`

- `SubmissionRecord.feedback_generated`
- `SubmissionRecord.feedback_reports` (and its secondary association table `submission_record_to_feedback_report`)
- `SubmissionRecord.feedback_sent`
- `SubmissionRecord.feedback_push_id`
- `SubmissionRecord.feedback_push_by`
- `SubmissionRecord.feedback_push_timestamp`

We want to remove the following methods on `SubmissionRole`

- `SubmissionRole.feedback_state`
- `SubmissionRole._supervisor_feedback_state`
- `SubmissionRole._marker_feedback_state`
- `SubmissionRole._moderator_feedback_state`
- `SubmissionRole._presentation_assessor_feedback_state`
- `SubmissionRole.feedback_valid`
- `SubmissionRole._internal_feedback_state`
- `SubmissionRole.response_state`
- `SubmissionRole._supervisor_response_state`
- `SubmissionRole.response_valid`

We want to remove the following fields on `SubmissionRole`

- `SubmissionRole.positive_feedback`
- `SubmissionRole.improvements_feedback`
- `SubmissionRole.submitted_feedback`
- `SubmissionRole.feedback_timestamp`
- `SubmissionRole.acknowledge_student`
- `SubmissionRole.response`
- `SubmissionRole.submitted_response`
- `SubmissionRole.response_timestamp`
- `SubmissionRole.feedback_sent`
- `SubmissionRole.feedback_push_id`
- `SubmissionRole.feedback_push_by`
- `SubmissionRole.feedback_push_timestamp`