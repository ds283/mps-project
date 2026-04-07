#
# Created by David Seery on 07/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# ---------------------------------------------------------------------------
# Classification thresholds and functions for LLM/AI-indicator metrics.
#
# This is the single authoritative source.  All classification logic and
# display code must import from here rather than defining local copies.
#
# ---------------------------------------------------------------------------
# METRIC DESCRIPTIONS AND RATIONALE
# ---------------------------------------------------------------------------
#
# ── MATTR (Moving Average Type-Token Ratio) ─────────────────────────────────
#
# MATTR measures lexical diversity by computing the type-token ratio within a
# sliding window of W consecutive tokens, then averaging across all windows.
# Window size W=100 is the conventional choice in the literature.
#
# Human academic text typically falls in the range 0.70–0.85.  Values below
# this range suggest limited vocabulary (consistent with repetitive or
# AI-generated text where the model recycles the same words).  Values
# significantly *above* 0.85 can also be suspicious: LLMs occasionally
# produce inflated lexical diversity by packing in unusual synonyms or
# over-varying vocabulary in ways untypical of natural academic prose.
# The literature is split on whether the high tail is truly diagnostic, so
# the upper bound is treated as a softer "noteworthy" flag only.
#
# Thresholds (human normal range: 0.70–0.85):
#   < MATTR_STRONG_THRESHOLD (0.60)      → strong concern (low)
#   < MATTR_NOTE_LOW_THRESHOLD (0.70)    → noteworthy (low)
#   > MATTR_NOTE_HIGH_THRESHOLD (0.85)   → noteworthy (high; softer flag)
#
# ── MTLD (Measure of Textual Lexical Diversity) ──────────────────────────────
#
# MTLD computes the mean length of sequential text runs over which the
# type-token ratio stays above a threshold (default 0.72).  It is considered
# more robust than TTR or MATTR to text length effects.  MTLD requires at
# least ~100 words of text to be numerically stable; results from shorter
# texts should be treated with caution and are suppressed here.
#
# Human academic text typically falls in the range 70–120.  Very low values
# suggest a repetitive, narrow vocabulary; very high values can indicate
# artificially inflated diversity (e.g. a model padding text with rare
# synonyms).  Both tails are thus flagged, though the high tail is softer.
#
# Thresholds (human normal range: 70–120):
#   < MTLD_STRONG_THRESHOLD (50)         → strong concern (low)
#   < MTLD_NOTE_THRESHOLD (70)           → noteworthy (low)
#   > MTLD_HIGH_NOTE_THRESHOLD (120)     → noteworthy (high; softer flag)
#
# ── Goh-Barabási Burstiness B ───────────────────────────────────────────────
#
# B = (σ − μ) / (σ + μ)  where σ and μ are the standard deviation and mean
# of the inter-arrival distances (in token positions) between consecutive
# occurrences of words in a predefined semantic group (hedging/academic
# vocabulary).  B ∈ [−1, 1]:
#   B = −1  perfectly periodic (maximally anti-bursty)
#   B =  0  Poisson / memoryless random
#   B = +1  maximally bursty (a single cluster, then silence)
#
# Goh & Barabási (2008) reported that human-generated event sequences (emails,
# phone calls) typically fall in the range 0.2–0.6.  This metric is applied
# here to word-group positions in text, which is a non-standard extrapolation;
# treat the thresholds as heuristic rather than empirically validated.
#
# Rationale for flagging:
#   - Very low B (< 0.0): words are distributed more evenly than random, which
#     is consistent with LLM output that mechanically distributes hedging
#     language throughout a document rather than concentrating it in sections
#     where it is naturally appropriate (e.g. literature review, discussion).
#   - Near-random B (0.0–0.2): inter-arrival distribution is nearly Poisson,
#     again consistent with uniform rather than section-driven placement.
#   - Above-human B (> 0.6): more bursty than typical human writing.  Possible
#     causes include artificial manipulation (inserting blocks of hedging
#     language) or a very unusual document structure.  Flagged as noteworthy.
#   - Very high B (> 0.8): implausibly extreme clustering; suggests
#     manipulation rather than natural authorship.
#
# Thresholds (human normal range: 0.2–0.6):
#   < BURSTINESS_STRONG_LOW (0.0)        → strong concern (too regular)
#   < BURSTINESS_NOTE_LOW (0.2)          → noteworthy (near-random)
#   > BURSTINESS_NOTE_HIGH (0.6)         → noteworthy (above human range)
#   > BURSTINESS_STRONG_HIGH (0.8)       → strong concern (manipulation suspected)
#
# ── Sentence-length Coefficient of Variation (CV) ───────────────────────────
#
# CV = σ / μ  where σ and μ are the standard deviation and mean of sentence
# lengths measured in non-punctuation, non-space tokens, using spaCy sentence
# segmentation of the cleaned main text.
#
# Human academic writing shows natural variation in sentence rhythm: a mix of
# short declarative sentences and longer complex ones.  The CV quantifies this
# variability relative to the mean sentence length.  LLM output tends toward
# highly uniform sentence lengths (very low CV), whereas human writing spans a
# broader range.  Implausibly *high* CV can indicate deliberate manipulation to
# inject sentence-length variation.
#
# Academic text typically falls in the range 0.55–0.85; the lower end is more
# common in technical/scientific writing where concision is valued.
#
# A minimum of 5 sentences is required; fewer than 5 returns None.
#
# Thresholds (human normal range: 0.55–0.85):
#   < SENT_CV_STRONG_LOW (0.35)          → strong concern (LLM-uniform rhythm)
#   < SENT_CV_NOTE_LOW (0.55)            → noteworthy (low variation)
#   > SENT_CV_NOTE_HIGH (0.85)           → noteworthy (high variation)
#   > SENT_CV_STRONG_HIGH (1.10)         → strong concern (implausible variability)
#
# ── AI concern aggregation ───────────────────────────────────────────────────
#
# Four metrics contribute (MATTR, MTLD, Burstiness B, Sentence CV).
# Each is classified as "ok", "note", or "strong".  The overall concern level
# is determined by:
#   low    : 0–1 metrics in "note" or above, none "strong"
#   medium : 2 metrics "note" or above, OR 1 metric "strong"
#   high   : 2+ metrics "strong", OR 3+ metrics "note" or above
#
# ---------------------------------------------------------------------------

