## SUMMARY

As part of the marking cycle, we would like to perform analysis of submitted PDF reports. There are three primary
purposes.

The first is to obtain some metrics that are explicitly part of the marker criteria, or which can be provided to markers
to guide their analysis. These include:

- word count: projects have a word limit. Currently, we ask students to estimate a word count and include it in the
  report
- number of references in the bibliography/reference list
- number of figures and tables
- whether all references are actually cited in the text of the report, and if not, which ones
- whether all figures and tables are actually referenced in the text of the report, and if not, which ones

A second reason is to help us identify the extent to which generative AI is being used to produce reports. To do this,
we'd like to estimate some language-based metrics that might be diagnostic of AI use. These include:

- MATTR
- MTLD
- burstiness measures

The third is to test whether a local LLM can provide guidance to human markers by determining how well each report
matches a set of indicative criteria defining grade bands.

### GENERAL CONSIDERATIONS

In planning this implementation, you should prefer to use existing Python libraries for PDF parsing, computing language
metrics, and handling submission of prompts to LLMs.

For PDF parsing, the PyMuPDF library is already used in the project. You can recommend using other PDF libraries for PDF
handling if you consider them to have clear advantages.

Celery tasks implemented as part of this feature should run on a separate Celery task queue labelled `llm_tasks`.
This is because jobs involving LLM submission particularly may be long-running, and we wish to avoid blocking the main
Celery task queue. LLM tasks must **only** run on this queue.

The Celery chain should route tasks explicitly using si() signatures with queue specified for each step. Statistical
tasks should be routed to the default queue; extraction and LLM tasks to llm_tasks. Do not rely on automatic queue
routing for cross-queue chains.

Run PDF download and text extraction on the llm_tasks queue alongside the LLM submission task, since these involve file
I/O and may be slow. Run purely statistical computation (MATTR, MTLD, burstiness, pattern matching) on the default
queue. Use a Celery chain to sequence these stages.

This is a large implementation task. Completion may span multiple rate limit windows. The status file should be named
LANGUAGE_ANALYSIS_IMPLEMENTATION.md at the repository root. Structure it with sections: Completed, In Progress, Pending,
Decisions Made, and Known Issues. Update it after completing each major component. Record any architectural decisions
made during implementation, particularly where the spec was ambiguous.

### LANGUAGE ANALYSIS WORKFLOW

The desired language analysis workflow is as follows. This should all be implemented as a Celery workflow operating on a
`SubmissionRecord` instance.

Eventually, this analysis step will take place **before** production of the processed report. The processed report will
then include some of the metadata and information obtained during this analysis. You must NOT use
`SubmissionRecord.processed_report` during this workflow.

- The asset corresponding to the `SubmissionRecord.report` should be downloaded to the container's ephemeral filesystem.
- The text content should be extracted. In particular:
    - The asset may be a single PDF document produced by LaTeX. We cannot assume that the LaTeX source is available.
      Generally, we only have the PDF to work with.
    - The asset may be a Word document.

- The text content of the asset should be extracted. For PDF this can perhaps be done using PyMuPDF, which is already
  part of the project, but you may consider other libraries where appropriate.
- The extracted text needs to be cleaned, as far as possible, to remove unwanted content
  from headers, footers, and page numbers.
- Word document text extraction should use python-docx. Apply the same cleaning and analysis pipeline as for PDF. If
  Word document support is complex to integrate, implement it as a stub that can be completed later, and note this in
  the status file.
- Perform a word count. Exclude (as far as possible) content that comes from figure or table captions, and from the
  bibliography or reference list. The word count is only intended to be an estimate, so it is understood that this
  procedure will be inexact. This word count will need to be persisted in the database, perhaps as part of a JSON
  structure.
