## SUMMARY

Recent tasks have developd an LLM analysis pipeline in which `SubmissionRecord` instances are managed through an
analysis pipeline. This pipeline involves calculation of some lexical diversity metrics and other document-level
metrics, submission to an LLM, and finally generation of a processed report. The processed report redacts the student
name (if this has been incorrectly included), and generates a title page that summarizes some of the metrics.

Submission to the LLM pipeline is orchestrated by the `LLMOrchestrationJob` model defined in
@app/models/llm_orchestration.py.

The desired changes in this task are:

- collect some extra metadata about the pipeline, to inform future decisions about its effectiveness
- unify the way jobs enter the pipeline, in order to ensure that orchestration occurs properly for all tasks and the LLM
  server is not overloaded
- make the orchestration task fault tolerant

## DESIRED CHANGES

### EXTRA METADATA

We would like to collect the following extra metadata about the LLM pipeline. This is intended to inform future
judgements about its accuracy, and whether it is worth re-running if a larger LLM (or larger context window) becomes
available later.

- the LLM model name
- the size of the context window
- the number of chunks that were required to submit each report to the LLM for grading.

For storing the LLM model name, there is not much cost in storing the entire name in the JSON blob stored on
`SubmissionRecord`, compared to the amount of data that is already being stored there. However, there is potentially
value in normalizing this information by storing the model name in a separate table, which is linked-to from the
`SubmissionRecord` table. Please evaluate both of these options (and others if appropriate) and make a recommendation
about best practice.

Where these metrics are available, they should be surfaced in the UI alongside the timing metadata. In particular this
should be done on the LLM report template @app/templates/documents/llm_report.html.

### BATCHING IN THE SUBMISSION STEP

The current orchestration strategy uses Celery callbacks to submit jobs sequentially to the LLM server. That is
currently what is required, but it does not allow scope for multiple jobs to be submitted in parallel. The desired
outcome is to have a Flask configuration key OLLAMA_BATCH_SIZE that controls the number of jobs that can be submitted to
the LLM in parallel. For the existing deployment this will be set to 1, but it may be set to larger values in future.

Also, multiple `LLMOrchestrationJob` instances may be present in the database due to multiple submission events. In the
current implementation these run simultaneously. This is not desirable because it means jobs do not currently know
whether other submissions are in progress. The result is that multiple submissions to the LLM server can be made in
parallel, bypassing the purpose of the orchestration step.

What is needed is a single orchestration manager that submits jobs from the LLM server from all active
`LLMOrchestrationJob` instances up to the current maximum batch size.

### HOW JOBS ENTER THE PIPELINE

There are submision points associated with the "AR risk" dashboard in @app/dashboards/views.py. These submission methods
all create `LLMOrchestrationJob` instances to control progression of each job through the pipeline.

However, there are also ad hoc submission methods that that do not operate through the `LLMOrchestrationJob` model, and
therefore create unwanted opportunities for orchestration to be bypassed, potentially leading to overload of the LLM
server. These include:

- The launch_language_analysis() method in @app/documents/views.py. This launches a full pipeline, but assembled only as
  an ad hoc Celery chain.
- The pull_report() Canvas workflow and the associated pull_report_finalize() workflows in @app/tasks/canvas.py. These
  pull a PDF report using the Canvas REST API, store any associated Turnitin similarity metrics, and then initiate
  production of the processed report. This final step bypasses the entire LLM analysis pipeline, and needs to be
  factored to use it, because the processed report requires the LLM pipeline to be run first.

Both of these need to be refactored to use the `LLMOrchestrationJob` model, so that they can be brought within the
rate-limiting policy currently being applied to the LLM server.

In pull_report_finalize(), the processing needs to be adjusted so that the entire LLM pipeline runs, with production of
the processed report only as the final step.

### SINGLE DEFINIITON OF THE PIPLEINE

We would like application of the pipeline to be defined in a single place, so that no matter how reports are submitted
to the pipeline, they are handled in a common way. Also, any changes to the pipeline would then be taken up globally
without multiple refactorings being requierd.

In particular, we want this for the pull_report_finalize() case, so that once the report is downloaded from the Canvas
REST API and stored, we can apply the standard pipeline to it, including calculation of lexical metrics, LLM data,
applying redaction of the student's name, and so on.

### FAULT TOLERANCE

The `LLMOrchestrationJob` model is not currently fault tolerant. If the Celery task sequence crashes, then (I think) it
can not easily be restarted.

Also, if the web app is restarted, then submission of jobs from any `LLMOrchestrationJob` instances that were in flight
will not be resumed.

We would like to remedy both of these issues. At the moment, some job data is persisted in the main SQL database, and
details of the `SubmissionRecord` instances in the queue are stored in the Redis cache. The Redis cache can be assumed
to be fairly fault tolerant, and to persist across restarts of the web app, and across restarts of the Celery workers.

The strategy for achievin fault tolerance should be considered in relation to the multiple `LLMOrchestrationJob`
instances that may be present in the database, and how submission from these instances is sequenced to prevent requests
being issued to the LLM server at a rate exceeding the current batch size limit.

However, we would prefer NOT to have a polling task for `LLMOrchestrationJob` instances that are in flight, unless there
are reasons of simplicity or robustness that would make this option preferable.