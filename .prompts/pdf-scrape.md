## SUMMARY

As part of the marking cycle, we would like to perform analysis of submitted PDF reports. There are three primary
purposes.

The first is to obtain some metrics that are explicitly part of the marker criteria, or which can be provided to markers
to guide their analysis. These include:

- word count: projects have a word limit. Currently, we ask students to estimate a word count and include it in the
  report
- number of references in the bibliography/reference list
- number of figures and tables
- whether all referenecs are actually cited in the text of the report
- whether all figures and tables are actually referenced in the text of the report, and if not, which ones

A second reason is to help us identify the extent to which generative AI is being used to produce reports. To do this
we'd like to estiamte some language-based metrics that might be diagnostic of AI use. These include:

In planning this implementation, you should prefer to use existing Python libraries for PDF parsing, computing language
metrics, and handling submission of prompts to LLMs.

- MATTR
- MTLD
- burstiness measures

The third is to test whether a local LLM can provide guidance to human markers by determining how well each report
matches a set of indicative criteria defining grade bands.

For PDF parsing, the PyMuPDF library is already used in the project. You can recommend using other libraries if you
consider them to be suitable.

### GENERAL CONSIDERATIONS

Celery tasks implemented as part of this feature should run on a separate Celery task queue labelled `llm_tasks`.
This is to avoid blocking the main Celery task queue. LLM tasks must **only** run on this queue.

It's possible that shorter tasks to perform text scraping and statistical analysis could also run on the default queue.
Please consider the architecture and make a recommendation.

This is a large implementation task. Completion may span multiple rate limit windows. Please write a status file to disk
at the top level of the repository, and update it periodically as you work.

### REPORT ANALYSIS WORKFLOW

The desired workflow is as follows. This should all be implemented as a Celery workflow operating on a
`SubmissionRecord` instance.

Eventually this analysis step will take place **before** production of the processed report. The processed report will
then include some of the metadata and information obtained during this analysis. You must not used
`SubmissionRecord.processed_report` during this workflow.

Design a mechanism to capture errors that occur during the workflow, so they can be surfaced to an administrator later
via the web interface.

- The asset corresponding to the `SubmissionRecord.report` should be downloaded to the container's ephemeral filesystem.
- The text content should be extracted. In particular:
    - The asset may be a single PDF document produced by LaTeX. We cannot assume that the LaTeX source is available.
      Generally, we only have the PDF to work with.
    - The asset may be a Word document.

- The text content of the asset should be extracted. For PDF this can perhaps be done using PyMuPDF, which is already
  part of the project, but you may consider other libraries where appropriate.
- For text scraped from a PDF, the extracted text needs to be cleaned, as far as possible, to remove unwanted content
  from headers, footers, and page numbers.
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

Please also compute the Goh and Barabási "burstiness" metric for the following groups of words. The text should be
lemmatised for these groups so that simple changes of inflectional forms are not counted as different words.

- suggest, suggests, suggested
- indicate, indicates, indicated
- demonstrate, demonstrates, demonstrated
- show, shows, showed, shown
- appear, appears, appeared
- estimate, estimates, estimated
- assume, assumes, assumed
- imply, implies, implied
- significant, significant
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

Please consider the database schema changes needed to persist all this information on the `SubmissionRecord` instance.
We are unlikely to need to query by any of these metrics, and for forward compatibility it may be helpful if
the layout is extensible (e.g. extra metrics can be added cheaply later). This may suggest serialization of a JSON
structure.

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
    - as mentioned above, as noted above
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
occur in the text.

In a second step (perhaps a separate Celery task to break the task up), we wish to submit the scraped text to an LLM
via the ollama REST API. Consider using "ollama-python" to abstract this. The API base URL and LLM model identifier
should be configurable and provided as part of the Celery task setup. They will likely be determined within the app by
environment variables set in docker-compose.yml. Consider using streaming responses to improve load balancing and reduce
the risk of a timeout.

You should expect the target LLM to be of 32B or 70B type. Carefully consider how the prompt (or sequence of prompts)
should be engineered to account for the LLM's context window. Ask for guidance if you're unsure.

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

In constructing the prompt, instruct the LLM that each higher band subsumes the criteria of lower bands.
The LLM should assess against the highest band whose criteria are mostly satisfied.

In considering how to build the prompt, you should consider the following:

- The prompt should require JSON structured output so that the result is easily parseable downstream
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

Please consider how best to enforce the JSON output structure. Consider what fallback options exist if the output from
the LLM cannot be interpreted. A valid strategy is simply to retry the analysis a certain number of times, or simply to
report failure. Failure notices would have to be persisted in the database so they can be surfaced to the administrator
in the web interface.

`SubmssionRecord` instances that have been marked as producing an LLM failure should not be retried until the status
flag is explicitly cleared by a human administrator. You will need to produce UI elements in order to allow this.

Please attempt to design the Celery workflows so that they are robust to failure and can be retried safely.

### SURFACE THESE RESULTS IN THE WEB INTERFACE

Where language metrics are available, please surface a concise summary of these in the UI. This could be done in the
project_tag() macro in @app/templates/convenor/submitters_macros.html. Key information would be the LLM's grade band
assessment, and the MATTR, MTLD and burstiness metrics.

To make the remining information accessible to a user of the web app, consider using an offcanvas popover to display the
full results, including the LLM's reasoning and confidence. Add UI elements to visualize the LLM's confidence measures.

You will need to parse the JSON output from the LLM and format the result attractively using Jinja2 markup and HTML
elements.

### ADD UI ELEMENTS TO LAUNCH TASK PROCESSING

- Add a UI element (action button) on the submitter_manager.html template to launch language analysis for the associated
  report. Show this control only when a report is actually uploaded.
- If language results are already stored in the database, include a summary of them on theis page. Include an action
  button to clear these results and re-launch the analysis.
- If there are no language results stored in the database, include a (small) action button in the project_tag() macro
  to launch the analysis.