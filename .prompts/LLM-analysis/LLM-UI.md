## SUMMARY

Recent work has implemented an LLM-based language analysis pipeline for project reports submitted by students. This task
describes a collection of inter-related refactorings of the back-end task chain, the user interface, and the workflows
associated with the `MarkingEvent`/`MarkingWorkflow` system.

The main user interface for the LLM language analysis outputs is currently on the
@app/templates/documents/submitter_manager.html template. There is also a concise summary rendered on the convenor's
"Submitters" inspector. This is rendered using the project_tag() macro in
@app/templates/convenor/submitters_macros.html.

The main tasks are:

- Clean up the user interface for the LLM language analysis outputs. Changes to the user interface elsewhere to surface
  its outputs where these are appropriate.
- Bring the LLM language analysis into the report processing task chain. In particular, we want to embed some LLM
  outputs into the report itself, but that can be deferred until a subsequent session.
- Bring the LLM language analysis outputs into some marking workflows, and make user interface changes to accommodate
  this.

This is a large implementation task. Completion may span multiple rate limit windows. The status file should be named
LANGUAGE_ANALYSIS_USER_INTERFACE.md in the .prompts/LLM-analysis directory.

Structure it with sections: Completed, In Progress, Pending, Decisions Made, and Known Issues. Update it after
completing each major component. Record any architectural decisions made during implementation, particularly where the
spec was ambiguous.

## THE DESIRED USER INTERFACE

### CONVENOR SUBMITTER VIEW

This is rendered by the project_tag() Jinja2 macro, as described above

- Currently grade information held in `SubmissionRecord.supervision_grade`, `SubmissionRecord.report_grade` and
  `SubmissionRecord.presentation_grade` is not surfaced unless these grades are set. The grade data should always be
  shown, with an indication that the mark is not yet available of these fields are unset. The corresponding "generated
  by" and "generation timestamp" data should be shown very compactly for each grade, where this data is available.
- The grade fields are populated by _propagate_grade_to_records() in @app/convenor/markingevent.py. However, this does
  not record which `MarkingEvent` was used to populate each grade. Please consider the options for persisting this
  information in the database and make a recommendation.
    - Option A: is it possible to set a FK to the `MarkingEvent` on `SubmissionRecord`? This has the disadvantage of
      creating a circular dependency chain, since `MarkingEvent` depends on `SubmissionPeriodRecord` and inherits the
      `SubmissionRecords` attached to it.
    - Option B: set a flag on each `MarkingEvent` to indicate whether it provided the data on the `SubmissionRecord`.
      This seems more fragile and there is a risk that the flag gets out of sync with reality.
      You can consider other options if you think there is a better approach.
- The main elements we wish to highlight in the view are RISK FACTORS, which will be associated with annotations (to be
  described below). This view should clearly highlight these risk factors with a traffic-light colour coding system, and
  a visual highlight for the data in this table cell to show when elevated risk factors are present. We also want a
  visual call-to-action when elevated risk factors are present without having been signed-off and annotated by the
  convenor.
- The view should provide a link to a view allowing the risk factors to be annotated and signed off. This view should
  also be accessible from the `SubmitterReport` inspector associated with a `MarkingWorkflow` (see below).
- We also want provide access to the detailed LLM report FROM THIS INSPECTOR. Currently the full details of the report
  are accessible only from the submitter_manager.html template. The data is split between the "Langugae analysis" card
  on this view, and a offcanvas slideover element that provides a more detailed view. The information has possibly
  become too large for an offcanvas element to comfortably hold. Please consider the UI alternatives here, and make an
  analysis of the possible options.

### THE SUBMITTER DOCUMENTS MANAGER VIEW

This needs changes to make its UI consistent with the detailed LLM report also available from the convenor's "
Submitters" inspector, as described above.

The UI between the two views should be consistent, so that the same data is presented in the same way.

### THE LLM REPORT USER INTERFACE

We want to tidy up the user interface elments. This description assumes that the LLM report is being moved entirely to a
different view, or to an offcanvas slideover, so that it can be shared with the convenor's "Submitters" inspector as
described above.

The LLM grade band assessment and the LLM summary of the report should be highlighted at the top, followed by the
student's detected "Preface" or personal contribution statement, if present. Below that, we want to summarize the main "
risk factor" elements for the report (as mentioned above).

