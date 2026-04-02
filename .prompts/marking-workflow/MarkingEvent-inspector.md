# Preamble

Implement the following routes and views, and build suitable Jinja2 templates to generate an attractively laid out user
interface using the same visual style as other elements in the application.

In this task, "convenor access privileges" means that the user is logged in and has the "root" role, or an "admin" role
and belongs to the same tenant as the project class, or has a "convenor" role for the project class, or has an "
external_examiner" or "exam_board" role and belongs to the same tenant as the project class. Refactor the
validate_is_convenor() function to apply these tenancy constraints if needed.

## TASK 1.

Working in @app/convenor, create a new file markingevent.py to hold convenor routes associated with MarkingEvent,
MarkingWorkflow, and their related models.

* Implement a view marking_events_inspector() that allows a user with suitable convenor access privileges to view
  MarkingEvent instances associated with closed SubmissionPeriodRecords (with field closed=True) that belong to the
  convenor's ProjectClass type.

* Create a new pill in the dashboard nav in @app/templates/dashboard/nav.html to link to the new view, with the title "
  Assessment archive". The pill should include a numeric label showing how many MarkingEvent instances are associated
  with the current convenor's ProjectClass.

* The view should implement a Datatables front end linked to an AJAX endpoint. The endpoint should use
  ServerSideSQLHandler to support searching, sorting, and pagination of MarkingEvent instances. It should format rows
  using a format handler defined in app/ajax. Look in app/ajax for other examples of row formatters.

* The view should display the following information, sensibly arranged into not too many columns:
    * SubmissionPeriodRecord.display_name
    * SubmissionPeriodRecord.start_date
    * SubmissionPeriodRecord.end_date
    * MarkingEvent.name
    * The names of any MarkingWorkflow associated with the MarkingEvent.
    * A dropdown menu with an otion allowing the user to inspect the MarkingWorkflow instances, linked to the view
      described in Task 2 below.

## TASK 2.

* Still in @app/convenor, create a view marking_workflow_inspector() that allows a user with suitable convenor access
  privileges to view the MarkingWorkflow instances associated with a MarkingEvent. This view will later be re-used to
  edit MarkingEvent instances associated with open SubmissionPeriodRecords, so it should _not_ enforce that the period
  is closed.

* The view should accept URL and text parameters that allow the user to return to the previous URL. Implement a UI for
  this, similar to that used for EmailWorkflow and EmailWorkflowItem inspectors in @app/site/views.py.

* The view should implement a Datatables front end linked to an AJAX endpoint. The endpoint should use
  ServerSideSQLHandler to support searching, sorting, and pagination of MarkingWorkflow instances. It should format rows
  using a format handler defined in app/ajax. Look in app/ajax for other examples of row formatters.

* The view should display the following information, sensibly arranged into not too many columns:
    * MarkingWorkflow.name
    * Details of the marking scheme attached via LiveMarkingScheme, if not None
    * Details of any attachments linked via the "attachments" relationship
    * The number of SubmitterReport instances linked to the workflow
    * The number of MarkingReport instances linked to the workflow
    * How many MarkingReport instances have had marking distributed, and how many do not
    * How many MarkingReport instances have feedback submitted, and how many do not
    * A dropdown menu with options allowing the user to inspect the SubmitterReport instances and MarkingReport
      instances associated with the workflow, linked to from Task 3 and Task 4 below.

## TASK 3.

* Create a view submitter_reports_inspector() that allows a user with suitable convenor access privileges to view the
  SubmitterReport instances associated with a MarkingWorkflow.

* The view should accept URL and text parameters that allow the user to return to the previous URL. Implement a UI for
  this, similar to that described above.

* The view should implement a Datatables front end linked to an AJAX endpoint. The endpoint should use
  ServerSideSQLHandler to support searching, sorting, and pagination of SubmitterReport instances. It should format rows
  using a format handler defined in app/ajax. Look in app/ajax for other examples of row formatters.

* The view should display the information contained on the SubmitterReport instance, sensibly laid out into columns and
  with an attractive and professional layout and style.

## TASK 4.

* Create a view marking_reports_inspector() that allows a user with suitable convenor access privileges to view the
  MarkingReport instances associated with a MarkingWorkflow.

* The view should accept URL and text parameters that allow the user to return to the previous URL. Implement a UI for
  this, similar to that described above.

* The view should implement a Datatables front end linked to an AJAX endpoint. The endpoint should use
  ServerSideSQLHandler to support searching, sorting, and pagination of MarkingReport instances. It should format rows
  using a format handler defined in app/ajax. Look in app/ajax for other examples of row formatters.

* The view should display the information contained on the MarkingReport instance, sensibly laid out into columns and
  with an attractive and professional layout and style.