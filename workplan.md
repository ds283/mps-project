# To do list

## Priority elements for Claude

* Refactor validator for marking scheme schema, which has changed and needs to be updated
* Allow convenors to see workflow log events that are associated with their project class.
* Update the Export to Excel option for workflow events to include student names. Convenors should only get events that
  are associated with their project class.
* Implement a journal for students
    - Entries are timestamped, linked to a specific academic year MainConfig, free-form HTML and are owned by the user
      who created them. They can optionally be associated with a project class.
    - Convenors and admin, root, office users can create ad hoc entries. Convenors can only see entries from themselves
      and other co-convenors on the same project class, or from admin users if they are explicitly marked as being
      associated with the project class.
    - Entries are automatically created for SubmittingStudent create/delete events, SelectingStudent create/delete
      events, CustomOffer create/accept/delete events. These should record the student's current academic year and
      programme at the time of the journal entry. Delete for SubmittingStudent, SelectingStudent should ask for a
      summary reason for deletion, which is included in the log.
    - Nicely formatted UI allowing entries to be searched, sorted, filtered by project class or academic year

## Medium term goals

* Implement UI for convenor to configure exemplar projects for each project class
* Implement UI to expose these exemplar projects to students and supervisors via the project hub
* Remove "faculty response" feedback from SubmissionRole et al, which has never been used

## Refactoring

* Remove morning_session, afternoon_session, talk_format from SubmissionPeriodRecord. These are properly properties of
  the PresentationAssessment (although need to think how they might vary by project class).
* Remove old marking and feedback fields from SubmissionRecord and SubmissionRole instances