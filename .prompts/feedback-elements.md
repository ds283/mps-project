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
- `FeedbackTemplateTag`: free-text tags for `FeedbackAsset` instances (moving to belong to `FeedbackTemplate`)
- `FeedbackRecipe`: a container for a collection of related resources used when building a feedback document. There is a
  primary template, which must always be a `FeedbackAsset` with the `is_template` parameter set. There may also be a
  list of subsdiary assets, such as images.
- `FeedbackReport`: represents a `GeneratedAsset` produced by applying a `FeedbackRecipe` to a particular student.

These need a set of migrations in order to be used in the new system.

### TASK 1. Migrate to a new data model

Currently, `FeedbackAsset` instances are organized at the level of a group of project classes. This is intended for
efficiency reasons, to prevent unnecesary duplication of assets, and also to stop assets used on multiple project
classes from drifting out of sync. However, this is not ideal because feedback documents should be controllable
by the project convenor.

#### Task 1a. Feedback assets with `is_template==False` should be associated only with a single project class

Instead of a many-to-many `project_classes` relationship, each existing `FeedbackAsset` model
**with `is_template==False`** needs a single `pclass` relationship indexed by a `pclass_id` foreign key.
Then, for each project class in `project_classes`, an idempotent migration needs to run on startup to create
the required duplicate entries. The `project_classes` relationship on the duplicates should be created empty;
it will be removed in a second step.

The linked asset needs to be duplicated at the time of migration. The existing asset must be downloaded from the
object store, and then a new `SubmittedAsset` record created, linked to a newly-uploaded object.
Read @app/tasks/maintenance.py to find assetrecord_maintenance() for an example of how to download and re-upload
from an object bucket. The extra step, not appearing there, is duplication of the `SubmissionAsset` record.

#### Task 1b. Feedback assets with `is_template==True` should be moved to a new `FeedbackTemplate` model

`FeedbackAsset` instances **with `is_template==True`** are to be treated differently. These need to be moved to
a one-instance-per-project-class model via another idemppotent migration, but the content of these records is moved
to a new `FeedbackTemplate` model.

The content of the `FeedbackTemplate.template_body` field should be set to the content of the asset linked to the
original `FeedbackAsset`. This should be downloaded from the object store and used to populate the new model.

Once the migration has run, the old `FeedbackAsset` records should be deleted. The physical asset should be deleted
from the object store, and the `SubmittedAsset` instance should be deleted.
