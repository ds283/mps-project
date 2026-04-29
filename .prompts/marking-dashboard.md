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

Compare to @app/templates/dashboards/ai_dashboard.html for visual styling and design vocabulary.

Place generated view functions in app/dashboards/views.py.
Place generated tempates in app/templates/dashboards/.

### TASK 1. Summary data dashboard

Design a summary data dashboard that includes a row or panel for each `MarkingEvent` within the user's scope. The
dashboard should include key summary data about the `MarkingWorkflow` instances within the `MarkingEvent`, and also the
status of the `MarkingEvent` container itself.

This is intended to be a read-only data dashboard. You will need to create a new "card" on the overview grid
app/templates/dashboards/overview.html. This should be in a visual style matching the existing card for the
AI dashboard. Do not duplicate code. Implement a Jinja2 macro that abstracts the task of building the UI components
for the card.

The dashboard itself should show all current `MarkingEvent` instances together with the project class they are part
of and the name of the convenor. The convenor name should be a mailto: link targeting their email address.

Organize the list by `Tenant`, then by `ProjectClass`, then by `SubmissionPeriodRecord`. so that all `MarkingEvent`s for
a single class are grouped together. Each `MarkingEvent` should be identified by name. Clearly highlight the deadline
and the current workflow state, which are critical data.]

To prevent the dashboard becoming too long, provide a filter to narrow the scope to a single `Tenant` or a single
`ProjectClass`.

For each `MarkingWorkflow` instance belonging to the `MarkingEvent`, you should surface the following information
as a concise overview:

- The deadline associated with this workflow and the current workflow state (key data)
- The role being targeted
- The marking scheme being used
- The total number of `SubmitterReport` instances
- The total number of `MarkingReport` instances

The main dashboard component for each `MarkingWorkflow` should be a set of metric tiles that describe the status
and health of the workflow. "Health indicators" is a good language to use here. Use the `dashboard_tile` metric
defined in @app/templates/dashboard_widgets.html to lay out each tile.

- Distribution state: Percentage distributed (healthy), percentage awaiting distrbution (unhealthy)
- Marking reports: Percentage submitted (healthy), percentage awaiting submission (unhealthy)
- Moderation: the number of `SubmitterReport` instances where a moderation event has been triggered.
- Feedback: of the marking reports submitted, what percentage have feedback (healthy), or are missing feedback (
  unhealthy)
- `SubmitterReport` workflow states: percentage in `NOT_READY`, percentage in `REQUIRES_CONVENOR_INTERVENTION`,
  percentage in `REQUIRES_MODERATOR_ASSIGNED` states (broken out separately), which unhealthy; remaining percentage,
  which are proceeding normally.
- The standard deviation and coefficient of variation (=standard deviation divided by the mean) of grades, computed
  for `SubmitterReport` instances that have two or more `MarkingReport` instances attached.

This dashboard should self-update. Please consider options to implement this and make a recommendation.

### TASK 2. Detailed marks register

For each `MarkingEvent` instance, provide a button orlink to access a marks register. This should be a relatively
COMPACT spreadsheet-like view of the current state of the `MarkingWorkflow` instances. It should scroll horizontally
if needed; it does not need to resize to fit within the current viewport. To prevent the view becoming too long it
may need to be paginated and it would be helpful to provide an option to filter by student name. This suggests a
possible DataTables approach, but you can evaluate alternative implementation strategies.

The register view should aggregate all reports for a single student across all `MarkingWorkflow` instances
belonging to the `MarkingEvent`. In particular, this means:

- a possible `ConflationReport` instance belonging to the parent `MarkingEvent`
- one `SubmitterReport` instance per `MarkingWorkflow`
- a number of `MarkingReport` instances per `SubmitterReport`.

The register "spreadsheet" view should be organized as follows. Do not draw a literal grid like a spreadsheet;
the term "spreadsheet" here is just used to indicate a cell layout.

- The first column should give the student name. Include the candidate number if present.
- The second column should reflect that status of a `ConflationReport` if present. If absent, show "Not conflated".
  If present, including "healthy"/"unhealthy" indicators for:
    - conflation report
    - feedback generated
    - feedback sent
- After this, organize columns into groups, with one group for each `MarkingWorkflow`. Add a header for each
  group of columns to show the name of the `MarkingWorkflow`.
    - The first column in each group should reflect the status of the `SubmitterReport` for this `MarkingWorkflow`.
      Use a SUBTLE colour scheme reflecting the current workflow status of the `SubmitterReport`. If a grade is
      present, display it. Include a warning indicator for `out_of_tolerance`. Include a status indicator if
      a moderator report has been accepted.

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