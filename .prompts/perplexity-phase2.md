The `TenantAICalibration` model is now in place. We need to:

1. Add NLL perplexity computation to `language_analysis.py`:

    - Add `_compute_chunk_nll(chunk_text, ollama_url, model) -> float | None`
      Returns mean negative log-likelihood per token (base e). Use the
      existing Ollama `/api/generate` endpoint with `logprobs=True`. Work in
      log space throughout — do not exponentiate to perplexity.

    - Add `_aggregate_nll(chunk_nlls) -> dict | None`
      Returns `{"mean_nll": float, "nll_cv": float}` where `nll_cv` is the
      coefficient of variation across chunks. Require at least 2 chunks.

    - Wire these into the existing map-reduce LLM pipeline. NLL should be
      computed in the map phase alongside evidence extraction, and aggregated
      in the reduce phase. Store mean_nll and nll_cv on the SubmissionRecord
      alongside the existing lexical metrics.

2. Update `_ai_concern_flag` to accept an optional `TenantAICalibration` list
   rather than a single calibration dict. For each calibration:
    - If `feature_set == "lexical"`, use (MATTR, MTLD, sentence_cv)
    - If `feature_set == "full"`, use (MATTR, MTLD, sentence_cv, mean_nll,
      nll_cv) only if the submission's LLM model matches the calibration's
      `llm_model_name` and `llm_context_window`
      Apply Bonferroni correction: per-test alpha = 0.05 / K where K is the
      number of calibrations actually evaluated. Fire the flag if any test
      exceeds its corrected threshold.

3. Update the calibration task to write `TenantAICalibration` rows via
   `get_calibration()` / upsert rather than the old blob setter.

Key constraint: mean NLL is a property of the scoring model, not the text
alone. Always store and match on `(llm_model_name, llm_context_window)` when
reading or writing NLL-derived values.
