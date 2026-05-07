The backend now supports multiple `TenantAICalibration` objects per tenant.
We need to update the UI in two areas:

### Calibration management (admin):

- Replace the single calibration status on the tenant list with a summary
  showing count of calibrations (e.g. "2 calibrations")
- Replace the single calibration detail page with a table of calibration
  objects, one row per TenantAICalibration, showing feature_set, LLM
  config, sample count, years, and status
- It should be possible to add calibrations to the table.
  The user should be able to select a (LLM, context window) pair,
  a group of project classes, and a group of years, from which the calibration
  will be built. Validate project class exclusivity
- It must be possible to delete calibrations, so that the project classes
  involved can be "freed up" for use in a different combination, if desired
- The "Run calibration" flow should: (a) first query distinct LLM
  configurations found in stored submission data for this tenant,
  (b) present these alongside the existing project class / year selectors,
  (c) validate pclass exclusivity before submitting
- The recalculation page should show which calibrations will be applied
  and the resulting Bonferroni-corrected per-test threshold

The recalculation page needs to show a table something like the following:

```
Calibration objects — Physics & Astronomy

  Type          LLM config          Samples  Years        Status
  ──────────────────────────────────────────────────────────────
  Lexical (3D)  —                   148      2019–2021    ✓ Calibrated 2026-04-13
  Full (5D)     qwen2.5:32b         94       2023–2025    ✓ Calibrated 2026-04-13
  Full (5D)     llama3.1:8b         12       2025         ⚠ Too few samples
```

The table should also include the project classes included (referred to by
their abbreviations to keep it concise, and the size of the LLM context window.

### Per-submission LLM report view:

- In the "AI use metrics" section, add a "Predictability metrics"
  subsection (shown only if NLL data is present) displaying mean_nll
  and nll_cv with a gauge similar to the existing MATTR display
- Add an "AI concern assessment" table showing one row per calibration
  evaluated, with sigma, p-value, and low/medium/high classification,
  plus the corrected alpha used
- The overall concern badge (currently shown in the submitter list)
  should reflect the worst-case across all evaluated calibrations

The intended layout is roughly:

```
LEXICAL DIVERSITY METRICS
  [existing MATTR gauge]
  [existing hedging/filler/em-dash row]

PREDICTABILITY METRICS  (shown only if NLL data available)
  Model: llama3.1:8b · Context: 12,288 tokens
  [mean NLL gauge, similar style to MATTR]
  NLL variability (CV): 0.34   ── low variability, consistent with AI-generated text

AI CONCERN ASSESSMENT
  ┌─────────────────────────────────────────────────┐
  │ Lexical          σ = 1.82   p = 0.12   ● Low    │
  │ Predictability   σ = 3.41   p = 0.008  ● High   │  ← drives overall flag
  │ Corrected α: 0.025 per test (Bonferroni, K=2)   │
  └─────────────────────────────────────────────────┘
  Overall: ● Medium concern
```
