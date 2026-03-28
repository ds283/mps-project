## PREAMBLE

This task enables Celery callbacks after successful sending of an EmailWorkflowItem.

### TASK 1

Refactor the EmailWorkflowItem model to include a `callbacks` field. This model is defined in @app/models/emails.
The `callbacks` field be a large JSON object. It should serialize a list of callbacks, each of which is specified
by a dictionary with the following keys:

- `task`: The name of the Celery task to execute.
- `args`: A list of positional arguments to pass to the task.
- `kwargs`: A dictionary of keyword arguments to pass to the task.

Refactor EmailWorkflowItem.build_ to accept a list of callbacks in this format, which you should serialize into the
`callbacks` field using json.dumps().

### TASK 2

Refactor send_workflow_item() in @app/tasks/email_workflow_items.py to work through thist list of callbacks
once the email has been sent successfully and the corresponding EmailLog item has been constructed and persisted into
the database.

Construct a group of Celery tasks with names taken from the `task` field in each callback dictionary. Prepend the
primary key of the newly constructed EmailLog item to the positional arguments list `args`. Then build a Celery
signature for this task using the `args` and `kwargs` fields and add t to the Celery task group. See
the launch_scheduled_task() route in @app/admin/system.py for an example of how to do this.

### TASK 3

Refactor check_event_for_attendance_prompt() in @app/tasks/attendance.py to add a callback for
mark_attendance_prompt_sent(). mark_attendance_prompt_sent() should be refactored so that it accepts the primary
key of the EmailLog item as its first positional argument, rather than the existing "result_data" field.
mark_attendance_prompt_send() needs the event_id as a second positional argument, so you should add this
into the callback structure. There are no needed kwargs.