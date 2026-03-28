# To do list

## Priority elements for Claude

## Medium term goals

* Implement UI for convenor to configure exemplar projects for each project class
* Implement UI to expose these exemplar projects to students and supervisors via the project hub
* Remove "faculty response" feedback from SubmissionRole et al, which has never been used

## Refactoring

* Remove morning_session, afternoon_session, talk_format from SubmissionPeriodRecord. These are properly properties of
  the PresentationAssessment (although need to think how they might vary by project class).
* Remove old marking and feedback fields from SubmissionRecord and SubmissionRole instances