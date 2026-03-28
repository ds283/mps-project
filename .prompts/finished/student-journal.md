## PREAMBLE

This task implements a persistent journal associated with students, allowing the reason for decisions to be recorded.
It will also record significant events such as the creation or deletion of SubmittingStudent or SelectingStudent
records.

### TASK 1

Plan and implement the database models needed to support the journal feature. Journal entries should be associated
with a single StudentData instance. They should be timestamped and linked to the academic year when they were
created via the current MainConfig instance. They may optionally be linked to one or more ProjectClassConfig instances.
They are owned by a single User instance associated with the user who created them, except for entries
that are created automatically in the background as explained in TASK 3. Each entry should contain a
free-form HTML field containing the main journal entry.

Journal entries may be sensitive. To store them securely in the database, use the EncryptedType() SQLAlchemy
column type and AesEngine to encrypt the entry. See the StudentData.exam_number field in @app/models/students.py
for an example of how this is done.

Implement the database models needed, but do NOT attempt to perform the database migration. I will
perform the migration manually.

### TASK 2

Plan and implement routes and Jinja2 templates to provide a user interface and CRUD functionality for the journal.
Users with convenor or co-convenor roles for any project class can create ad hoc journal entries which are
associated with their project class. Convenors should only be able to view entries associated with their project
class. Users with "root", "admin", or "office" roles can create ad hoc journal entries, which may optionally
also be associated with a group of project classes, or not be associated with a project class at all.

Journal entries should only be editable by the user who created them.

Use a Datatables front end to display the table of journal entries for any student. Default to ordering the
table in descending order of timestamp. Allow creation of new journal entries from this view. Use a similar visual
style to the existing application. Look in @app/templates/admin for many examples, e.g.
@app/templates/admin/edit_project_class.html or @app/templates/admin/edit_period_definitions.html.
The add and edit views should share the same Jinja2 template. Look at @app/templates/admin/edit_period_definition.html
for an example of how this is done.

Use the select2 library to style the dropdown menu for the multiple-select field for project classes. See
@app/templates/admin/edit_programme.html for an example of how to use select2.

The freeform HTML field should be rendered using TinyMCE. See e.g.
@app/templates/convenor/marking_events/edit_marking_scheme.html for an example of how to use TinyMCE.

The Datatables front end should be backed by an AJAX endpoint. Use the ServerSideSQLHandler pattern to implement
searching, sorting, and pagination of the table. See e.g. workflow_items_ajax() in
@app/emailworkflow/views.py for an example of how to do this.

### TASK 3

Perform a refactoring to automatically create journal entries whenever a SubmittingStudent or SelectingStudent
record is created or deleted. These entries should record the student's current academic year and degree programme
at the time of the create/delete event. They should also record the name of the user who initiated the event.
Include a footer in the journal entry noting that the entry was automatically created. These entries are NOT
owned by a specific user.

Also, create entries whenever a CustomOffer associated with the student is created or deleted.

For deletion events, include a short explanation of the reason for the deletion obtained from the user, as explained in
TASK 4.

### TASK 4

The delete_submitter() and delete_selector() functions should allow the user to enter a reason for the deletion,
which is to be recorded in the student's journal as explained in TASK 3. For a similar example, see the
create_custom_offer() route in @app/convenor/selector_detail.py. This should replace the current implementation
which routes through the @app/templates/admin/danger_confirm.html template to warn the user that deletion cannot
be undone. You will need to implement a new Jinja2 template backed by a form to allow the user to enter the reason.
However, show the same warning message to the user as the current implementation.

### TASK 5

Add an entry linking to the student's journal inspector to the Actions dropdown menu rendered from the _menu template
in @app/ajax/users/shared.html.

Add an entry linking to the journal inspector the Actions dropdown menu rendered in the convenor selectors and
submitters views. These are implemented in @app/ajax/convenor/selectors.html and @app/ajax/submitters.html.

For users with "root", "admin" or a convenor-level role for the appropriate project class, add a button the
project hub page rendered by @app/templates/projecthub/hub.html to link to the student's journal inspector.
Do NOT show this button (even disabled) to users with any lower level of access. Do NOT allow it to be visible
to users with a "student" role, under any circumstances.

Add a link to the student's journal inspector in the student_offcanvas() macro defined in
@app/templates/admin/matching/student_offcanvas.html.