- Identify the bibliography or reference section and count how many entries it contains.
- Determine (approximately) whether all these references are actually cited in the main text. This may only be easily
  possible for PDFs produced from LaTeX, where references usually occur in a characteristic format. Prepare a list of
  references that do not appear to be cited in the text, so these can be reported later. The list will also need to be
  persisted, again, possibly, as part of a JSON structure.
- Determine (approximately) whether all figures and tables are actually referenced in the main text by pattern matching
  for "figure <number>" "fig. <number>" and "table <number>". Prepare a list of figures and tables that may not be
  referenced in the text. These lists will need to be persisted, so they can be surfaced to markers later.
- Compute the MATTR and MTLD metrics for the entire text. Prefer to use existing Python libraries for this. You may
  consider the 'lexicalrichness' library, but you can also consider alternatives. These metrics will need to be
  persisted in the database. Use a 50-word window (=lexicalrichness default)

Please also compute the Goh and Barabási "burstiness" metric for the following comma-separated groups of words. The text
should be lemmatised for these groups so that simple changes of inflectional forms are not counted as different words.

- suggest, suggests, suggested
- indicate, indicates, indicated
- demonstrate, demonstrates, demonstrated
- show, shows, showed, shown
- appear, appears, appeared
- estimate, estimates, estimated
- assume, assumes, assumed
- imply, implies, implied
- significant, insignificant
- important, relevant
- consistent, inconsistent
- unexpected, surprising
- clear, unclear
- compare, compared, comparing
- contrast, differ, differs
- agree, disagree, confirm, confirms
- support, supports, contradict

Words with fewer than 8 occurrences in the document should be excluded from the calculation for that document, as the
inter-arrival distribution is too sparse to be meaningful.

Compute an aggregate "bustiness" metric by averaging over all the above groups. Persist this burstiness metric in the
database.

Add classification flags to indicate where the MATTR, MTLD and burstiness metrics are outside the following fiducial
ranges. These ranges may themselves need to be configurable on a ProjectClass basis, but for the moment use the
following values:

| Metric         | Typical human academic | Worth noting | Stronger flag |
|----------------|------------------------|--------------|---------------|
| MTLD           | 80–120                 | < 70         | < 50          |
| MATTR (w=50)   | 0.70–0.85              | < 0.68       | < 0.60        |
| Burstiness (B) | 0.20–0.60              | < 0.20       | < 0.10        |

Add a flag for each metric.

You should also add an overall "AI concern" classification flag for the report based on the number of metrics that are
outside the standard ranges. Do not flag reports where only one metric is at an elevated level; at least two metrics
should be above the standard range. Classify using the bands "low" (all metrics in standard range, or only one metric
outside range), "medium" (more than one metric outside the standard range), and "high" (all three metrics outside the
standard range, or two at the higher level).

Please also compute the rate of ocurrence of the following specific patterns in the text. Current LLMs have
characteristic tendencies that are measurable with simple pattern matching. Please produce counts of
these:

- Use of hedging phrases:
    - it is important to note that
    - it is worth noting that
    - it is crucial to note that
    - it should be noted that
    - needless to say
    - it goes without saying that
    - as mentioned above
    - as noted above
    - as discussed previously
    - it is interesting to note that
    - significantly, importantly
    - fundamentally, essentially, basically
    - it is clear that, clearly
    - obviously, evidently
    - of course, naturally
- Transitional filler phrases
    - furthermore
    - moreover
    - in conclusion
- The em-dash used as a stylistic separator: current models overuse this noticeably

Do NOT use these counts in the "AI concern" classification. You should ONLY compute the number of times these patterns
occur, and record the result.

In a second step (perhaps a separate Celery task to break the task up), we wish to submit the scraped text to an LLM
via the ollama REST API. Consider using "ollama-python" to abstract this. The API base URL and LLM model identifier
should be configurable and provided as part of the Celery task setup. They will likely be determined within the app by
environment variables set in docker-compose.yml.

Use streaming responses to keep the connection alive during long inference and to allow progress to be written
incrementally. Accumulate streamed tokens into a complete response string before attempting JSON parsing.

