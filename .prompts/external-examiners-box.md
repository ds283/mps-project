## Summary

The codebase already features functionality to hold a Box OAuth token allowing upload.
The next task is to design and implement a feature to upload assets and marking data
from a single `SubmissionPeriodRecord` to a Box folder for review by the exam board
and external examiners. In particular, we will need to upload student reports, and
compile an Excel spreadsheet that aggregates information in the `MarkingWorkflow`
instances attached to the `SubmissionPeriodRecord`.

### Design principles

- Student names must not leak. Marking is done blind. Students must ALWAYS be identified
  by their exam numbers, available from `StudentData.exam_number`
- Marker names must not leak. Markers should be anonymized when marks are scrutinized
  by the exam board or external examiners.

## STEP 1: User interface

The upload task should be initiated from the `MarkingEvent` inspector for a single
submission period, `app/templates/convenor/markingevent/period_marking_events_inspector.html`.
Place a new action button next to the existing "Add marking event..." button, using the
same "ghost" styling. The label for this action button should be "Export assets to Box...".

When clicked, the user should be redirected to an intermediate page. This should allow the user
to specify:

- the user whose Box credentials will be used during the upload. This should be a dropdown
  selector (styled with `select2`), with options drawn from the current project convenor and
  any co-convenors who have linked their accounts to Box. If no convenors or co-convenors with
  a Box linking are available, export cannot proceed. Display a warning banner and provide
  only a "Cancel" action button allowing the user to return to the `MarkingEvent` inspector.
- the Box folder id for the target folder. This is always an integer. Box does not publish other
  validation rules.

Include a "Cancel" button to return the user to the `MarkingEvent` inspector. If a linked Box
account is in scope, include an "Export..." action button to launch the export task.
It should validate that the Box user account field is set and a suitable Box folder has been
specified. Use a WTForms implementation with CSRF protection as specified in the project rules.

## STEP 2. The export task

The "Export..." button should dispatch a Celery task that will perform the export
and then return the user to the `MarkingEvent` inspector.
The task should be implemented in `app/tasks/box_export_period_marking.py`.

The Celery task should be implemented using the usual `TeskRecord` pattern that allows updates
to be pushed to the user in the web interface.

### STEP 2a. Build a set of `SubmissionRecord` instances that are in scope.

This set is determined by inspecting all the `MarkingWorkflow` instances associated with
`MarkingEvent`s attached to the `SubmissionPeriodRecord`. If the `SubmitterReport` for a
`SubmissionPeriodRecord` is in the `DROPPED` state in ALL `MarkingWorkflow`s then it is
out-of-scope and can be excluded. Otherwise, the `SubmissionRecord` should be kept in-scope,
even if it is marked `DROPPED` in some `MarkingWorkflow`s.

### STEP 2b. Perform a idempotent upsert upload of all reports to the Box folder

If it does not exist, create a "Reports" subfolder in the Box target folder. This will be the
destination for upload of the reports for each `SubmissionRecord` in scope.

For each `SubmissionRecord`, inspect the `processed_report` asset and upload it to the "Reports"
subfolder. It should have leafname "Candidate_<exam_number>", where <exam_number> is the numerical
exam number obtained from `StudentData.exam_number`. Retain the same file extension recorded in the
`GeneratedAsset` record.

If `processed_report` is null but `report` is not, upload the `report` asset to the "Reports"
subfolder instead. Keep a record of whether it was possible to upload a report. You will also need
to generate a direct link to the file, to embed in the associated Excel spreadsheet.

Before uploading anything, use the Box SDK to check whether a file with that name exists. If it does,
upload a replacement version rather than attempting a fresh upload. This will create a new version
in Box's versioning system.

### STEP 2c. Build a master Excel sheet containing marking details

Now build an Excel spreadsheet according to the following recipe.

#### Column Group 1

Each row should corresopnd to a `SubmissionRecord` in scope. Write the rows out in order of ascending
exam number, For each row, the header column should the student's exam number. The column should simply
contain a number, nothing else, so that it can be unambiguously sorted. The column name should be "Candidate number".

The second column should be titled "Box link". If a file could be uploaded, include a direct URL linking
to it. Otherwise, leave this column blank.

#### Column Group 2

The next columns should include details extracted from the language analysis pipeline:

- Column title "Pages", number of pages in report document
- Column title "Words", number of STUDENT-DECLARED words in report document

#### Column Group 3

The next columns relate to the Turnitin scores:

- Column title "Turnitin score", gives the overall Turnitin similarity score, if present
- Column title "Turnitin flag", "Yes"/"No" boolean flag correspond to risk flag
- Column title "Turnitin resolved", whether the risk flag was resolved
- Column title "Turnitin comment", convenor annotation on resolved flag, if present

#### `ConflationReport` column group

Reserve a number of columns, one for each target recorded by the `ConflationReport` pipeline.
For each `SubmissionRecord`, inspect all its associated `ConflationReport` instances and write
the values into the appropriate columns. Assign the target label to the column name.

#### `MarkingWorkflow` column groups

Next, create a Column Group for each `MarkingWorkflow` in scope. Each column in this group has a nameprefix
"<key>-", where <key> is the `MarkingWorkflow.key` attribute.

Reserve enough columns to account for all the marker and moderator reports columns described below.

`MarkingReport` columns

Iterate through each `MarkingReport` instance attached to the `SubmitterReport` in this `MarkingWorkflow`
that is attached to the `SubmissionRecord` for the row. Label successive reports `marker-A`, `marker-B`, and so on.
For each `MarkingReport`, write out its grade

- Column name: "<key>-marker-<N>-grade", corresponding grade value

`ModeratorReport` columns

If the mark scheme for this `MarkingWorkflow` has `uses_tolerance` set, write out a column

- "<key>-max-marking-difference", max - min marks in this workflow
- "<key>-tolerance-trigger", whether this student was marked out-of-tolerance in this workflow

Then, iterate through each `ModeratorReport`. For each `ModeratorReport`, write out:

- Column name: "<key>-moderator-<N>-grade"
- Column name: "<key>-moderator-<N>-comment"

#### Excel sheet format

Add a header row with the column names. Format this as a header row, with a slightly darker grey background.
Format the first column (candidate number) as a header column, also with a slightly darker grey background.
If you can do so, mark this row and column as "frozen".

Fill the cells belonging to each Column Group with a subtle background tint. This should only be subtle.
Pick three or four contrasting colours and cycle.

Once you have constructed the Excel spreadsheet, uplaod it to the target Box folder. Use the same upsert semantics,
so that a new verison will be generated if the file already exists. The filename should be
"marking-report-<pclass name>-<period name>-<timestamp>.xlsx"

For <pclass name>, use `ProjectClass.abbreviation` or `ProjectClassConfig.abbreviation`. For <period name>,
use `SubmissionPeriodRecord.display_name`. Normalize the resulting filename so that any illegal characters
are replaced with underscores.

### Error behaviour

If the user's Box OAuth token has expired, report this to the user by posting a `Notification` directing them
to refresh it. Include a suitable link to the necessary page.

Provide suitable updates to the user via the `TaskRecord` notification mechanism, as the Celery task proceeds.
Issue a notification when the task completes.