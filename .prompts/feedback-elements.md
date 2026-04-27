## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

This task is associated with developing user interface elements to manage the resources that will later be used to
generate feedback documents based on `MarkerReport` instances captured by a `MarkingWorkflow`.

Models to support this are already present in the database, in @app/models/feedback.py. They are:

- `FeedbackAsset`: represents a `SubmittedAsset` that is involved in the production of a feedback document, such as
  images that might be used when generating a PDF document.
- `FeedbackTemplate`: represents a Jinja2 HTML template for rendering to PDF, which will generate the actual feedback
  report delivered to the student. The HTML text can be edited.
- `FeedbackTemplateTag`: tenant-scoped free-text tags or labels for `FeedbackTemplate` instances
- `FeedbackRecipe`: a container for a collection of related resources used when building a feedback document. There is a
  primary template linked by `FeedbackRecipe.template`, which is a `FeedbackTemplate`. There may also be a list of
  subsidiary `FeedbackAsset` instances, which might be images or similar.
- `FeedbackReport`: represents a `GeneratedAsset` produced by applying a `FeedbackRecipe` to a particular student.

General implementation patterns:

- Views that provide lists (of `FeedbackAsset`, `FeedbackTemplate`, `FeedbackRecipe`, etc.) should use a Datatables
  based front end backed by an AJAX endpoint. Implement an AJAX row formatted in @app/ajax/convenor.
- Use the `ServerSideSQLHandler` pattern where possible to provide sorting, searching, and pagination in the AJAX
  endpoint. Use `ServerSideInMemoryHandler` where it is not possible to build a single SQL query that will satisfy
  all requirements.
- Do not use separate "display" and "sortstring" fields in Datatables rows when `ServerSideSQLHandler` is used.
  These do not format correctly and are not needed. `ServerSideSQLHandler` will handle and sorting required.
- Use the `select2()` library to render `QuerySelectField` and `QueryMultipleSelectField` fields. Use the
  `select2-small` value for the `selectionCssClasss` and `dropdownCssClass` properties.

This is a large refactoring. Please generate an on-disk progress file and update it as you work, so that state
can easily be recovered if the implementation runs over more than one rate-limit window.

### TASK 1. CRUD-like functionality for `FeedbackAsset`, `FeedbackTemplate`, `FeedbackRecipe`

Please read @app/templates/convenor/dashboard/resources.html. Feedback assets, templates, and recipes are
resources that we need to manage in the same way.

You will need to generate a new resource card linking to a page managing the feedback assets. This page will need
distinct sections for managing assets, templates, and recipes. We do not expect a large number of any individual
element, so a dashboard-style display is likely to be the correct route. The dashboard should extend base_app.html,
like the marking scheme inspector. Add a "back button" link to return to the resources grid page.

To lay out the dashboard, use the `dashboard_tile()` macro in @app/templates/dashboard_widgets.html to generate a row
of metric cards showing the number of each type of asset. Use
@app/templates/covenor/dashboard/overview_cards/selection_open.html for an example of how these metric cards are used.

Below the metric cards, add a card containing a table listing `FeedbackRecipe` instances available for the
project class, inferred from the `ProjectClass` or `ProjectClassConfig` that anchors the convenor dashboard.
The table should list the recipes identified by label name (first column), the creation metadata (author and timestamp)
and last edit metadata (author and timestamp) in a second column, and a summary of the assets in a third column.
The fourth column should be a drop-down "Actions" menu. The actions menu should allow the recipe to be edited or
deleted. See below for details of the edit page. This card should include a button allowing creation of a new
feedback recipe. Feedback recipes must have names that are unique within their project class. This is enforced at the
database level, but you must include a validation check on the creation form so that the issue can be surfaced to
the user without creating a database exception. Use mixins to share as much configuration as possible between
the Add and Edit forms. For example, see `AddMarkingEventForm` and `EditMarkingEventForm` for an example of the
pattern.

Below this card, add another card containing a table listing `FeedbackTemplate` instances available for the project
class. This table should list the recipes by label (first column), the creation metadata (author and timestamp)
and last edit metadata (author and timestamp) in a second column, and the description followed by any applied
tags in a third column. The fourth column should be a drop-down "Actions" menu. The actions menu should allow the
tempalte to be edited or deleted. See below for details of the edit page. This card should include a button allowomg
creation of a new feedback template. Templates must have names that are unique within their project class. This is
enforced at the database level, but you must include a validation check on the creation form so that the issue can be
surfaced to the user without creating a database exception. Use mixins to share as much configuration as possible
between the Add and Edit forms.

Below this card, add another card containing a table listing `FeedbackAsset` instances available for the project
class. This table should list the assets by label (first column) with an embedded small thumbnail preview image
below. This preview thumbnail can be obtained from the `SubmittedAsset` record associated with the `FeedbackAsset`.
The second column should show creation metadata (author and timestamp) and last edit metadata (author and timestamp).
The third column should include the description. The fourth column should be a drop-down "Actions" menu. The actions
menu should allow the asset to be edited or deleted. See below for details of the edit page. This card should include a
button allowing creation of a new feedback asset. This page will need to allow files to be uploaded and associated
with the asset by creation of a new `SubmittedAsset` record. Read `convenor.upload_period_attachment()` and inspect
its associated templates for examples of how this should be done. Use the bucket map `OBJECT_STORAGE_BUCKETS` to find
the appropriate `ObjectStore` and use the `buckets.PROJECT_BUCKET` bucket as the target `ObjectStore`.
Ensure that you call `dispatch_thumbnail_task()` to queue
generation of the thumbnails after upload.

Your user interface design should be clean, modern, and consistent with user interfaces used elsewhere in the system.

The add/edit page for `FeedbackRecipe` should allow the label to be set (with validation to ensure it is unique;
the current label can always be re-used, but if the label changes, it must be unique), and a template to be selected
from the list of templates available for the project class. It should also be possible to view the list of assets
associated with the recipe, and to adjust these. Base your user interface on the `convenor.edit_marking_workflow()` and
`convenor.add_workflow_attachment()` routes and their associated templates. In the asset list, surface thumbnails for
each asset to give visual guidance about what the asset is, and include the label, description, and last edit metadata.
Style any select boxes using the `select2` library in accordance with the project conventions. Update the last edit
metadata after editing.

The add/edit page for `FeedbackTemplate` should allow the label to be set (with validation to ensure it is unique;
the current label can always be re-used, but if the label changes, it must be unique), and a description to be set.
Include a large text area, by default 15 lines, that contains the template body. The template body should be
editable by the user. You should also include a selectable list of labels defined by `FeedbackTemplateTag` instances
(but the user can freely create new ones). Base your implementation of the labels used for email templates;
see `admin.edit_global_email_template()` and its associated templates. Style any select boxes using the `select2`
library in accordance with the project conventions. Update the last edit metadata after editing.

The add/edit page for `FeedbackAsset` should allow the label to be set (with validation to ensure it is unique;
the current label can always be re-used, but if the label changes, it must be unique), and likewise the description.
Update the last edit metadata after editing.

When deleting a `FeedbackAsset`, you must ensure that the corresponding `SubmittedAsset` record is also deleted,
and the physical asset is removed from the object store.
