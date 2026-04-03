## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

This task involves design and implementation of a marking dashboard to provide summary-level information to project
class convenors, "admin"/"root" level users, and external stakeholders such as management, exam board members (with
the "exam_board" role) and external examiners (with the "external") role.

The dashboard should give a visual overview of the state of all `MarkingEvent` instances+workflows within the scope of
the user:

- convenors can inspect `MarkingEvent` instances for any project classes that they convene or co-conveners
- "admin" level users can inspect all `MarkingEvent` instances for all project classes belonging to tenants they are
  associated with
- "root" level users can inspect all `MarkingEvent` instances globally
- currently the "exam_board" and "external" roles are not fully implemented. Users with the "exam_board" role would be
  able to inspect `MarkingEvent` instances for all project classes belonging to a tenant they are associated with. Users
  with the "external" role would be associated to specific project classes, like convenors, and would be able to inspect
  `MarkingEvent` instances for only those project classes.

### TASK 1. Summary data dashboard

Design a summary data dashboard that includes a row or panel for each `MarkingEvent` within the user's scope. The
dashboard should include key summary data about the `MarkingWorkflow` instances within the `MarkingEvent`, and also the
status of the `MarkingEvent` container itself.

At least initially, this is intended to be a ready-only data dashboard.

For each constituent `MarkingWorkflow` the dashboard should show metrics, preferably in visual form (e.g., using the
Bokeh
library that is already part of the project):

- the distribution state of `MarkingReport` instances attached to the workdlow
- the number of submitted `MarkingReport` instances, and the number of instances that are still awaiting submission
- the number of `SubmitterReport` instances in each workflow state. All states are useful, but it is critical to clearly
  highlight the `NOT_READY`, `REQUIRES_CONVENOR_INTERVENTION` and `REQURES_MODERATOR_ASSIGNED` states.
- the number of `SubmitterReport` instances where a moderation event has been triggered
- statistics on the typical spread of assigned grades where there are multiple `MarkingReport` instances attached to a
  single `SubmitterReport` instance in a workflow.

Organize the list by `Tenant`, then by `ProjectClass`, then by `SubmissionPeriodRecord`. To prevent the dashboard
becoming too long it may be necessary to provide a filter to narrow the scope to a single `Tenant` or a single
`ProjectClass`.

Currently, the app is built as a Flask app that builds pages in the backend and serves them as static HTML to the
browser. There are some small JavaScript components in the front end, mostly DataTables instances that consume AJAX
endpoints.

Ideally, this dashboard (and the marks register described in Task 2 below) would self-update. Please consider options
for doing so, and make a recommendation. It is possible to deploy some type of JavaScript-based front end framework, but
please consider the costs and benefits of doing so. The app is unlikely to be rebuilt based on a front end library
because there is no compelling business case for doing so.

### TASK 2. Detailed marks register

For each `MarkingEvent` instance, provide a means to access a register (i.e. COMPACT table view, scrolling, not
DataTables filtered) of all `MarkingWorkflows`.

- for each `MarkingWorkflow`, include a row for each `SubmitterReport`. Colour code by the workflow state of this
  `SubmitterReport` using a sensible system. Please ensure that the colour coding can easily be changed later.
- the left-hand side of each row should be a "tile" highlighting the assigned grade where it exists and include a
  compact text label for the current workflow state
- show a clear label to indicate whether a moderation event was triggered for this `SubmitterReport`
- working across the row, include further "tiles' for each `MarkingReport` and `ModeratorReport` instances attached to
  this `SubmitterReport`. Coluor code to highlight the submisison/sign-off state of each report. Highlight the assigned
  grade where it exists.
- provide a metric to show the maximum discrepancy between markers for this `SubmitteReport`

### TASK 3. Allow Excel export

Include a button allowing an Excel report to be created, with columns containing the same data shown in Task 2.

- Each `MarkingEvent` maps to UP TO two separate worksheets within the Excel report. The first sheet should contain rows
  for each generated `ConflationReport` belonging to the `MarkingEvent`. Include columns giving the conflated mark for
  each target specfified in `MarkingEvent.targets` JSON structure, the identity of the user who performed the
  conflation, and the timestmap. Also include columns summarizing the final `SubmitterReport.grade` calculated in each
  constituent `MarkingWorkflow`. Only include this sheet if there are `ConflationReport` instances for this
  `MarkingEvent`.
- Second, include a second sheet summarizing the state of the `MarkingWorkflow` instances. Collect all `MarkingWorkflow`
  instances for the same `MarkingEvent` on a single worksheet, but ensure they are clearly separate visually. After
  listing the student name, a column should give the `SubmitterReport.grade` calculated for this `MarkingWorkflow`.
  Also include the identity of the user who generated the grade and the generation timestamp, and the timestamp for when
  the `SubmitterReport` entered the `COMPLETED` workflow state.
- Include subsequent columns for each `MarkingReport` instance, labelled `assessor1_grade`, `assessor1_name`, etc, and
  `moderator1_grade`, `moderator1_name`. Include columns for the submission timestamp, the user who signed off on the
  report, and the sign-off timestamp.
- The Excel report should be generated by a background Celery workflow.
- Look at generate_excel_matching_report() in @app/tasks/matching.py for an example of how Excel reports have been
  generated using Pandas.
- When generated, the report should be persisted as a `GeneratedAsset` and uploaded made available in the User's
  "Download Centre". Upload to the `PROJECT_BUCKET` bucket.
- Ensure that you use the appropriate `ObjectStore` and `AssetUploadManager` to handle deposition of the final report in
  the object bucket.