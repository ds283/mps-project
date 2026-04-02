## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

This task is intended to carry out refactorings so that `PeriodAttachment` records can be associated with a set of roles
matching those usd on `SubmissionRole` instances.

### TASK 1. Database schema changes

Please make a recommendation of how to associate a list of roles (which are integer magic numbers defined by the
`SubmissionRoleTypesMixin` class) with a `PeriodAttachment` record. It should also be possible to specify that the
`PeriodAttachment` is not restricted by submission role and is available to all participants.

Please note that currently there is NO STUDENT ROLE in `SubmissionRole`. Please make a recommendation for how to adjust
the code to account for this.

- Option A. Add a new `SubmissionRoleTypesMixin.ROLE_STUDENT` role that is only used to determine access permissions for
  `PeriodAttachment`, but is never associated with a explicit `SubmissionRole` instance.
- Option B. As for Option A, but now create `SubmissionRole` instances for students in addition to supervisors, markers,
  moderators, etc. This is conceptually clean, but potentially redundant since a student obviously must have a role
  associated with any `SubmissionRecord` instance representing a project they are undertaking.
- Option C. Treat student roles differently and retain the `PeriodAttachment.publish_to_students` field to determine
  whether a given attachment should have visibility to students. This is simple but potentially complicates queries.

You may also consider other options.

Your recommendation should also plan for removal of `PeriodAttachment.publish_to_students` (unless Option C is chosen),
`PeriodAttachment.include_marker_emails` and `PeriodAttachment.include_supervisor_emails` fields. These will become
obsolete since the same information will be tracked by the more fine-grained role capture implementation.

Please design an idempotent migration that will populate existing `PeriodAttachment` records with the new role
information, based on the following assignment:

- if `PeriodAttachment.publish_to_students` is True and this field is being removed, add `ROLE_STUDENT` to the list of
  roles held on the `PeriodAttachment`.
- if `PeriodAttachment.include_marker_emails` is True, add `ROLE_MARKER` and `ROLE_MODERATOR` to the list of roles.
- if `PeriodAttachment.include_supervisor_emails` is True, add `ROLE_SUPERVISOR` and `ROLE_RESPONSIBLE_SUPERVISOR` to
  the list of roles.

### TASK 2. Change email sending behaviour

Once an implementation strategy has been chosen, please:

- adjust the upload route documents.upload_period_attachment() in @app/documents/routes.py to capture the roles that
  should be held by the `PeriodAttachment` instance via the upload form and persist them on the `PeriodAttachment`
  instance.
- adjust places where `PeriodAttachment` instances are attached to outgoing emails to respect these roles.
    - when sending marking notification emails via dispatch_emails() in @app/tasks/marking.py, emails to supervisors
      should only include attachments with the `ROLE_SUPERVISOR` or `ROLE_RESPONSIBLE_SUPERVISOR` role.
    - likewise, emails to markers should only include attachments with the `ROLE_MARKER` role.
    - emails inviting moderators to submit a moderation report should only include attachments with the `ROLE_MODERATOR`
      role.

### TASK 3. Surface `PeriodAttachment` instances on faculty and student dashboards and project hubs

Currently, PeriodAttachment instances are surfaced on on the @app/templates/documents/submitter_manager.html template.
This makes them relatively undiscoverable.

Please make the following changes:

- remove the display of `PeriodAttachment` instances from submitter_manager.html. In future, this should be restricted
  **only** to documents that have been attached to a specific `SubmissionRecord` instance.
- student dashboards show a list of active projects associated with `SubmissionRecord` instances for the current
  submission period. Faculty dashboards show a list of supervisor, marking, and moderating assignments associated with
  ROLE_SUPERVISOR/ROLE_RESPONSIBLE_SUPERVISOR, ROLE_MARKER, and ROLE_MODERATOR roles.
    - for STUDENTS and ROLE_SUPERVISOR/ROLE_RESPONSIBLE_SUPERVISOR, please add a compact annotation on the main
      dashboard that documents are available. The documents themselves should be surface on the project hub page as
      described below.
    - for ROLE_MARKER and ROLE_MODERATOR there is no access to the project hub page. Here, please surface documents VERY
      COMPACTLY directly on the dashboard, but ONLY ONCE for each `SubmissionPeriodRecord` where the user has marking or
      moderating assignments. Include a deascription only via a tooltip or other popover. Format using a lightweight
      table (NOT DataTables based). Do NOT show duplicate document entries for each marking or moderating assignment.
      Include a download link. Include a small thumbnail preview.
    - add a compact "Files" pane on project hub page @app/templates/projecthubs/hub.html to show a summary of about 5
      recently uploaded `PeriodAttachment`s that are visible to the user. When designing this pane, please consider how
      to make it extensible. In future there may be similar panes to surface other types of documents or resources,
      including `ProjectSubmitterArticle` and `ConvenorSubmitterArticle` instances, exemplar reports, and possibly
      other resources such as LaTeX template files. Include a small thumbnail of the preview, and provide a download
      link.
    - Link this "Files" pane to a separate view ("Downloads and resources") where the user can inspect all attached
      `PeriodAttachemnt` instances using a more sophisticated DataTables front end backed by an AJAX endpoint. Use the
      ServerSideSQLHandler pattern to handle sorting, searching and pagination of the table. For each
      `PeriodAttachment`, include its name, a medium sized thumbanil preview, the full content of the
      `PeriodAttachment.description` field, and a download link.
    - The visual design should match the existing design of the hub.html template and its associated templates. Ensure
      that there is a return link from the "Downloads and resources" view back to the project hub.

### TASK 4. Adjust the marking form and moderation form to surface only attachments that are visible to the user

Please adjust the marking form @app/templates/faculty/marking_form.html and the moderation form
@app/templates/faculty/moderator_report_form.html to surface ONLY attachments that have been assigned for the
`SubmissionRole` type that the user holds. Note:

- Students should only ever be able to view attachments that have been explicitly assigned a STUDENT role.
- Users with `ROLE_SUPERVISOR` can see attachments marked for `ROLE_SUPERVISOR` but NOT `ROLE_RESPONSIBLE_SUPERVISOR`.
- Users with `ROLE_RESPONSIBLE_SUPERVISOR` can see attachments marked for `ROLE_SUPERVISOR` and
  `ROLE_RESPONSIBLE_SUPERVISOR`.
- Users with `ROLE_MARKER` can see attachments marked for `ROLE_MARKER`.
- Users with `ROLE_MODERATOR` can see attachments marked for `ROLE_MODERATOR`.