The key risk factors are:

- Turnitin score in the "needs attention" range. Currently this is handled within the `SubmitterReport` inspector for
  `MarkingWorkflow`. A `SubmitterReport` moves into the `NEEDS_CONVENOR_ATTENTION` lifecycle state if the Turnitin score
  is in the "Yellow" range or above. The convenor is required to mark the situation resolved explicitly, and provide a
  brief explanation or annotation.
    - This design was in error. The Turnitin score needs to be resolved only **once**, no matter how many
      `MarkingWorkflow` instances are created for the `SubmissionRecord`. Details of the "resolved" status and any
      convenor annotation should be recorded on the `SubmissionRecord` because this is the semantically correct place to
      do so. The resolution should be shared by all `MarkingWorkflow` instances. We cannot have incompatible resolutions
      being made in different `MarkingWorkflow` instances.
    - The "Turnitin" risk factor is only one of a number of risk factors that should be treated on an equal footing.
      Whenever one of these risk factors is present, any `SubmitterReport` instances should be held in the
      `NEEDS_CONVENOR_ATTENTION` lifecycle state. until they are marked resolved. The risk factors should also be
      highlighted on the convenor's "Submitters" inspector as described above.
    - The "Turnitin" call to action shown on the `SubmitterReport` inspector should be updated to reflect the presence
      of one or more risk factors.
- The next risk factor is the "AI use" state that reflects two or more of the MATTR, MTLD, and burstiness B metrics
  being in an elevated state.
- Another risk factor is the presence of an explicit AI complicance statement in the report, as detected by the LLM
  analysis.
- Another risk factor is the document length exceeding a specified limit on the number of words or pages.
    - To handle this, `ProjectClass` needs flags to indicate whether a word or page limit has been set, and what that
      limit is. It is only possible to set one of these limits; they can't both be set simultaneously. The project class
      editor view @app/templates/admin/edit_project_class.html should be updated to allow the user to set these flags,
      with the values being captured by the endpoint that backs the form, and persisted in the database. Make the
      database schema changes needed.
    - Each `ProjectClassConfig` should inherit the current `ProjectClass` setting, but allow it to be overridden. A
      similar pattern is used for the "LOCAL CONFIGURATION" flags in `ProjectClassConfig`, such as
      `ProjectClassConfig.uses_supervisor`. It should be possible to edit these settings in the
      convenor.edit_project_config() view in @app/convenor/marking_feedback.py.
    - If the measured word count or the measured page count exceeds the configured limits, as appropriate, this counts
      as a another risk factor. Ensure that you use the word count directly computed from the cleaned text, and NOT the
      student-reported word count recovered from the LLM. The student-reported word count is considered in the next
      point.
- The final risk factor is a discrepancy between the student-reported word count and the word count computed from the
  cleaned text, where these are both available.
    - The tolerance here should be configurable, with a baseline of 15%. This setting should be configured on
      `ProjectClass`, inherited by `ProjectClassConfig`, and editable on a per-config basis as for the word/page limits
      described above. Make the database schema changes needed to support this.
    - Where the student-reported word count differs from the measured word count above the specified tolerance, this
      comprises another risk condition requiring explicit convenor resolution.

Below the risk factors display, the UI should surface any document metrics, including the number of detected references,
the number of detected figures and tables (shown separately), and which of these may be unreferenced. In this section,
you should also show discreetly the measured timings for the different stages in the LLM pipeline. Please add separate
timings for the LLM grade band assignment and the LLM feedback query.

the UI should show the LLM's reasoning for the grade band recommended, followed by the
specific criteria and the LLM's assessment of the evidence for or against. Pleae format this section as compactly as
possible.

Finally, the UI should show the LLM's suggestions for positive and negative feedback.

Please design the UI to be visually appealing, modern, and clean. It should be easy to read and understand.

Please note:

- All `SubmitterReport` instances linked to a `SubmissionRecord` must remain locked to the `NEEDS_CONVENOR_ATTENTION`
  state while any unresolved risk factors are present.
- It should be possible for a convenor to resolve ALL risk states either from the `SubmitterReport` inspector, or
  directly from the convenor's "Submitters" inspector.