# MATTR thresholds
MATTR_STRONG_THRESHOLD = 0.60
MATTR_NOTE_LOW_THRESHOLD = 0.70
MATTR_NOTE_HIGH_THRESHOLD = 0.85

# MTLD thresholds
MTLD_NOTE_THRESHOLD = 70
MTLD_STRONG_THRESHOLD = 50
MTLD_HIGH_NOTE_THRESHOLD = 120

# Goh-Barabási burstiness B thresholds
BURSTINESS_STRONG_LOW = 0.0
BURSTINESS_NOTE_LOW = 0.2
BURSTINESS_NOTE_HIGH = 0.6
BURSTINESS_STRONG_HIGH = 0.8

# Sentence-length CV thresholds
SENT_CV_STRONG_LOW = 0.35
SENT_CV_NOTE_LOW = 0.55
SENT_CV_NOTE_HIGH = 0.85
SENT_CV_STRONG_HIGH = 1.10


def classify_metric(value: float | None, note_threshold: float, strong_threshold: float) -> str:
    """Generic single-sided (lower-is-worse) classifier.

    Returns 'ok', 'note', 'strong', or 'unknown'.
    Values are flagged when they fall *below* the note threshold.
    Useful as a building block; prefer the metric-specific functions below.
    """
    if value is None:
        return "unknown"
    if value < strong_threshold:
        return "strong"
    if value < note_threshold:
        return "note"
    return "ok"


def classify_mattr(value: float | None) -> str:
    """Classify an MATTR value using the two-sided rule.

    Flagged 'note' when below MATTR_NOTE_LOW_THRESHOLD (limited vocabulary) or above
    MATTR_NOTE_HIGH_THRESHOLD (inflated diversity).  'strong' only for very low values.
    """
    if value is None:
        return "unknown"
    if value < MATTR_STRONG_THRESHOLD:
        return "strong"
    if value < MATTR_NOTE_LOW_THRESHOLD:
        return "note"
    if value > MATTR_NOTE_HIGH_THRESHOLD:
        return "note"
    return "ok"


def classify_mtld(value: float | None) -> str:
    """Classify an MTLD value using the two-sided rule.

    Flagged 'note' when abnormally *low* (< MTLD_NOTE_THRESHOLD, limited vocabulary range)
    or abnormally *high* (> MTLD_HIGH_NOTE_THRESHOLD, inflated diversity).
    'strong' only for very low values (< MTLD_STRONG_THRESHOLD).
    """
    if value is None:
        return "unknown"
    if value > MTLD_HIGH_NOTE_THRESHOLD:
        return "note"
    return classify_metric(value, MTLD_NOTE_THRESHOLD, MTLD_STRONG_THRESHOLD)


def classify_burstiness(value: float | None) -> str:
    """Classify a Goh-Barabási B value using the four-zone symmetric rule.

    Normal human range: [BURSTINESS_NOTE_LOW, BURSTINESS_NOTE_HIGH] = [0.2, 0.6].
    Below 0.0 → strong (too regular).
    [0.0, 0.2) → note (near-random distribution).
    (0.6, 0.8] → note (above human range).
    Above 0.8 → strong (implausible clustering; manipulation suspected).
    """
    if value is None:
        return "unknown"
    if value < BURSTINESS_STRONG_LOW:
        return "strong"
    if value < BURSTINESS_NOTE_LOW:
        return "note"
    if value > BURSTINESS_STRONG_HIGH:
        return "strong"
    if value > BURSTINESS_NOTE_HIGH:
        return "note"
    return "ok"


def classify_sentence_cv(value: float | None) -> str:
    """Classify a sentence-length CV value using the four-zone symmetric rule.

    Normal human academic range: [SENT_CV_NOTE_LOW, SENT_CV_NOTE_HIGH] = [0.55, 0.85].
    Below 0.35 → strong (LLM-uniform rhythm).
    [0.35, 0.55) → note (low variation).
    (0.85, 1.10] → note (high variation).
    Above 1.10 → strong (implausible variability; manipulation suspected).
    """
    if value is None:
        return "unknown"
    if value < SENT_CV_STRONG_LOW:
        return "strong"
    if value < SENT_CV_NOTE_LOW:
        return "note"
    if value > SENT_CV_STRONG_HIGH:
        return "strong"
    if value > SENT_CV_NOTE_HIGH:
        return "note"
    return "ok"
