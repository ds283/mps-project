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

### TASK 1. CRUD-like functionality for `FeedbackAsset`, `FeedbackTemplate`.

