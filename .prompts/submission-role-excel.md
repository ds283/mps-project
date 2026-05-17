## Summary

The refactoring described here introduces a suite of options to suport marker workload allocations during the
project assessment cycle.

There are existing action buttons on the convenor's submitter dashboard tab. This is rendered by the
`submitters()` route in `app/convenor/submitters.py`. The template is in
`app/templates/convenor/dashboard/submitters.html`. This already contains some action buttons:

- "Remove markers". Directs to `convenor.remove_markers()` in `app/convenor/marking_feedback.py`
- "Populate markers". Directs to `convenor.populate_markers()` in `app/convenor/marking_feedback.py`

### Changes to scope of the "Remove markers" and "Populate markers" buttons

Currently, these buttons only work for the specific `ProjectClass` that is in scope on the convenor's dashboard.

However, (re-)allocation of markers is a global resource commitment. It shuold be balanced across different project
classes.

Both buttons should redirect to a view allowing the user to select a range of `ProjectClass` instances to which
the action is applied.

For the "Remove markers" view, the user should be offered a list of project classes that are available to be scoped:

- for a user with the "admin" or "root" roles, the list should include all project classes belonging to the `Tenant`
  owning the project class in scope on the dashboard
- for a user who is just a convenor (does not hold elevated "admin" or "root" roles), it should offer a list of project
  classes where the user holds convenor roles

When the user confirms, the markers for all these project classes should be removed.

For the "Populate markers" view, the user should be offered the same list of project classes, scoped by role.

### Changes to the "Populate markers" functionality

First, currently, the underlying Celery workflow `populate_markers` in `app/tasks/matching.py` does not remove markers
before re-populating them. However, it should do so.

Second, the `populate_markers` workflow does not try to do workload balancing in the same way as the main
`_create_PuLP_problem` function that performs student project allocation, supervisor allocation, and marker allocation
all in one step.

In the app, the unit of workload allocation is the CAT.

The `populate_markers` task should offer workload balancing in two modes:

#### Mode 1

The "Populate markers" view should also offer an option to upload a spreadsheet (in CSV or Excel format).
This sheet should be uploaded as an expiring `TemporaryAsset` in the same way as the `batch_upload_students`
and `batch_upload_faculty` views in `app/manage_users/views.py`.

This should have the following scheme:

- either: 'Last name', 'First name' columns giving the last and first names of a faculty member, or simple 'Name' field
  giving the name in <last name>, <first name> format
- a 'Total CATS' column.

This gives an assignment of faculty member -> existing CATS loading

#### Mode 2

No spreadsheet is uploaded. Instead, the system builds an existing CATS loading by introspecting all current
`SubmissionRole` records for each faculty member in the active cycle. It should calculate this CATS load in the
same way as the `workload` view in `app/reports/views.py` (or rather the AJAX row formatter that backs the table
rendered by this view).

#### Inclusion of workload data in the marker assignment

For each faculty member, the CATS load obtained by Mode 1 or Mode 2 should set the baseline. New variables will be
needed to compute the CATS load for a given assignment of variable in the integer linear programming problem.
The optimizer should try to keep the overall highest CATS load as small as possible, and also minimize the difference
between faculty members with the highest and lowest CATS load. This is intended to push marker towards faculty members
that are lower on the workload allocation table.

### Export allocation as Excel document

On the convenor submitters report pane, add a button to the right-hand side of the `card-title` title bar of the
`card` div that holds the table. This should offer export of current assignments associated with submission roles.

The button should activate a Celery background task that builds an Excel document, uploads it to an object bucket
as a persisted asset, generates a `GeneratedAsset` record for it, and links this into the user's download centre.
See the `app/tasks/ai_dashboard_export.py` file for an explicit example where exactly this workflow is implemented.

For each `ProjectClass` in scope for the current user (computed as described above: for 'admin' and 'root' users,
all project classes in the current tenant; for a convenor-only user, all project classes for which the user holds
convenor roles), the Excel document should conatain a worksheet listing all the `SubmissionRoles`.
The format should be:

- `faculty_last_name`: faculty member last name
- `faculty_first_name`: faculty member first name
- `faculty_full_name`: faculty member full name
- `project_class_name`: abbreviation for project class (redundant with table name but helpful if rows are later merged)
- `role`: name of role (responsible supervisor, supervisor, marking, moderating, ...)
- `role_type`: both "responsible supervisor" and "supervisors" could as a "supervisor" role; other vocabulary unchanged
  from `role`
- `student_last_name`: assigned student last name
- `student_first_name`: assigned student first name
- `project_name`: assigned project name

There should also be a summary worksheet that lists:

- `faculty_last_name`: faculty member last name
- `faculty_first_name`: faculty member first name
- `faculty_full_name`: faculty member full name
- `total_supervising`: total number of supervisory roles
- `total_marking`: total number of marking roles
- `total_moderating`: total number of moderating roles
- `total_CATS`: total CATS score, computed as for the `workload` report view

Prefer not to duplicate code. Extract a helper method from `workload` to compute the necessary CATS scores.