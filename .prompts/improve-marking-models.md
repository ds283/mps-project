## PREAMBLE

This task is part of a broader complex of refactoring tasks aimed at rebuilding the legacy feedback system based on
SubmissionPeriodRecord into a new, workflow-centered system based on MarkingEvent and MarkingWorkflow and their
associated models.

This task does not introduce major new functionality, but cleans up some of the newly introduced code and supporting
models.

## TASK 1 -- Changes to MarkingEvent and MarkingWorkflow schema

To support aggregation and conflation of marks, we need each MarkingWorkflow to have a key that is unique within its
MarkingEvent.

Add a new "key" field on the `MarkingWorkflow` model. The `key` should be unique within its MarkingEvent. Look at the
logic surrounding database constraints and form validation for `MarkingWorkflow.name` to see how to enforce uniqueness.

The "key" field should be captured during creation of the `MarkingWorkflow`. Adjust the form to allow this. It can
subsequently be edited. The key should be a valid Python identifier.

Add a new `targets` field on the `MarkingEvent` model. `targets` should be a valid JSON representation of
a dictionary, with the followig form:
{ "target_name": "conflation_rule", ... }
where each "target_name" is a string that should be a valid Python identifier. The conflation rule should be a valid
string representing a Python expression. This expression may contain identifiers corresponding to the `key` fields on
the constituent `MarkingWorkflow`s. It should evaluate to a Python float when these keys have float values.

Validate this structure in the same way as parse_schema() function and valid_marking_schema() validator in
@app/shared/forms/wtf_validators.py. If the JSON structure is not valid, pass a validation error back through the
WTForms control so that it can be surfaced to the user.

The form control for `targets` should be rendered as a JSON editor using CodeMirror as in the editor for the `schema`
field on MarkingScheme in @app/templates/convenor/markingevent/edit_marking_scheme.html.

## TASK 2 -- Fix broken marking scheme selector on edit_marking_workflow.html.

When editing an already-created MarkingWorkflow, the marking scheme selector is broken. On creation of the
`MarkingWorkflow`, the selected mark scheme is duplicated as a `LiveMarkingScheme` object. The link to this object is
stored on the marking workflow.

When editing, the `marking_scheme` control is populated with MarkingWorkflow element from the get_schemes() query in
@app/convenor/forms.py. This means assignment of the `LiveMarkingScheme` object held in `MarkingWorkflow` is rejected.
The control appears to be unset when it is rendered.

Instead, what is wanted is that the `marking_scheme` control should be set to the `MarkingScheme` object that the
`LiveMarkingScheme` links to.

If the user **does not change the marking scheme** when submitting the form, then we wish to leave this
`LiveMarkingScheme` object in place and not generate a new one.

On the other hand, if the user **changes the marking scheme** then we wish to discard the old `LiveMarkingScheme`
object (which is now orphaned) and replace it with a new LiveMarkingScheme linking to the newly selected marking
scheme.

The purpose of `LiveMarkingScheme` is to freeze the marking scheme when the `MarkingWorkflow` is created, so that
subsequent edits to the marking scheme do not bring the schema out of sync with the JSON report structures stored in
`MarkingReport.report` fields. This is why the marking scheme cannot be changed after any marking reports have been
submitted. However, it would be helpful to surface to the user when the LiveMarkingScheme is older than the current
version of its parent `MarkingScheme`. This can be done by adding `EditingMetadataMixin` to `LiveMarkingScheme` and
populating it at the time of creation with `creation_timestamp`. This timestamp should be compared to the
`MarkingScheme.last_edit_timestamp` field. If the `LiveMarkingScheme` is older than the `MarkingScheme`, this should be
reported to the user in the "Mark scheme" column of the `MarkingWorkflow` table.
