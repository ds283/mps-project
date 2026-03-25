# To do list

* Implement UI for convenor to configure exemplar projects for each project class
* Implement UI to expose these exemplar projects to the user
* Remove "faculty response" feedback, which has never been used

## Refactoring

* Remove morning_session, afternoon_session, talk_format from SubmissionPeriodRecord. These are properly properties of
  the PresentationAssessment (although need to think how they might vary by project class).
* Remove old marking and feedback fields from SubmissionRecord and SubmissionRole instances