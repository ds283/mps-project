## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

This task is associated with developing user interface elements to manage the resources that will later be used to
generate feedback documents based on `MarkerReport` instances captured by a `MarkingWorkflow`.

Models to support this are already present in the database, in @app/models/feedback.py. They are:

- `FeedbackAsset`: represents a `SubmittedAsset` that is involved in the production of a feedback document, such as an
  images that might be used when generating a PDF document, or the Jinja2 template producing the HTML that will actually
  be rendered into a PDF. There is a special `is_template` field to identify "base" templates of this kind, which are
  the primary element in generating a feedback document.
- `TemplateTag`: free-text tags for `FeedbackAsset` instances
- `FeedbackRecipe`: a container for a collection of related resources used when building a feedback document. There is a
  primary template, which must always be a `FeedbackAsset` with the `is_template` parameter set. There may also be a
  list of subsdiary assets, such as images.
- `FeedbackReport`: represents a `GeneratedAsset` produced by applying a `FeedbackRecipe` to a particular student.

### TASK 1. Refactor the schema

Currently, `FeedbackAsset` instances are organized at the level of a group of project classes. This is intended for
efficiency reasons, to prevent unnecesary duplication of assets, and also to stop assets used on multiple project
classes from drifting out of sync.