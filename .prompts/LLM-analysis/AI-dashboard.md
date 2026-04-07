## SUMMARY

Previous tasks have implemented the calculation of lexical diversity metrics, and other document-level metrics, for
reports submitted by students. These are part of a larger language analysis pipeline which queries an LLM to classify
the report against a grading rubric, and to extract certain parts of the content.

The lexical diversity metrics are used to assess an "AI risk" flag, which is surfaced on the "Submitters" inspector.

In this task, the intention is to produce a data dashboard that shows the distribution of the lexical diversity metrics
for entire cohorts over time. It should allow the data to be segmented by the project class, where there are enough
students to produce meaningful distributions.

As part of the process, new orchestration tasks are needed to compute metrics, LLM outputs, and processed reports for
entire cohorts. These orchestration tasks should be accessible to convenors for the current cycle, (via the "Submitters"
inspector), and to admin users for all cycles held in the database.

This is a large implementation task. Completion may span multiple rate limit windows. The status file should be named
AI_DASHBOARD.md in the .prompts/LLM-analysis directory under the top level project directory.

Structure this file with sections: Completed, In Progress, Pending, Decisions Made, and Known Issues. Update it after
completing each major component. Record any architectural decisions made during implementation, particularly where the
spec was ambiguous.

### LLM SUBMISSION ORCHESTRATION TASKS

New Celery workflows are required to:

- Submit all reports attached to a given `SubmissionPeriodRecord` to the metrics+LLM+processed-report pipeline, where
  the metrics and LLM output are empty. (This may require removal of an existing processed report, in which case the
  corresponding asset in the physical object store needs to be deleted.)
- Clear all metric and LLM outputs (and processed reports), and re-submit **all** reports attached to a given
  SubmissionPeriodRecord to the pipeline.

Buttons to activate these workflows should be added to the "Submitters" inspector. Place these buttons next to the
"Email using local client" action button.

We will later require a higher-level orchestration to carry out the same two functions for:

- all `SubmissionPeriodRecord` instances belonging to e single `ProjectClass` config
- all `SubmissionPeriodRecord` instances belonging to a single cycle, represented by a `MainConfig` year
- all `SubmissionPeriodRecord` instances globally

In planning how to orchestrate these workflows, please consider that the LLM model has limited capacity and we do not
want to swamp it with many simultaneous requests.

- Initially, the LLM model is likely to be of qwen-24b or llama-70b type, running on a single MacStudio with 32 Gb or 64
  Gb memory. With a typical context window, my estimate is that this is likely enough only to service only ONE request
  at once. We therefore wish to submit tasks serially.
- Please consider how this is best done and make a recommendation. Please consider the following scenarios, although you
  may recommend an alternative option if it seems preferable.
    - Option A. Use a Celery chain. This is the simplest approach. The major drawbacks are that the Celery task canvas
      system can be fragile and introspection of the current task state is not entirely straightforward. Also, this
      approach works for a completely serial submission, but cannot easily scale up to partial parallelism.
    - Option B. Use a separate Celery orchestration task that creates LLM submission tasks, monitors their progress, and
      schedules new tasks when space becomes available. This is more complex to implement, but may be less fragile, and
      allows more flexibility (tasks can be scheduled in small batches if the LLM server is upgraded).

### AI DATA DASHBOARD

This will be the first of a suite of data dashboards. The AI data dashboard should be visible to the following groups of
users (which will be a standard pattern for all data dashboards):

- "root" role users can view the AI data dashboard for all cycles, all project classes, and all tenants. They can launch
  orchestration tasks to clear outputs and resubmit reports to the analysis pipeline.
- "admin" role users can view the AI data dashboard for all cycles and all project classes, for tenants they belong to
  via the `tenants` collection on their `User` instance. They can launch orchestration tasks to clear outputs and
  resubmit reports to the analysis pipeline, for project classes they can view.
- project class convenors can view the AI data dashboard for project classes which they convene (or are co-convenors
  for). They can launch orchestration tasks to clear outputs and resubmit reports to the analysis pipeline, for these
  specific project classes only.
- users with the "data_dashboard_AI" role have the same **viewing** permissions as "admin" role users, specifically for
  viewing the AI dashboard: they can view all cycles and all project classes, for tenants they belong to. Users with
  only this permission have "read only" access. They cannot launch tasks to clear results or resubmit reports to the
  analysis pipeline.

The dashboard should be accessible from a new "Dashboards" top-level navbar item. This should be placed between the "
Reports" and "Archive" items. It should work like the "Convenors" navbar item, taking the user to a landing page
containing a responsive Bootstrap grid of cards showing the dashboards that the user has privileges to view. Currently
this will be ONLY the AI data dashboard. The card should briefly summarize the purpses of the dashboard and summarize
the data that is available to view, e.g. "3 tenants, 2 project classes, 10 cycles." Explicitly call out each level only
if the viewable number is greater than 1.

