Implement the following. It is a large refactoring. Write a plan file that can be committed to the repository and
updated as you work, so that state is not lost.

TASK 1.
Implement database models to support a workflow log. We require a model that will capture a timestamp, the route or
Celery task that is responsible for the event, a link to any logged-in user (represented by a User model) who initiated
the event, and a link to any ProjectClass instance (of group of ProjectClass instances) that can be identified with the
event.

TASK 2.
Estimate the typical size of such a workflow log. The physical space needed to store it as a database should be bounded
by about 50 Mb. Estimate how many rows can be retained.

TASK 3.
Implement a periodic Celery task to prune the workflow log to an arbitrary number of rows, but using your estimate from
TASK 2 as the default.

TASK 4.
Plan how to push entries to the workflow log. Each write to the database comes from a db.session.commit(). Can this be
replaced by a wrapper function that would capture details needed for the log and then perform the commit? The wrapper
function should capture a brief human-readable summary of what event has taken place, using the names of any students (
linked from SubmittingStudent, SelectingStudent, SubmissionRecord, StudentData, SubmitterReport instances) or faculty (
linked from SubmissionRole, FacultyData instaces) or other users (represented by User) models who are available in the
context. If there is a ProjectClass or ProjectClassConfig instance in the context, it should use this to determine the
project classes (or group of classes) to which the transaction applies. It should also capture the name of the route or
Celery task that is peforming the db.session.commit(), and write this (with a datestamp) into the workflow log.

TASK 5.
Plan how to implement this refactoring. It may take a long time and require several sessions with the agent, so state
will need to be written to a plan file.

TASK 6.
Implement a new route allowing the workflow log to be inspected. It should use a Datatables based front end, and
ServerSideSQLHandler to handle searching, sorting, and pagination. It should include columns for the user initiating the
task, route or Celery task, project classes, the datestamp, and the human readable summary of the event. It should allow
filtering by project class or tenant via parameters passed in the request; see eg. @app/reports/workload.py for example
of how this is done and the UI markup. Keep the visual style consistent with the rest of the application.

TASK 7.
Implement a new route allowing the workflow log to be exported as a CSV file or Excel spreadsheet. Link to this route
via a button on the Inspector page from Task 6. The CSV file or Excel spreadsheet should be stored as a GeneratedAsset
and an entry inserted into the user's Download Centre so that it can be downloaded.

TASK 8.
Create a new menu entry on the "Site management..." menu allowing access to the workflow log for users with "root"
permissions.