You should expect the target LLM to be of 32B or 70B type. You should expect typical documents submitted for analysis to
be in the range of 20 to 50 PDF pages, with 40 pages being typical.

A 40-page document may contain 15,000–20,000 words. For models with a 32k token context window this is feasible but
tight when combined with the rubric and output schema. Submit the full document text in a single prompt. If the text
exceeds 12,000 words, truncate to the first 6,000 and last 6,000 words, noting this truncation in the caveats field of
the output. Do not chunk the document across multiple LLM calls for the rubric assessment.

Use a system prompt for the rubric and instructions, and the user prompt for the document text. This is better practice
and uses the context window more efficiently.

When truncating, insert a clear marker in the text between the two sections, such
as "[... middle section omitted due to length ...]", so the LLM is aware the text is not continuous.
Include a note in the system prompt that the document may be truncated.

The LLM should be asked to evaluate the text against a rubric which gives indicative criteria for a number of grade
bands. The crtieria for these bands may vary by ProjectClass, but initially they will all be the same. The model should
be asked to recommend a classification band, and to provide evidence for each of the criteria.

Currently, the list of bands we would like to consider is given below. However, the list of criteria should not be
hardcoded but needs to be extensible and easy to change. The bands are ordered in order of quality from lowest to
highest.

- 3rd class
    - Scientific work of limited quality
    - Demonstrates some relevant knowledge and understanding, with limitations
    - Limited evidence for technical and practical skills
    - At least some attempt to explain and interpret the results of the project
    - Report shows evidence of at least some editing and proof-reading
- 2.2 class
    - Scientific work of competent quality
    - Demonstrates reasonable understanding and analysis; competent technical or practical skills; some organizational
      and presentation skills
    - Report edited and proof-read to a competent standard
    - Report is structured into chapters, but parts of the organization may be unclear
    - Explanations mostly adequate
- 2.1 class
    - Demonstrates very good understanding and analysis; very good technical or practical skills; very good
      organizational and presentation skills
    - Report edited, typeset, and proof-read to a good standard
    - Text mostly in a good scientific style
    - Partial assessment of wider significance of the results
    - Partial discussion of relation to previously published work, if appropriate
    - Explanations are clear and not verbose
    - Sources of error in techniques, approximations or methodologies are mostly considered
    - Some discussion future directions or improvements
- 1st class
    - Demonstrates excellent understanding and analysis; excellent technical or practical skills; excellent
      organizational and presentation skills
    - Report edited, typeset, and proof-read to a high standard
    - Text is written in a good scientific style
    - Clear assessment of wider significance or context of the results
    - Relation to previously published work is explained, if appropriate
    - Explanations are clear and succinct
    - Sources of error in techniques, approximations or methodologies are considered
    - Clear, well-defined suggestions for future directions or improvements

The prompt must explicitly state: "Each higher grade band subsumes all criteria of lower bands. A submission cannot be
awarded a higher band unless it substantially satisfies the criteria of all lower bands. Assess against the highest band
whose full set of criteria, including those of all lower bands, are mostly satisfied."

Use ollama's format='json' parameter on all LLM API calls to constrain output to valid JSON. Additionally, provide the
expected JSON schema in the prompt itself. Implement a retry mechanism with a maximum of three attempts. On persistent
failure, store the raw LLM response alongside the failure notice so it can be inspected by an administrator.

On retry, use identical prompt and parameters. Add a brief delay between retries (suggest 5 seconds) to avoid hammering
the ollama service.

Treat network errors and malformed JSON as retryable. Treat HTTP 4xx errors from the ollama service as permanent
failures. A response that is valid JSON but does not conform to the expected schema should be treated as a parsing
failure after all retries are exhausted.

If JSON parsing fails after retries, store the raw text response in the database rather than discarding it. Surface this
to the administrator as a parsing failure rather than an inference failure, since the raw text may still contain useful
information.