- For users able to view multiple tenants, the dashboard should display project classes from just a SINGLE tenant at
  once. A filter control should be provided to allow the user the select between tenants.
- For users able to view multiple project classes, the dashboard should allow users to select a COMBINATION of project
  classes to display. It is possible to display all project classees simultaneously, but at laest ONE must be selected.
- The dashboard should allow users to select which CYCLES to display, meaning academic years recorded by `MainConfig`
  instances. The default is to display all cycles. At lease ONE cycle must be selected. However, it should be possible
  to restrict the display to an arbitrary subset of cycles.

The data dashboard should then be organized into SECTIONS corresponding to `MainConfig` cycles. Include a control
allowing the sections to be presented in ascending or descending time order.

- Each section should include a subsection for each `SubmissionPeriodRecord` within each selected project class for the
  specified cycle, ordered alphabetically on name. These subsections should contain the information on metrics and
  distributions described below.
- At the end, a summary section should show the same metrics and distributions for the combination of all
  `SubmissionPeriodRecord` instances belonging to the selected project classes for that cycle.

Where viewers have sufficient privilges, at each level (`SubmissionPeriodRecord`, entire `ProjectClassConfig`, entire
`MainConfig` cycle, globally) include action buttons to launch orechestration tasks as described above:

- to launch LLM-pipeline submissions tasks for all `SubmissionRecord` instances where the LLM output is empty
- to clear the LLM output for all `SubmissionRecord` instances and re-launch submission tasks to the LLM pipeline

For each `SubmissionPeriodRecord` instance, you should display the following information:

- the number of `SubmissionRecord` instances that are MISSING metric/LLM data
- the number of `SubmissionRecord` instances where an "AI risk" flag was raised
- The mean, standard deviation, inter-quartile range, maximum and minimum values for the following metrics:
    - lexical diversity metrics MATTR, MTLD, burstiness R, CV
    - number of pages detected in the PDF
    - number of words detected in the PDF
    - number of references detected in the PDF
- If there are 25 or more `SubmissionRecord` instances in the set being displayed, use Bokeh to generate a binned
  histograp showing the distribution for each of these metrics over the set. Format these attractively with correctly
  labelled axes.

The dashboard allows LLM-pipeline submission orchestration tasks to be launched.

- The dashboard should include a panel (probably at the top) showing the number of submission tasks currently in the
  queue, the number that have been successfully completed, and the number that failed with an error state. It should
  report the mean time taken by the LLM grading and LLM feedback tasks, together with their maximum and minimum values.
- On loading, the dashboard will need to populate this queue, which should likely be done by querying Celery to find
  which tasks have been submitted to a work queue or are currently in progress.
- When subsequent orchestration actions add tasks to the queue, the status panel should update to accommodate them. In
  the Option B scenario described above, where a separate Celery task performs orchestration of LLM submission, this
  will require the task to make its job queue available for inspection, perhaps by persisting it to the database. Redis
  is also available as a temporary cache if that provides a better solution.

The data dashboard itself should update when tasks finish and exit the work queue. Please also include a manual "Reload"
button that refreshes the dashboard, in case an automatic update is not triggered.

At each level (`SubmissionPeriodRecord`, entire `ProjectClassConfig`, entire `MainConfig` cycle, globally) include a
button to download (1) a CSV file, and (2) an Excel file, containing the data for the set being displayed. For each
`SubmissionRecord`, emit a row containing: (1) an anonymized identifier (which should be stable across multiple export
events; the `SubmissionRecord` id field is one canddidate), (2) the MATTR, MTLD, burstiness R, CV metrics; (3) page
count from the PDF, (4) word count from the PDF, (5) number of references detected in the PDF, (6) and grade
information (supervision, report, presentation) stored on the `SubmissionRecord` instance.

The generated CSV or Excel file should be prepared by a Celery background task. It should be named according to the
following scheme: "<year>_<pclass_identifier>_<period_identifier>_AI_dashboard_data.csv" (or ".xlsx").
Here:

- <pclass_identifier> should be the project class `abbreviation` where only one project class is selected, or
  "all_pclasses" if all project classes are selected. If more than one pclass is selected but not all,
  use "n_pclasses", where n is the number of selected project classes.
- <period_identifier> should be the `SubmissionPeriodRecord` display name where only one period is selected,
  or "all_periods" if all periods are selected. If more than one period is selected but not all, use "n_periods",
  where n is the number of selected periods.

The generated file should be uploaded to the "project" object bucket and persisted in the database as a `GeneraedAsset`.
Link this asset to the user's Download Centre and emit a notification when the file is ready. Look at existing code
using the Download Centre to see the implementation pattern here.  