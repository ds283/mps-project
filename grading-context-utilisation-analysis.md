# Grading context-window utilisation analysis

*Written 2026-05-11 following commit 2daada37 (calibrate `_TOKENS_PER_WORD_CONTENT` to 1.5).*

---

## Observed values

Production data from the first post-patch batch (FYP MPhys, 2020 cohort):

| Record | Student | Chunks | Peak prompt tok | Peak ctx% | Peak completion tok |
|---|---|---|---|---|---|
| 427 | Micah Annor | 3 | 10 320 | 56.0% | 634 |
| 433 | Jessica Iraclides | 3 | 9 744 | 52.9% | 878 |

Context size: 18 432 tokens throughout.

---

## Why 53–56% and not higher

The chunk budget ceiling is:

```
chunk_word_budget = int((context_size − _map_overhead) / _TOKENS_PER_WORD_CONTENT × 0.85)
```

where `_map_overhead = _chunk_prompt_tokens + _map_response_tokens`.

With typical values for a 12-criterion FYP rubric:

| Parameter | Value | Source |
|---|---|---|
| `_chunk_prompt_tokens` | ≈ 3 280 tok | `_build_chunk_system_prompt(...)` ≈ 2 050 words × 1.6 |
| `_map_response_tokens` | 3 140 tok | `max(1200, 500 + 12 × 220)` |
| `_map_overhead` | **6 420 tok** | sum |
| `chunk_word_budget` | **≈ 6 800 words** | `int((18432 − 6420) / 1.5 × 0.85)` |

For a 15 000-word FYP MPhys submission (3 chunks of 5 000 words each):

```
5 000 words × 1.44 t/w (actual content) = 7 200 content tokens
system prompt actual:  2 050 words × 1.30 t/w = 2 665 tokens
peak prompt total:     7 200 + 2 665 = 9 865 tokens
context pressure:      9 865 / 18 432 = 53.5%
```

This matches the observed 53–56%. **The context pressure is set by submission length, not by
the budget formula.** The FYP MPhys submissions in this sample are shorter than the budget
ceiling allows (~15 000 words ÷ 3 chunks = 5 000 words/chunk vs a ceiling of ~6 800 words).

---

## What the 2.0 → 1.5 t/w patch changed

Before the patch, the budget ceiling was:

```
old_chunk_word_budget = int((18432 − 6420) / 2.0 × 0.85) ≈ 5 100 words
```

A 15 000-word submission therefore required ⌈15 000 / 5 100⌉ = **3 chunks**, each ≈ 5 000 words.

After the patch the ceiling is ≈ 6 800 words. The same submission still fits in **3 chunks**,
each ≈ 5 000 words, because 5 000 < 6 800.

For a longer submission (≈ 20 000 words, e.g. FYP MPhys with extensive appendices):
- **Before:** ⌈20 000 / 5 100⌉ = 4 chunks
- **After:** ⌈20 000 / 6 800⌉ = 3 chunks  ← one LLM call saved (~200–350 s)

The patch's primary benefit is **chunk count reduction for medium-length submissions**, not
higher per-chunk context pressure.

---

## Completion token reservation: current vs actual

`_map_response_tokens` reserves space in the context window for the model's grading output:

```python
_map_response_tokens = max(1200, 500 + n_criteria * 220)
# For n_criteria = 12: max(1200, 3140) = 3140 tokens
```

Actual peak completion tokens from production:

| Record | Chunks | Peak completion | Tokens/criterion (peak chunk) |
|---|---|---|---|
| 427 | 3 | 634 | 53 |
| 433 | 3 | 878 | 73 |

The formula reserves **3 140 tokens** when the observed peak is **634–878 tokens** —
a factor of **3.6–5.0× overestimate**.

---

## Opportunity: reduce `_map_response_tokens`

If the reservation is reduced from 3 140 to ≈ 1 400 tokens (still 1.6× the observed peak
of 878 with safety margin), the budget ceiling increases:

```
new_map_overhead    = 3 280 + 1 400 = 4 680 tokens
new_chunk_word_budget = int((18432 − 4680) / 1.5 × 0.85) ≈ 7 800 words
```

Impact for a 15 000-word submission (currently 3 chunks):

```
⌈15 000 / 7 800⌉ = 2 chunks of 7 500 words
peak prompt:  7 500 × 1.44 + 2 665 = 13 465 tokens → 73% context pressure
```

73% is safely below the 85% amber threshold. This change would save **one LLM call per
15 000-word submission** (~200–350 s wall-clock time and the associated API cost).

For a 20 000-word submission:

```
⌈20 000 / 7 800⌉ = 3 chunks of 6 667 words → 73% context pressure
```

Still 3 chunks (same as now), but each chunk is larger (higher quality analysis, more context
visible to the model per call).

---

## Proposed revised formula (deferred)

```python
# Before
_map_response_tokens = max(1200, 500 + n_criteria * 220)

# After — calibrated from empirical peak completion data
_map_response_tokens = max(1400, 300 + n_criteria * 100)
```

| n_criteria | Current | Proposed | Observed peak |
|---|---|---|---|
| 6 | 1 820 | 1 400 | — |
| 12 | 3 140 | **1 500** | 878 |
| 18 | 4 460 | **2 100** | — |

The floor rises from 1 200 to 1 400 to maintain a ≥1.6× safety margin at the observed 878-token
peak. The per-criterion coefficient drops from 220 to 100, reflecting that map-phase chunks
only surface evidence for ~4 out of 12 criteria (the ones actually present in each chunk).

---

## Recommendation

**Do not implement the revised formula yet.** Only 2 post-patch records with
`peak_completion_tokens` data are available. The per-criterion completion rate will vary with
rubric structure, submission quality, and model behaviour. Collect 15–20 records before
recalibrating; the current over-reservation is conservative but not harmful.

**Revisit when:** `peak_completion_tokens` is populated for ≥15 post-patch records (expected
within 2–3 weeks at current processing rate). If the 634–878 range holds broadly, implement
the revised formula.

---

## Summary

| Question | Answer |
|---|---|
| Is 53–56% context pressure sufficient? | Yes — it reflects submission length, not formula inefficiency |
| What determines context pressure per chunk? | Submission word count ÷ chunk count |
| Why not higher? | `_map_response_tokens` reserves 3 140 tok when actual peak is 634–878 |
| Is the current state wasteful? | For typical ~15 000-word submissions: no. For ~20 000-word submissions it costs one extra LLM call vs what's achievable |
| When to act? | After 15+ records with `peak_completion_tokens` data |