- It should be possible to resolve all risk factors simultaneously from a single view.
    - This view should concisely summarize the main information about the risk factor, allow the convenor to mark the
      situation resolved, and add a brief annotation to explain what action has been taken.
    - Please consider how to persist this information in the database. Currently, information on the Turnitin resolution
      state is persisted using the TURNITIN REVIEW fields on `SubmitterReport`. This information needs to be moved to
      `SubmissionRecord`, as explained above. There are now many risk factors and more may be implemented in future. We
      would like an extensible approach. Please advice whether persisting this information as a serialized JSON data
      structure provides a sensible approach.
    - For each risk factor, we still wish to capture a timestamp for when the issue was resolved, and the identity of
      the user who resolved it.
- There is NO NEED to generate a migration step to move data from the `SubmitterReport.turnitin_*` fields. There are
  not yet any database entries that use these fields (the feature is still being built).

For the LLM report UI:

- The "AI use" risk factors can be displayed more richly on this view, where there is more space available. Please
  organize using the following groups of related data:
    - The Turnitin status. If this is a risk factor, whether the situation has been marked resolved, and who by.
    - The AI compliance statement. If present, this must be reviewed by the convenor and explicitly marked as resolved.
    - The AI use metrics (MATTR, MTLD, Burstiness, AI-indicator pattern counts), and whether these constitute a risk
      factor. If so, whether the situation has been marked resolved, and who did so.
        - Please generate a visualization of where these metrics fall relative to the threshold at which they are
          considered elevated.
        - You may use the Bokeh library to generate the visualization, which is already part of the project. You may
          also use simpler markup if you prefer.
        - MATTR, MTLD and the B metric do not appear to be normally distributed. The visualization should probably just
          show a "danger" threshold and where the measured count falls relative to this threshold.
    - The word count, student-recovered work count, any discrepancy between them (expressed as a percentage). If this is
      a risk factor, whether the situation has been marked resolved, and who did so
    - If the user has "admin" or "root" privileges, it should offer an action button to clear the results (without
      rerunning the analysis), or to clear the results and re-run the analysis.
        - Note that, below, I explain that production of the processed report should now be preceded by the LLM
          analysis, because the processed report will depend on some of its outputs. Clearing the results should
          therefore clear the processed report and delete the corresponding physical asset in the object store.

If an error state is present:

- The UI should note the error state.
- If the user has "admin" or "root" privileges, it should offer an action button to clear the error state

## THE PROCESSED REPORT

As explained above, we now wish to embed some of the LLM analysis outputs into the processed report. This task is
performed by the process() task in @app/tasks/process_report.py. The processing task creates a new cover page that
embeds certain metadata about the report.

- Generation of the processed report should now be conditional on the LLM analysis having completed successfully.
- If the LLM analysis is cleared or reset, the processed report should be cleared as well. However, it should also be
  possible to clear the processed report and request regeneration WITHOUT clearing the LLM output.
- When the LLM analysis task completes, it should now proceed to generate and emplace a new processed report.

The cover page is generated using PyMuPDF.

- Please adjust the cover page to include the following document-level metrics. Include a disclaimer that the
  information in this section is automatically generated, is provided for guidance only, and must be verified by the
  human marker.
    - How many references were detected, and whether any of them may be uncited in the main text. If there are only
      three or four, include explicit details of which ones appear to be uncited. If there are more, there will only be
      space to include a count.
    - How many figures were detected, and which of them appear to be unreferenced in the main text.
    - How many tables were detected, and which of them appear to be unreferenced in the main text.
    - The word count estimated from the cleaned text, and any student-reported word count recovered from the LLM. DO NOT
      highlight any discrepancy; simply report the numbers.
- Please also:
    - Note whether an AI use statement was detected. If so, please highlight this clearly to the human marker in a way
      that draws attention to it (e.g. a red border). Please add a note that AI use statements are reviewed by the
      convenor, but that the marker should be aware of the statement when preparing their report. If no report was
      detected, please note this in a muted way. Do not say that no AI statement is present -- only that none was
      detected, and that a statement may be present in the report.

## THE MARKING FORM

Where there are feedback suggestions from the LLM associated with a `SubmissionRecord`, please surface these on the
marking form @app/templates/faculty/marking_form.html. Locate the feedback in the correct place: "positive" or "what is
good?" feedback should go ABOVE the positive feedback box; "suggestions for improvements" should go above its
corresponding input box.

Note that the feedback suggestions are AI generated. Label them clearly as suggestions, not recomendations.