In considering how to build the prompt, you should consider the following:

- Ask the model to assess each criterion individually, with brief textual evidence from the document
- Ask for a classification with explicit reasoning, not just a label
- Explicitly instruct the LLM to note where it is uncertain or where the text doesn't provide enough evidence
- Ask the model to flag which criteria the model considers itself less able to assess reliably from
  text alone. The model can note "this criterion relates to visual presentation which cannot be fully assessed from
  extracted text" rather than guessing.

It would be helpful if the model could cite specific passages in its reasoning. This makes the output auditable by a
human reader, who can check whether the model's evidence actually supports its conclusion.

A well-prompted response might return something like:

- Per-criterion: a one- or two-sentence assessment with a confidence indicator (strong evidence / partial evidence / not
  evident)
- Overall: a suggested band with a short paragraph of reasoning
- Caveats: explicit flags where the model felt uncertain

You may wish to consider a possible JSON output structure of the form given below, but you may adjust this if you feel
it is preferable.

```json
{
  "classification": "2.1 class",
  "overall_reasoning": "...",
  "criteria": [
    {
      "criterion": "Explanations clear and not verbose",
      "assessment": "Strong evidence",
      "commentary": "The discussion section explicitly situates...",
      "confidence": "high"
    },
    ...
  ],
  "caveats": "..."
}
```

`SubmissionRecord` instances that have been marked as producing an LLM failure should not be retried until the status
flag is explicitly cleared by a human administrator. You will need to produce UI elements in order to allow this.

Please attempt to design the Celery workflows so that they are robust to failure and can be retried safely.

Make suitable changes to the database models to capture all the results identified above.
Add a single `language_analysis` JSON column to SubmissionRecord to store all metrics, flags, and LLM output. Use a
top-level structure with keys `metrics`, `flags`, `patterns`, `llm_result`, and `errors`. This allows new metrics to be
added without schema migrations. Add a separate boolean column `llm_analysis_failed` and a text column
`llm_failure_reason` for explicit failure state tracking, since these will need to be queried directly.

Errors during any workflow stage should be caught, serialised, and written to the `errors` key of the
`language_analysis` JSON column. Include the stage name, exception type, and message. Non-LLM errors should not set
`llm_analysis_failed`; that flag is reserved specifically for LLM inference and JSON parsing failures.

### SURFACE THESE RESULTS IN THE WEB INTERFACE

Where language metrics are available, please surface a concise summary of these in the UI. This could be done in the
project_tag() macro in @app/templates/convenor/submitters_macros.html. Key information would be the LLM's grade band
assessment, and the MATTR, MTLD and burstiness metrics. If the LLM's assessment is not available because of a workflow
failure, please note this.

To make the remining information accessible to a user of the web app, use an offcanvas popover to display the
full results, including the LLM's reasoning and confidence. Add UI elements to visualize the LLM's confidence measures.

You will need to parse the JSON output from the LLM and format the result attractively using Jinja2 markup and HTML
elements.

For the offcanvas popover, use the existing Bootstrap offcanvas component patterns already present in the project.
Display per-criterion confidence using coloured badge elements: green for "strong evidence", amber for "partial
evidence", red for "not evident". The overall grade band recommendation should be displayed prominently. Flag criteria
the model was uncertain about with a distinct visual treatment.

The action button to launch analysis should trigger a Celery task and return immediately. Do not make the user wait
for the result.

### ADD UI ELEMENTS TO LAUNCH TASK PROCESSING

- Add a UI element (action button) on the submitter_manager.html template to launch language analysis for the associated
  report. Show this control only when a report is actually uploaded.
- If language results are already stored in the database, include a summary of them on theis page. Include an action
  button to clear these results and re-launch the analysis.
- If there are no language results stored in the database, include a (small) action button in the project_tag() macro
  to launch the analysis.