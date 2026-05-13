## Summary

The trigger for production of a `SimilarityConcern` record during operation of the similarity
pipeline in `app/tasks/similarity_analysis.py` is being changed.

Currently, this is a 2-step process. First, MinHash values are computed and cached for each chunk
that is extract. When comparing pairwise, a MinHash LSH estimate of the Jaccard similarity is
produced. This is used to gate any further similarity analysis. Currently the threshold is set
to 0.15.

The submissions in our corpus show very little evidence of literal copying, of the type that would
be detected by a Jaccard similarity. All comparisons produce very low values, so the second step
of the process never runs. The second step is based on semantic comparison using `sentence-transformers`.
The result is that a number of submissions with large cosine similarity are not being detected.

Since these steps are performing different functions, there is no need to chain them. They should
both run.

A `SimilarityConcern` should be generated for any chunk where **either** one of the cosine
similarity thresholds fires, **or** the Jaccard similarity exceeds 0.05.
`SimilarityConcern` now needs a flag to indicate which was the trigger (or both).
We are unlikely to add further triggers, so adding suitable boolean flags may be reasonable,
but you may consider other approaches if you consider them to be preferable.
The `SimilarityConcern` should also carry metadata indicating which `sentence-transformers`
model was used.

Currently, MinHash hashes are stored in the MongoDB document cache, but not the embedding
vector produced by `sentence-transformrers`. Computing the embedding is the expensive step
in any similarity comparison, so this should also be cached. It should be gated by the current
prompt version, as before. However, you will also need to store the name of the `sentence-transformers`
model as metadata, so that we only every perform apples-to-apples comparisons.
There is no need to discard cached values that belong to a model other than the one currently
in use, unless the prompt version has changed, in which case all cached chunk-level
data should be dropped as before.

Both the cosine similarity and the Jaccard similarity should both be stored on `SimilarityConcern`
and shown in the user interface where cosine similarity values are surfaced.
On the similarity dashboard this will require a new orderable column.
The similarity dashboard should report the `sentence-transformers` model used to compute the
cosine similarity as a small context cue in that column. Do not add a new column just for this.

Both the cosine similarity and the Jaccard similarity should be reported on the detail card
and on the detail view `similarity_concern_detail.html` and the risk factor card
`_similarity_risk_factor_card.html`. Do not privilege one similarity score above the other;
present them as parallel, independent measurements at the same level of important.

On `similarity_concern_detail.html` and `_similarity_risk_factor_card.html`,
hardcoded values for the cosine similarity are used
to determine UI elements. These are decoupled from the actual threshold values used in
`app/tasks/similarity_analysis.py`. There should be a single source of truth for these
values that is used in the template and in `app/tasks/similarity_analysis.py`.
The values that are reported as elevated or highly elevated should vary by chunk type,
because the thresholds also vary by chunk type.

Please make a recommendation as to whether it is advisable to allow the `sentence-transformers`
model to be set by a configuration variable, in the same way the LLM model is. Not all
`sentence-transformers` models can be used with the same adapter structure, so this may or may
not be sensible.

The default `sentence-transformers` model should be switched to `all-mpnet-base-v2`.
However, we would like to allow at least `all-MiniLM-L6-v2` as a configuration option, if possible.