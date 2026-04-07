#
# Created by David Seery on 03/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json
import re
import time
import unicodedata
from datetime import datetime

import numpy as np
from celery import states
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import SubmissionRecord
from ..shared.asset_tools import AssetCloudAdapter
from ..shared.workflow_logging import log_db_commit

# ---------------------------------------------------------------------------
# Rubric: grade bands and criteria.
# Defined as a module-level constant so they are easy to update.
# Each higher band subsumes the criteria of all lower bands.
# ---------------------------------------------------------------------------

GRADE_BANDS = [
    {
        "band": "3rd class",
        "criteria": [
            "Scientific work of limited quality",
            "Demonstrates some relevant knowledge and understanding, with limitations",
            "Limited evidence for technical and practical skills",
            "At least some attempt to explain and interpret the results of the project",
            "Report shows evidence of at least some editing and proof-reading",
        ],
    },
    {
        "band": "2.2 class",
        "criteria": [
            "Scientific work of competent quality",
            "Demonstrates reasonable understanding and analysis; competent technical or practical skills; some organisational and presentation skills",
            "Report edited and proof-read to a competent standard",
            "Report is structured into chapters, but parts of the organisation may be unclear",
            "Explanations mostly adequate",
        ],
    },
    {
        "band": "2.1 class",
        "criteria": [
            "Demonstrates very good understanding and analysis; very good technical or practical skills; very good organisational and presentation skills",
            "Report edited, typeset, and proof-read to a good standard",
            "Text mostly in a good scientific style",
            "Partial assessment of wider significance of the results",
            "Partial discussion of relation to previously published work, if appropriate",
            "Explanations are clear and not verbose",
            "Sources of error in techniques, approximations or methodologies are mostly considered",
            "Some discussion of future directions or improvements",
        ],
    },
    {
        "band": "1st class",
        "criteria": [
            "Demonstrates excellent understanding and analysis; excellent technical or practical skills; excellent organisational and presentation skills",
            "Report edited, typeset, and proof-read to a high standard",
            "Text is written in a good scientific style",
            "Clear assessment of wider significance or context of the results",
            "Relation to previously published work is explained, if appropriate",
            "Explanations are clear and succinct",
            "Sources of error in techniques, approximations or methodologies are considered",
            "Clear, well-defined suggestions for future directions or improvements",
        ],
    },
]


# ---------------------------------------------------------------------------
# Word groups for burstiness analysis.
# Each group defines a set of canonical spaCy lemmas. The corpus is
# lemmatised and token positions are matched against these lemma sets.
# ---------------------------------------------------------------------------

BURSTINESS_WORD_GROUPS = [
    {"group": "suggest", "lemmas": {"suggest"}},
    {"group": "indicate", "lemmas": {"indicate"}},
    {"group": "demonstrate", "lemmas": {"demonstrate"}},
    {"group": "show", "lemmas": {"show"}},
    {"group": "appear", "lemmas": {"appear"}},
    {"group": "estimate", "lemmas": {"estimate"}},
    {"group": "assume", "lemmas": {"assume"}},
    {"group": "imply", "lemmas": {"imply"}},
    {"group": "significant", "lemmas": {"significant", "insignificant"}},
    {"group": "important", "lemmas": {"important", "relevant"}},
    {"group": "consistent", "lemmas": {"consistent", "inconsistent"}},
    {"group": "unexpected", "lemmas": {"unexpected", "surprising"}},
    {"group": "clear", "lemmas": {"clear", "unclear"}},
    {"group": "compare", "lemmas": {"compare"}},
    {"group": "contrast", "lemmas": {"contrast", "differ"}},
    {"group": "agree", "lemmas": {"agree", "disagree", "confirm"}},
    {"group": "support", "lemmas": {"support", "contradict"}},
]

# Minimum number of occurrences for a word group to be included in the
# burstiness calculation. Groups below this threshold are excluded
# because the inter-arrival distribution is too sparse.
BURSTINESS_MIN_OCCURRENCES = 8


# ---------------------------------------------------------------------------
# Classification thresholds.
# ---------------------------------------------------------------------------

MTLD_NOTE_THRESHOLD = 70
MTLD_STRONG_THRESHOLD = 50
MTLD_HIGH_NOTE_THRESHOLD = 100
MATTR_NOTE_THRESHOLD = 0.68
MATTR_STRONG_THRESHOLD = 0.60
BURSTINESS_NOTE_THRESHOLD = 0.20
BURSTINESS_STRONG_THRESHOLD = 0.10


# ---------------------------------------------------------------------------
# Hedging and filler patterns for AI-tendency detection.
# These are matched case-insensitively.
# ---------------------------------------------------------------------------

HEDGING_PATTERNS = [
    r"it is important to note that",
    r"it is worth noting that",
    r"it is crucial toin  note that",
    r"it should be noted that",
    r"needless to say",
    r"it goes without saying that",
    r"as mentioned above",
    r"as noted above",
    r"as discussed previously",
    r"it is interesting to note that",
    r"\bsignificantly\b",
    r"\bimportantly\b",
    r"\bfundamentally\b",
    r"\bessentially\b",
    r"\bbasically\b",
    r"it is clear that",
    r"\bclearly\b",
    r"\bobviously\b",
    r"\bevidently\b",
    r"of course",
    r"\bnaturally\b",
]

FILLER_PATTERNS = [
    r"\bfurthermore\b",
    r"\bmoreover\b",
    r"in conclusion",
]

# Unicode em-dash and ASCII triple-hyphen (sometimes produced by PDF extraction
# from LaTeX --- ligature)
EM_DASH_PATTERN = r"(\u2014|---)"


# ---------------------------------------------------------------------------
# Lazy spaCy model loader.
# The model is loaded once per worker process on first use.
# ---------------------------------------------------------------------------

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy

        _nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
    return _nlp


# ---------------------------------------------------------------------------
# Text extraction helpers.
# ---------------------------------------------------------------------------


def _extract_pdf_text(path: str) -> tuple[str, int]:
    """
    Extract plain text from a PDF file at *path* using PyMuPDF.

    Returns (raw_text, page_count).  Header and footer regions (top/bottom 8%
    of each page) are skipped to reduce noise from running headers and page
    numbers.
    """
    import fitz

    doc = fitz.open(path)
    pages = []
    for page in doc:
        page_height = page.rect.height
        blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, block_no, block_type)
        body_blocks = [
            b[4]
            for b in blocks
            if b[1] > page_height * 0.08  # skip top 8 % (header / running title)
            and b[3] < page_height * 0.92  # skip bottom 8 % (footer / page number)
            and b[6] == 0  # block_type 0 = text (not image)
        ]
        pages.append("\n".join(body_blocks))
    page_count = len(doc)
    doc.close()
    return "\n\n".join(pages), page_count


def _extract_docx_text(path: str) -> tuple[str, int]:
    """
    Extract plain text from a Word document at *path* using python-docx.

    This is a basic implementation: it joins all paragraph texts.
    Table cell content is included.  Returns (raw_text, page_count=0) since
    Word documents do not expose a reliable page count without rendering.
    """
    try:
        from docx import Document

        doc = Document(path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    text = cell.text.strip()
                    if text:
                        paragraphs.append(text)
        return "\n\n".join(paragraphs), 0
    except Exception as exc:
        current_app.logger.warning(f"language_analysis: DOCX extraction failed: {exc}")
        return "", 0


# ---------------------------------------------------------------------------
# Statistical analysis helpers.
# ---------------------------------------------------------------------------

# Patterns used to detect the start of the bibliography / reference section.
_BIBLIO_HEADING = re.compile(
    r"^\s*(references|bibliography|works\s+cited)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Caption line pattern (figure or table captions, used to exclude word count).
_CAPTION_LINE = re.compile(
    r"^\s*(figure|fig\.|table)\s+\d+",
    re.IGNORECASE | re.MULTILINE,
)

# Numbered bibliography entry: [N] or N.
_NUMBERED_ENTRY = re.compile(r"^\s*(\[\d+\]|\d+\.)\s+\S", re.MULTILINE)

# Numbered citation in main text: [N] or [N, M, ...]
_NUMBERED_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _split_text(text: str) -> tuple[str, str]:
    """
    Split *text* into (main_text, biblio_text) at the bibliography heading.
    If no heading is found, returns (text, "").

    Uses the *last* match of _BIBLIO_HEADING rather than the first.  Reports
    commonly include a table of contents where "References" appears on its own
    line (e.g. "5\nReferences\n8") well before the actual reference list.
    The genuine bibliography is always the final occurrence of the heading.
    """
    matches = list(_BIBLIO_HEADING.finditer(text))
    if matches:
        match = matches[-1]
        return text[: match.start()], text[match.start() :]
    return text, ""


# ---------------------------------------------------------------------------
# Pattern used to decide whether a line contains English prose.
# See _strip_math_lines() for the full rationale.
# ---------------------------------------------------------------------------

_ENGLISH_WORD = re.compile(r"[a-zA-Z]{5,}")


def _strip_math_lines(text: str) -> str:
    """
    Remove lines that consist predominantly of mathematical notation produced
    by PDF text extraction of LaTeX-typeset equations.

    Such extraction scatters formula content across many short lines that are
    meaningless as English text — e.g. ``d4q``, ``(2π)4``, ``D0D1``,
    ``→I2(p) =``, lone integers, Greek-letter fragments.  Retaining them
    inflates word counts and distorts lexical-richness metrics (MATTR, MTLD).

    ## Detection strategy

    A line is *kept* if and only if it contains at least one run of **five or
    more consecutive ASCII letters**.  Such a run reliably indicates either an
    English content word or a recognisable section heading.

    Threshold rationale — alternatives evaluated and rejected:

    * ``[a-zA-Z]{2,}`` (≥ 2 letters): false positives for 2-letter math
      variable names (``Dk``, ``Di``, ``dq``, ``ki``) and 3-letter function
      abbreviations (``Res``, ``lim``, ``sin``, ``det``).  A digit inside a
      token (e.g. ``d3q``) *does* break the run and so is correctly filtered,
      but purely alphabetic 2–4-character tokens are not.

    * ``≥ 2 tokens of [a-zA-Z]{3,}``: correctly rejects variable names, but
      strips single-word headings such as "Introduction" and "Conclusion"
      because they contain only one matching token.

    * Vowel-gated tokens (≥ 3 letters containing ≥ 1 vowel): ``Res``,
      ``sin``, ``lim``, ``det`` all contain vowels and would pass — same
      false positives as the ``{2,}`` approach.

    With ``{5,}``:
    * Math tokens ``d3q``, ``D0D1``, ``dq0``, ``Dk``, ``Res``, ``lim`` →
      correctly filtered.
    * Section headings ``Introduction``, ``Conclusion``, ``Results``,
      ``Cauchy`` → correctly kept.
    * Prose lines → kept (always contain at least one 5+ letter word).

    The only theoretical false negative is a line whose every word is 1–4
    characters long (e.g. "We do it.").  Such lines are rare as standalone
    lines in scientific prose and, even if removed, do not materially affect
    word count or lexical richness scores.

    ## Scope of application

    This function should be applied to *main_text* only (after bibliography
    splitting) to produce a *clean_main_text* used for word count and
    MATTR/MTLD computation.  The unstripped text is left intact for burstiness
    analysis (spaCy already filters to alphabetic tokens internally), pattern
    matching (searches for English phrases), figure/table cross-reference
    detection, and LLM submission where the prose context surrounding equations
    is preserved even after stripping the equation fragments themselves.
    """
    kept = []
    for line in text.splitlines():
        if not line.strip() or _ENGLISH_WORD.search(line):
            kept.append(line)
    return "\n".join(kept)


def _word_count(main_text: str) -> int:
    """
    Count words in *main_text*, excluding caption lines.
    This is an estimate; punctuation is included with adjacent words.
    """
    clean = _CAPTION_LINE.sub("", main_text)
    return len(clean.split())


def _count_bibliography(biblio_text: str) -> tuple[int, list[str]]:
    """
    Count bibliography entries and return (count, list_of_entry_keys).

    Handles:
    - Numbered entries starting with [N] or N.
    - Falls back to a heuristic line count for author-year styles.
    """
    numbered = _NUMBERED_ENTRY.findall(biblio_text)
    if numbered:
        # Strip to just the bracket/dot keys for cross-referencing
        keys = [k.strip().strip(".").strip("[]") for k in numbered]
        return len(keys), keys
    # Heuristic: count non-blank lines after the heading as rough entry count
    lines = [ln.strip() for ln in biblio_text.splitlines() if ln.strip()]
    # Skip the heading line itself
    entry_lines = [
        ln
        for ln in lines[1:]
        if ln and not ln.lower().startswith(("ref", "biblio", "works"))
    ]
    return len(entry_lines), []


def _check_uncited(main_text: str, keys: list[str]) -> list[str]:
    """
    For a numbered bibliography with *keys* like ['1', '2', ...], return
    those keys that do not appear as citations in *main_text*.
    Only meaningful for numbered (LaTeX-style) references.
    """
    if not keys:
        return []
    cited_numbers: set[str] = set()
    for match in _NUMBERED_CITATION.finditer(main_text):
        for num in match.group(1).split(","):
            cited_numbers.add(num.strip())
    return [k for k in keys if k not in cited_numbers]


def _check_figure_table_refs(text: str) -> tuple[list[str], list[str]]:
    """
    Return (uncaptioned_figures, uncaptioned_tables): labels that appear in
    captions but are not mentioned anywhere in the main body text.
    """
    # Collect all figure and table labels from captions
    fig_labels: dict[str, str] = {}  # "N" -> "Figure N"
    tab_labels: dict[str, str] = {}

    for m in re.finditer(r"\b(figure|fig\.)\s+(\d+)", text, re.IGNORECASE):
        n = m.group(2)
        if n not in fig_labels:
            fig_labels[n] = f"Figure {n}"

    for m in re.finditer(r"\btable\s+(\d+)", text, re.IGNORECASE):
        n = m.group(1)
        if n not in tab_labels:
            tab_labels[n] = f"Table {n}"

    # Check which labels appear only once (the caption itself) — a label
    # mentioned more than once is likely also cited in the text.
    def _cited(label_text: str, pattern: str) -> bool:
        return len(re.findall(pattern, text, re.IGNORECASE)) > 1

    uncaptioned_figs = [
        label
        for n, label in fig_labels.items()
        if not _cited(label, rf"\b(?:figure|fig\.)\s+{re.escape(n)}\b")
    ]
    uncaptioned_tabs = [
        label
        for n, label in tab_labels.items()
        if not _cited(label, rf"\btable\s+{re.escape(n)}\b")
    ]

    return uncaptioned_figs, uncaptioned_tabs


def _compute_mattr_mtld(main_text: str) -> tuple[float | None, float | None]:
    """
    Compute MATTR (window=50) and MTLD for *main_text*.
    Returns (mattr, mtld), either of which may be None on failure.
    """
    try:
        from lexicalrichness import LexicalRichness

        lex = LexicalRichness(main_text)
        if lex.words < 50:
            print(
                f"_compute_matr_mtld: too few words to compute MATTR and MTLD statistics ({lex.words} words detected)"
            )
            return None, None
        mattr = float(lex.mattr(window_size=50))
        mtld = float(lex.mtld(threshold=0.72))
        return mattr, mtld
    except Exception as exc:
        current_app.logger.warning(
            f"language_analysis: MATTR/MTLD computation failed: {exc}"
        )
        return None, None


def _compute_burstiness(text: str) -> tuple[dict, float | None]:
    """
    Compute per-group and aggregate Goh-Barabási burstiness for *text*.

    Returns (group_results_dict, aggregate_burstiness).
    *group_results_dict* maps group name -> B value (or None if excluded).
    *aggregate_burstiness* is the mean over eligible groups, or None.
    """
    nlp = _get_nlp()

    # spaCy processes the text; we only need token lemmas and positions.
    # Restrict to alphabetic tokens to avoid punctuation noise.
    doc = nlp(text)
    token_lemmas = [
        (i, token.lemma_.lower()) for i, token in enumerate(doc) if token.is_alpha
    ]

    group_results: dict[str, float | None] = {}
    eligible_values: list[float] = []

    for group_def in BURSTINESS_WORD_GROUPS:
        group_name = group_def["group"]
        target_lemmas: set[str] = group_def["lemmas"]

        positions = [i for i, lemma in token_lemmas if lemma in target_lemmas]

        if len(positions) < BURSTINESS_MIN_OCCURRENCES:
            group_results[group_name] = None
            continue

        arrivals = np.diff(positions).astype(float)
        mu = float(np.mean(arrivals))
        sigma = float(np.std(arrivals, ddof=1)) if len(arrivals) > 1 else 0.0

        denom = sigma + mu
        B = float((sigma - mu) / denom) if denom != 0 else 0.0

        group_results[group_name] = B
        eligible_values.append(B)

    aggregate = float(np.mean(eligible_values)) if eligible_values else None
    return group_results, aggregate


def _count_patterns(text: str) -> dict:
    """
    Count occurrences of AI-tendency indicator patterns.
    Returns a dict with per-pattern counts and totals.
    """
    hedging_total = 0
    hedging_detail: dict[str, int] = {}
    for pattern in HEDGING_PATTERNS:
        count = len(re.findall(pattern, text, re.IGNORECASE))
        hedging_detail[pattern] = count
        hedging_total += count

    filler_total = 0
    filler_detail: dict[str, int] = {}
    for pattern in FILLER_PATTERNS:
        count = len(re.findall(pattern, text, re.IGNORECASE))
        filler_detail[pattern] = count
        filler_total += count

    em_dash_count = len(re.findall(EM_DASH_PATTERN, text))

    return {
        "hedging_total": hedging_total,
        "hedging_detail": hedging_detail,
        "filler_total": filler_total,
        "filler_detail": filler_detail,
        "em_dash_count": em_dash_count,
    }


def _classify_metric(
    value: float | None, note_threshold: float, strong_threshold: float
) -> str:
    """Return 'ok', 'note', or 'strong' classification for a metric value."""
    if value is None:
        return "unknown"
    if value < strong_threshold:
        return "strong"
    if value < note_threshold:
        return "note"
    return "ok"


def _ai_concern_flag(mattr_flag: str, mtld_flag: str, burst_flag: str) -> str:
    """
    Compute overall AI concern classification:
    - 'low'    : at most one metric outside the standard range
    - 'medium' : two or more metrics outside the standard range
    - 'high'   : all three outside, or two at the 'strong' level
    """
    flags = [mattr_flag, mtld_flag, burst_flag]
    outside = sum(1 for f in flags if f in ("note", "strong"))
    strong_count = sum(1 for f in flags if f == "strong")

    if outside <= 1:
        return "low"
    if outside == 3 or strong_count >= 2:
        return "high"
    return "medium"


# ---------------------------------------------------------------------------
# LLM helpers.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Criterion type annotations for the LLM checklist.
#
# 3rd class criteria mix two types that the LLM must treat differently for
# submissions that exceed that band:
#
#   NEGATIVE criteria describe deficiencies.  A higher-band submission does NOT
#   exhibit these deficiencies, so the correct assessment is "Not evident".
#
#   POSITIVE FLOOR criteria describe minimum positive requirements.  A
#   higher-band submission clearly meets and exceeds these floors, so the
#   correct assessment is "Strong evidence".
#
# All criteria for 2.2 and above are achievement-level descriptors and are not
# tagged — they should be assessed normally against the evidence in the text.
# ---------------------------------------------------------------------------

_NEGATIVE_CRITERIA: frozenset = frozenset(
    [
        "Scientific work of limited quality",
        "Demonstrates some relevant knowledge and understanding, with limitations",
        "Limited evidence for technical and practical skills",
    ]
)

_POSITIVE_FLOOR_CRITERIA: frozenset = frozenset(
    [
        "At least some attempt to explain and interpret the results of the project",
        "Report shows evidence of at least some editing and proof-reading",
    ]
)

_TRUNCATION_MARKER = "\n\n[... middle section omitted due to length ...]\n\n"
_MAX_WORDS_BEFORE_TRUNCATION = 12000
_TRUNCATION_HEAD_WORDS = 6000
_TRUNCATION_TAIL_WORDS = 6000

_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_DELAY = 5  # seconds


def _truncate_text(text: str) -> tuple[str, bool]:
    """
    If *text* exceeds _MAX_WORDS_BEFORE_TRUNCATION words, return a truncated
    version consisting of the first and last _TRUNCATION_{HEAD,TAIL}_WORDS words
    separated by a marker.  Returns (text, was_truncated).
    """
    words = text.split()
    if len(words) <= _MAX_WORDS_BEFORE_TRUNCATION:
        return text, False
    head = " ".join(words[:_TRUNCATION_HEAD_WORDS])
    tail = " ".join(words[-_TRUNCATION_TAIL_WORDS:])
    return head + _TRUNCATION_MARKER + tail, True


def _build_system_prompt(truncated: bool) -> str:
    """Construct the LLM system prompt including the rubric and explicit criteria checklist."""
    # Rubric narrative section (used for context and assessment rules)
    band_sections = []
    for band in GRADE_BANDS:
        criteria_list = "\n".join(f"  - {c}" for c in band["criteria"])
        band_sections.append(f"### {band['band']}\n{criteria_list}")
    rubric_text = "\n\n".join(band_sections)

    # Explicit numbered checklist — enumerate every criterion so the LLM cannot
    # accidentally omit or paraphrase any of them.  The criterion text here must
    # be reproduced verbatim in the "criterion" field of each response entry.
    checklist_sections = []
    for band_idx, band in enumerate(GRADE_BANDS, start=1):
        lines = [f"Band {band_idx} — {band['band']}:"]
        for crit_idx, criterion in enumerate(band["criteria"], start=1):
            if criterion in _NEGATIVE_CRITERIA:
                tag = "  [NEGATIVE — 'Not evident' for submissions above this band]"
            elif criterion in _POSITIVE_FLOOR_CRITERIA:
                tag = "  [POSITIVE FLOOR — 'Strong evidence' for submissions above this band]"
            else:
                tag = ""
            lines.append(f"  {band_idx}.{crit_idx}  {criterion}{tag}")
        checklist_sections.append("\n".join(lines))
    criteria_checklist = "\n\n".join(checklist_sections)

    truncation_note = (
        "\n\nNOTE: The document text provided may have been truncated. "
        "If you see the marker '[... middle section omitted due to length ...]', "
        "the middle portion of the document has been removed. Please note this "
        "limitation in the caveats field of your response."
        if truncated
        else ""
    )

    schema_description = f"""
Your response must be a JSON object with the following fields:

- "report_summary": 1-2 paragraphs describing what the report is about, what the student
  did, and the overall approach taken. This is a content summary, not a marking judgement.

- "classification": the recommended grade band (one of the exact band names from the rubric).

- "overall_reasoning": one paragraph explaining why you recommend that band.

- "bands": an array with exactly one entry per grade band, in order from lowest to highest.
  Each entry must have:
    - "band": the band name, copied exactly from the rubric
    - "band_assessment": one of:
        "Criteria clearly demonstrated"   — report substantially satisfies all criteria for this band
        "Criteria mostly demonstrated"    — most criteria met, minor gaps
        "Some criteria demonstrated"      — meaningful evidence for some criteria but threshold not reached
        "No evidence"                     — report does not meet this band's criteria
    - "criteria": an object with exactly one key per criterion for that band.
      Each key is the short numeric code from the checklist below (e.g. "1.1", "2.3").
      Each value is an object with:
        - "assessment": one of "Strong evidence", "Partial evidence", or "Not evident"
        - "commentary": one or two sentences with specific textual evidence from the report
        - "confidence": one of "high", "medium", or "low"
      Every code in the checklist MUST appear as a key. Do not add extra keys.

- "caveats": any limitations, uncertainties, or criteria that could not be assessed from
  text alone (e.g. typesetting quality, visual presentation).

- "stated_word_count_found": true if the document contains an explicit word count stated
  by the student (typically near a label such as "Word count:", "Total word count:", or
  similar); false otherwise.

- "stated_word_count": the integer value of the student's stated word count if
  stated_word_count_found is true, otherwise null.

- "genai_statement_found": true if the document contains any statement about the student's
  use (or non-use) of generative AI tools; false otherwise. The statement may appear
  anywhere in the document under any heading.

- "genai_statement": if genai_statement_found is true, copy the verbatim text of the AI
  use statement (or its first sentence if very long). Empty string if not found.

- "preface_found": true if the document contains a "Preface" section (or equivalently
  named section, e.g. "Acknowledgements and Contribution", "Personal Statement") that
  includes a description of the student's personal contribution to the project work.
  false otherwise.

- "preface_precis": if preface_found is true, provide a 1-3 sentence précis of the
  student's personal contribution statement. Empty string if not found.

## Criteria checklist — use the numeric code (e.g. "1.1") as the key for each criterion

{criteria_checklist}

Flag criteria that relate to visual presentation or typesetting with low confidence and a note
that these cannot be fully assessed from extracted text alone.
"""

    cross_band_guidance = """
## Cross-band assessment guidance

Rubric criteria fall into two types:

1. **Negative/limitation criteria** describe deficiencies (e.g. "Scientific work of \
limited quality", "Limited evidence for technical and practical skills"). For a \
submission that exceeds that band, the correct assessment is "Not evident" — the \
deficiency is simply absent.

2. **Positive minimum criteria** describe a floor requirement (e.g. "At least some \
attempt to explain and interpret the results", "Some discussion of future directions"). \
A submission at a higher band clearly meets and exceeds these floors. The correct \
assessment is "Strong evidence" — not "Not evident".

For bands BELOW your recommended classification:
- Negative/limitation criteria → "Not evident"
- Positive minimum criteria → "Strong evidence"

For your recommended band: assess each criterion normally on the evidence in the text.

For bands ABOVE your recommended classification: use "Partial evidence" or "Not evident" \
with commentary explaining specifically what evidence is missing or insufficient.

Your assessments must be self-consistent. If you recommend "2.1 class", marking \
"At least some attempt to explain and interpret the results" as "Not evident" is \
contradictory — a 2.1 submission clearly demonstrates this.
"""

    return f"""You are an expert academic marker assisting with assessment of undergraduate and postgraduate project reports. Your task is to evaluate the submitted report text against the rubric below and recommend a grade band.

## Rubric

{rubric_text}

## Assessment Rules

Each higher grade band subsumes all criteria of lower bands. A submission cannot be awarded a higher band unless it substantially satisfies the criteria of all lower bands. Assess against the highest band whose full set of criteria, including those of all lower bands, are mostly satisfied.

Where you are uncertain, or where the text does not provide enough evidence, say so explicitly. Quote specific passages from the text to support your assessment — this makes your reasoning auditable by a human marker. Flag criteria where you consider yourself less able to assess reliably from text alone.
{cross_band_guidance}
{schema_description}{truncation_note}"""


def _build_user_prompt(document_text: str) -> str:
    return f"Please assess the following report text:\n\n---\n\n{document_text}\n\n---"


_REQUIRED_JSON_KEYS = {
    "report_summary",
    "classification",
    "overall_reasoning",
    "bands",
    "caveats",
    "stated_word_count_found",
    "stated_word_count",
    "genai_statement_found",
    "genai_statement",
    "preface_found",
    "preface_precis",
}


def _make_band_schema(band_idx: int, criteria_list: list) -> dict:
    """
    Return the JSON Schema for a single band entry within the top-level 'bands' object.

    *band_idx* is the 1-based index of the band (used to generate criterion codes).
    *criteria_list* is the exhaustive list of criterion strings for this band.

    'criteria' is modelled as a fixed-key JSON Schema object (not an array) where each
    property key is a short numeric code ("1.1", "1.2", …) rather than the full criterion
    text.  Using short codes avoids a SIGSEGV in the llama.cpp GBNF grammar generator,
    which crashes when property name literals in the generated grammar exceed a certain
    length or contain special characters (parentheses, punctuation, etc.).

    Short alphanumeric keys ("1.1", "2.3", …) are entirely safe for grammar generation.
    The mapping from code to full criterion text is stored separately in criterion_map
    (built in submit_to_llm) and injected into the template context for display.

    This approach still enforces at the grammar level that:
      - every criterion is present exactly once (object keys are unique and required),
      - no criterion can be invented (only the declared property names are valid).
    """
    per_criterion_schema = {
        "type": "object",
        "properties": {
            "assessment": {
                "type": "string",
                "enum": ["Strong evidence", "Partial evidence", "Not evident"],
            },
            "commentary": {"type": "string"},
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low"],
            },
        },
        "required": ["assessment", "commentary", "confidence"],
    }
    codes = [f"{band_idx}.{crit_idx}" for crit_idx in range(1, len(criteria_list) + 1)]
    return {
        "type": "object",
        "properties": {
            "band_assessment": {
                "type": "string",
                "enum": [
                    "Criteria clearly demonstrated",
                    "Criteria mostly demonstrated",
                    "Some criteria demonstrated",
                    "No evidence",
                ],
            },
            "criteria": {
                "type": "object",
                "properties": {code: per_criterion_schema for code in codes},
                "required": codes,
            },
        },
        "required": ["band_assessment", "criteria"],
    }


# JSON Schema passed to the Ollama structured-output API (format= parameter).
# This enforces the response structure at the token-sampling level, independently
# of the natural-language instructions in the system prompt.
#
# Top-level structure:
#   report_summary         — 1-2 paragraph narrative description of the report content
#   classification         — recommended grade band (enum-constrained to GRADE_BANDS)
#   overall_reasoning      — one paragraph justifying the recommended band
#   bands                  — fixed-key object, one property per GRADE_BANDS entry, each
#                            containing a band_assessment summary and a 'criteria' object.
#                            'bands' as an object enforces that all four band names are
#                            present exactly once (object keys are unique and required).
#                            'criteria' is also modelled as a fixed-key object keyed by
#                            short numeric codes ("1.1", "1.2", …) rather than the full
#                            criterion text.  Long criterion strings as grammar property-
#                            name literals trigger a SIGSEGV in the llama.cpp GBNF
#                            generator; short codes are safe.  The code→text mapping is
#                            stored in criterion_map.
#   caveats                — free-text limitations or caveats
#   stated_word_count_found — whether the document states an explicit word count
#   stated_word_count      — the stated integer count, or null
#   genai_statement_found  — whether a generative-AI use statement is present
#   genai_statement        — verbatim AI use statement, or empty string
#   preface_found          — whether a preface / personal contribution section exists
#   preface_precis         — 1-3 sentence précis of the contribution statement, or ""
_LLM_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "report_summary": {"type": "string"},
        "classification": {
            "type": "string",
            "enum": [band["band"] for band in GRADE_BANDS],
        },
        "overall_reasoning": {"type": "string"},
        "bands": {
            "type": "object",
            "properties": {
                band["band"]: _make_band_schema(band_idx, band["criteria"])
                for band_idx, band in enumerate(GRADE_BANDS, start=1)
            },
            "required": [band["band"] for band in GRADE_BANDS],
        },
        "caveats": {"type": "string"},
        "stated_word_count_found": {"type": "boolean"},
        "stated_word_count": {"type": ["integer", "null"]},
        "genai_statement_found": {"type": "boolean"},
        "genai_statement": {"type": "string"},
        "preface_found": {"type": "boolean"},
        "preface_precis": {"type": "string"},
    },
    "required": [
        "report_summary",
        "classification",
        "overall_reasoning",
        "bands",
        "caveats",
        "stated_word_count_found",
        "stated_word_count",
        "genai_statement_found",
        "genai_statement",
        "preface_found",
        "preface_precis",
    ],
}


def _validate_llm_response(data: dict) -> bool:
    """Return True if the LLM JSON response has all required top-level keys."""
    return _REQUIRED_JSON_KEYS.issubset(data.keys())


# ---------------------------------------------------------------------------
# Feedback LLM helpers.
# ---------------------------------------------------------------------------

_LLM_FEEDBACK_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "positive_feedback": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 3,
        },
        "improvements": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 3,
        },
    },
    "required": ["positive_feedback", "improvements"],
}

_REQUIRED_FEEDBACK_JSON_KEYS = {"positive_feedback", "improvements"}


def _build_feedback_system_prompt(truncated: bool) -> str:
    """Construct the LLM system prompt for the feedback-generation pass."""
    truncation_note = (
        "\n\nNOTE: The document text provided may have been truncated. "
        "If you see the marker '[... middle section omitted due to length ...]', "
        "the middle portion of the document has been removed. Base your feedback "
        "only on the text that is visible."
        if truncated
        else ""
    )

    return f"""You are an experienced academic supervisor reading a student project report. \
Your task is to provide concise, specific formative feedback that will help the student \
understand what they did well and how they could improve.

## Instructions

Produce exactly 2–3 items of **positive feedback** and exactly 2–3 **suggestions for improvement**.

Each item must:
- Be specific to the actual content of this report — name the topic, technique, section, \
or argument you are referring to. Generic phrases such as "good introduction" or \
"consider improving your writing" are not acceptable.
- Be written in plain English, addressed to the student, in one or two sentences.
- For improvements: be actionable — say what the student should do differently, not just \
that something is missing.

## Response format

Your response must be a JSON object with exactly two fields:

- "positive_feedback": an array of 2–3 strings, each being one item of positive feedback.
- "improvements": an array of 2–3 strings, each being one actionable improvement suggestion.{truncation_note}"""


def _build_feedback_user_prompt(document_text: str) -> str:
    return f"Please provide feedback on the following report:\n\n---\n\n{document_text}\n\n---"


def _validate_feedback_response(data: dict) -> bool:
    """Return True if the feedback JSON response has all required top-level keys."""
    return _REQUIRED_FEEDBACK_JSON_KEYS.issubset(data.keys())


# ---------------------------------------------------------------------------
# Celery task registration.
# ---------------------------------------------------------------------------


def _dispatch_process_report(record_id: int) -> None:
    """Fire-and-forget dispatch of process_report.process after language analysis completes."""
    try:
        celery = current_app.extensions["celery"]
        task = celery.tasks["app.tasks.process_report.process"]
        task.apply_async(args=[record_id])
    except Exception as exc:
        current_app.logger.exception(
            f"Failed to dispatch process_report for record_id={record_id}", exc_info=exc
        )


def register_language_analysis_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def download_and_extract(self, record_id: int):
        """
        Stage 1 (llm_tasks queue): download the submitted report asset and
        extract plain text from it.  The extracted text is stored temporarily
        in the language_analysis JSON blob under the key '_extracted_text'.
        """
        self.update_state(
            state=states.STARTED, meta={"msg": "Downloading report asset"}
        )

        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError in download_and_extract", exc_info=exc
            )
            raise self.retry()

        if record is None:
            raise Exception(
                f"language_analysis.download_and_extract: SubmissionRecord #{record_id} not found"
            )

        if record.report is None:
            raise Exception(
                f"language_analysis.download_and_extract: SubmissionRecord #{record_id} has no report"
            )

        asset = record.report
        storage = current_app.config["OBJECT_STORAGE_ASSETS"]
        adapter = AssetCloudAdapter(
            asset,
            storage,
            audit_data=f"language_analysis.download_and_extract (record #{record_id})",
        )

        if not adapter.exists():
            raise Exception(
                f"language_analysis.download_and_extract: report asset not found in object store for record #{record_id}"
            )

        raw_text = ""
        page_count = 0
        errors = []

        mimetype = (asset.mimetype or "").lower()
        _t_extraction = time.monotonic()

        try:
            with adapter.download_to_scratch() as scratch:
                path = str(scratch.path)
                if "pdf" in mimetype or path.lower().endswith(".pdf"):
                    raw_text, page_count = _extract_pdf_text(path)
                elif (
                    "word" in mimetype
                    or "officedocument" in mimetype
                    or path.lower().endswith((".docx", ".doc"))
                ):
                    raw_text, page_count = _extract_docx_text(path)
                else:
                    # Fall back to PDF extraction and log a warning
                    current_app.logger.warning(
                        f"language_analysis: unknown mimetype '{mimetype}' for record #{record_id}; attempting PDF extraction"
                    )
                    try:
                        raw_text, page_count = _extract_pdf_text(path)
                    except Exception as exc2:
                        errors.append(
                            {
                                "stage": "extract",
                                "type": type(exc2).__name__,
                                "message": str(exc2),
                            }
                        )
        except Exception as exc:
            errors.append(
                {"stage": "download", "type": type(exc).__name__, "message": str(exc)}
            )

        # Persist extracted text in the JSON blob
        data = record.language_analysis_data
        data["_extracted_text"] = unicodedata.normalize("NFKC", raw_text)
        data["_page_count"] = page_count
        if errors:
            data.setdefault("errors", []).extend(errors)
        data.setdefault("timings", {})["extraction_s"] = round(
            time.monotonic() - _t_extraction, 1
        )
        record.set_language_analysis_data(data)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError committing extracted text", exc_info=exc
            )
            raise self.retry()

    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def compute_statistics(self, record_id: int):
        """
        Stage 2 (default queue): compute all statistical language metrics from
        the extracted text stored in the JSON blob.  Errors in individual
        computation steps are caught and recorded; the task does not abort.
        """
        self.update_state(
            state=states.STARTED, meta={"msg": "Computing language statistics"}
        )

        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError in compute_statistics", exc_info=exc
            )
            raise self.retry()

        if record is None:
            raise Exception(
                f"language_analysis.compute_statistics: SubmissionRecord #{record_id} not found"
            )

        data = record.language_analysis_data
        raw_text: str = data.get("_extracted_text", "")
        errors: list = data.get("errors", [])

        metrics: dict = {}
        references_info: dict = {}
        patterns_info: dict = {}

        # --- split into main text and bibliography ---------------------------
        main_text, biblio_text = _split_text(raw_text)
        # Strip math-extraction noise for metrics sensitive to vocabulary content.
        # See _strip_math_lines() for full rationale and threshold choice.
        clean_main_text = _strip_math_lines(main_text)

        # print(f"CLEANED MAIN TEXT = {clean_main_text}")
        # print(f"BIBLIOGRAPHY = {biblio_text}")

        _t_counting = time.monotonic()

        # --- word count -------------------------------------------------------
        try:
            wc = _word_count(clean_main_text)
            metrics["word_count"] = wc
        except Exception as exc:
            errors.append(
                {"stage": "word_count", "type": type(exc).__name__, "message": str(exc)}
            )
            metrics["word_count"] = None

        # --- bibliography count and citation check ----------------------------
        try:
            ref_count, ref_keys = _count_bibliography(biblio_text)
            metrics["reference_count"] = ref_count

            uncited = _check_uncited(main_text, ref_keys)
            references_info["uncited"] = uncited
        except Exception as exc:
            errors.append(
                {"stage": "references", "type": type(exc).__name__, "message": str(exc)}
            )
            metrics["reference_count"] = None
            references_info["uncited"] = []

        # --- figure and table cross-reference check --------------------------
        try:
            uncaptioned_figs, uncaptioned_tabs = _check_figure_table_refs(raw_text)
            # Count distinct labels found
            fig_labels = set(
                re.findall(r"\b(?:figure|fig\.)\s+\d+", raw_text, re.IGNORECASE)
            )
            tab_labels = set(re.findall(r"\btable\s+\d+", raw_text, re.IGNORECASE))
            metrics["figure_count"] = len(fig_labels)
            metrics["table_count"] = len(tab_labels)
            references_info["uncaptioned_figures"] = uncaptioned_figs
            references_info["uncaptioned_tables"] = uncaptioned_tabs
        except Exception as exc:
            errors.append(
                {
                    "stage": "figure_table_refs",
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            metrics["figure_count"] = None
            metrics["table_count"] = None
            references_info["uncaptioned_figures"] = []
            references_info["uncaptioned_tables"] = []

        # counting_s covers: word count, bibliography, figure/table refs, pattern
        # matching — all fast regex/counting operations with no NLP model load.
        _t_ai = time.monotonic()

        # --- MATTR and MTLD --------------------------------------------------
        try:
            mattr, mtld = _compute_mattr_mtld(clean_main_text)
            metrics["mattr"] = mattr
            metrics["mtld"] = mtld
        except Exception as exc:
            errors.append(
                {"stage": "mattr_mtld", "type": type(exc).__name__, "message": str(exc)}
            )
            metrics["mattr"] = None
            metrics["mtld"] = None

        # --- burstiness ------------------------------------------------------
        try:
            burstiness_groups, burstiness_aggregate = _compute_burstiness(raw_text)
            metrics["burstiness"] = burstiness_aggregate
            metrics["burstiness_by_group"] = burstiness_groups
        except Exception as exc:
            errors.append(
                {"stage": "burstiness", "type": type(exc).__name__, "message": str(exc)}
            )
            metrics["burstiness"] = None
            metrics["burstiness_by_group"] = {}

        # --- pattern matching ------------------------------------------------
        try:
            patterns_info = _count_patterns(raw_text)
        except Exception as exc:
            errors.append(
                {"stage": "patterns", "type": type(exc).__name__, "message": str(exc)}
            )

        # --- classification flags --------------------------------------------
        mattr_flag = _classify_metric(
            metrics.get("mattr"), MATTR_NOTE_THRESHOLD, MATTR_STRONG_THRESHOLD
        )
        _mtld_val = metrics.get("mtld")
        if _mtld_val is not None and _mtld_val > MTLD_HIGH_NOTE_THRESHOLD:
            mtld_flag = "note"
        else:
            mtld_flag = _classify_metric(
                _mtld_val, MTLD_NOTE_THRESHOLD, MTLD_STRONG_THRESHOLD
            )
        burst_flag = _classify_metric(
            metrics.get("burstiness"),
            BURSTINESS_NOTE_THRESHOLD,
            BURSTINESS_STRONG_THRESHOLD,
        )
        ai_concern = _ai_concern_flag(mattr_flag, mtld_flag, burst_flag)

        flags = {
            "mattr_flag": mattr_flag,
            "mtld_flag": mtld_flag,
            "burstiness_flag": burst_flag,
            "ai_concern": ai_concern,
        }

        # --- persist ---------------------------------------------------------
        timings = data.get("timings", {})
        timings["counting_s"] = round(_t_ai - _t_counting, 1)
        timings["ai_metrics_s"] = round(time.monotonic() - _t_ai, 1)
        data["timings"] = timings
        data["metrics"] = metrics
        data["flags"] = flags
        data["references"] = references_info
        data["patterns"] = patterns_info
        data["errors"] = errors
        record.set_language_analysis_data(data)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError committing statistics", exc_info=exc
            )
            raise self.retry()

    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def submit_to_llm(self, record_id: int):
        """
        Stage 3 (llm_tasks queue): submit the extracted report text to an Ollama
        LLM for grade-band assessment.  Retries up to three times on transient
        errors; permanent failures are recorded in llm_analysis_failed.

        Records with llm_analysis_failed=True are not retried until an
        administrator explicitly clears the flag.
        """
        self.update_state(state=states.STARTED, meta={"msg": "Submitting to LLM"})

        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError in submit_to_llm", exc_info=exc
            )
            raise self.retry()

        if record is None:
            raise Exception(
                f"language_analysis.submit_to_llm: SubmissionRecord #{record_id} not found"
            )

        # Do not re-attempt if a human administrator has not yet cleared the failure flag
        if record.llm_analysis_failed:
            current_app.logger.info(
                f"language_analysis.submit_to_llm: skipping record #{record_id} — llm_analysis_failed is set"
            )
            return

        data = record.language_analysis_data
        raw_text: str = data.get("_extracted_text", "")

        # Strip math-extraction noise before submission: garbled equation
        # fragments convey nothing useful to the LLM and waste context tokens.
        # The prose surrounding equations — which carries the scientific
        # reasoning the LLM needs to assess — is preserved intact.
        main_text, _ = _split_text(raw_text)
        clean_text = _strip_math_lines(main_text)

        document_text, was_truncated = _truncate_text(clean_text)
        system_prompt = _build_system_prompt(was_truncated)
        user_prompt = _build_user_prompt(document_text)

        base_url = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = current_app.config.get("OLLAMA_MODEL", "llama3.1:70b")

        accumulated = ""
        last_exc: Exception | None = None
        parsed_result: dict | None = None

        import ollama

        client = ollama.Client(host=base_url)
        _t_llm = time.monotonic()

        for attempt in range(_LLM_RETRY_ATTEMPTS):
            accumulated = ""
            try:
                stream = client.generate(
                    model=model,
                    prompt=user_prompt,
                    system=system_prompt,
                    format=_LLM_RESPONSE_SCHEMA,
                    stream=True,
                )
                for chunk in stream:
                    # The ollama library returns objects with a .response attribute
                    # (or dict-style access in older versions)
                    if hasattr(chunk, "response"):
                        accumulated += chunk.response
                    elif isinstance(chunk, dict):
                        accumulated += chunk.get("response", "")

                # Attempt to parse and validate
                parsed = json.loads(accumulated)
                if not _validate_llm_response(parsed):
                    raise ValueError(
                        f"LLM response missing required keys; got: {list(parsed.keys())}"
                    )
                parsed_result = parsed
                last_exc = None
                break  # success

            except ollama.ResponseError as exc:
                last_exc = exc
                status = getattr(exc, "status_code", 0)
                if 400 <= status < 500:
                    # HTTP 4xx: permanent failure — do not retry
                    current_app.logger.error(
                        f"language_analysis.submit_to_llm: permanent HTTP {status} error for record #{record_id}: {exc}"
                    )
                    break
                # Other HTTP errors: transient
                if attempt < _LLM_RETRY_ATTEMPTS - 1:
                    time.sleep(_LLM_RETRY_DELAY)

            except (json.JSONDecodeError, ValueError) as exc:
                last_exc = exc
                current_app.logger.warning(
                    f"language_analysis.submit_to_llm: JSON parse failure on attempt {attempt + 1}: {exc}"
                )
                if attempt < _LLM_RETRY_ATTEMPTS - 1:
                    time.sleep(_LLM_RETRY_DELAY)

            except Exception as exc:
                last_exc = exc
                current_app.logger.warning(
                    f"language_analysis.submit_to_llm: transient error on attempt {attempt + 1}: {exc}"
                )
                if attempt < _LLM_RETRY_ATTEMPTS - 1:
                    time.sleep(_LLM_RETRY_DELAY)

        # Handle outcome
        data.setdefault("timings", {})["llm_s"] = round(time.monotonic() - _t_llm, 1)
        errors: list = data.get("errors", [])

        if parsed_result is not None:
            # Success: store result.
            # _extracted_text is left intact here so the subsequent
            # submit_to_llm_feedback task can reuse it; finalize() cleans it up.
            data["llm_result"] = parsed_result
            # Build a code→full-text mapping so the template can display criterion text.
            # Codes match those used as JSON Schema property keys in _make_band_schema.
            data["criterion_map"] = {
                f"{band_idx}.{crit_idx}": criterion
                for band_idx, band in enumerate(GRADE_BANDS, start=1)
                for crit_idx, criterion in enumerate(band["criteria"], start=1)
            }
        else:
            # Failure after all retries
            failure_reason = str(last_exc) if last_exc else "Unknown error"
            record.llm_analysis_failed = True
            record.llm_failure_reason = failure_reason
            data["llm_raw_response"] = (
                accumulated  # preserve raw response for admin inspection
            )
            errors.append(
                {
                    "stage": "llm_submission",
                    "type": type(last_exc).__name__ if last_exc else "Unknown",
                    "message": failure_reason,
                }
            )
            current_app.logger.error(
                f"language_analysis.submit_to_llm: LLM submission failed for record #{record_id}: {failure_reason}"
            )

        data["errors"] = errors
        record.set_language_analysis_data(data)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError committing LLM result", exc_info=exc
            )
            raise self.retry()

    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def submit_to_llm_feedback(self, record_id: int):
        """
        Stage 4 (llm_tasks queue): submit the extracted report text to an Ollama
        LLM for formative feedback generation (positive feedback and improvement
        suggestions).  Runs after submit_to_llm in the chain so both tasks share
        the same _extracted_text without redundant downloads.

        Failures are recorded in the JSON blob and in llm_feedback_failed on the
        record, but do not abort the chain — finalize() still runs so the rest of
        the analysis results remain available.
        """
        self.update_state(state=states.STARTED, meta={"msg": "Generating feedback"})

        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError in submit_to_llm_feedback", exc_info=exc
            )
            raise self.retry()

        if record is None:
            raise Exception(
                f"language_analysis.submit_to_llm_feedback: SubmissionRecord #{record_id} not found"
            )

        # Do not re-attempt if a human administrator has not yet cleared the failure flag
        if record.llm_feedback_failed:
            current_app.logger.info(
                f"language_analysis.submit_to_llm_feedback: skipping record #{record_id} — llm_feedback_failed is set"
            )
            return

        data = record.language_analysis_data
        raw_text: str = data.get("_extracted_text", "")

        main_text, _ = _split_text(raw_text)
        clean_text = _strip_math_lines(main_text)
        document_text, was_truncated = _truncate_text(clean_text)

        system_prompt = _build_feedback_system_prompt(was_truncated)
        user_prompt = _build_feedback_user_prompt(document_text)

        base_url = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model = current_app.config.get("OLLAMA_MODEL", "llama3.1:70b")

        accumulated = ""
        last_exc: Exception | None = None
        parsed_result: dict | None = None

        import ollama

        client = ollama.Client(host=base_url)
        _t_feedback = time.monotonic()

        for attempt in range(_LLM_RETRY_ATTEMPTS):
            accumulated = ""
            try:
                stream = client.generate(
                    model=model,
                    prompt=user_prompt,
                    system=system_prompt,
                    format=_LLM_FEEDBACK_RESPONSE_SCHEMA,
                    stream=True,
                )
                for chunk in stream:
                    if hasattr(chunk, "response"):
                        accumulated += chunk.response
                    elif isinstance(chunk, dict):
                        accumulated += chunk.get("response", "")

                parsed = json.loads(accumulated)
                if not _validate_feedback_response(parsed):
                    raise ValueError(
                        f"Feedback LLM response missing required keys; got: {list(parsed.keys())}"
                    )
                parsed_result = parsed
                last_exc = None
                break

            except ollama.ResponseError as exc:
                last_exc = exc
                status = getattr(exc, "status_code", 0)
                if 400 <= status < 500:
                    current_app.logger.error(
                        f"language_analysis.submit_to_llm_feedback: permanent HTTP {status} error for record #{record_id}: {exc}"
                    )
                    break
                if attempt < _LLM_RETRY_ATTEMPTS - 1:
                    time.sleep(_LLM_RETRY_DELAY)

            except (json.JSONDecodeError, ValueError) as exc:
                last_exc = exc
                current_app.logger.warning(
                    f"language_analysis.submit_to_llm_feedback: JSON parse failure on attempt {attempt + 1}: {exc}"
                )
                if attempt < _LLM_RETRY_ATTEMPTS - 1:
                    time.sleep(_LLM_RETRY_DELAY)

            except Exception as exc:
                last_exc = exc
                current_app.logger.warning(
                    f"language_analysis.submit_to_llm_feedback: transient error on attempt {attempt + 1}: {exc}"
                )
                if attempt < _LLM_RETRY_ATTEMPTS - 1:
                    time.sleep(_LLM_RETRY_DELAY)

        data.setdefault("timings", {})["llm_feedback_s"] = round(
            time.monotonic() - _t_feedback, 1
        )
        errors: list = data.get("errors", [])

        if parsed_result is not None:
            data["llm_feedback"] = parsed_result
        else:
            failure_reason = str(last_exc) if last_exc else "Unknown error"
            record.llm_feedback_failed = True
            record.llm_feedback_failure_reason = failure_reason
            errors.append(
                {
                    "stage": "llm_feedback_submission",
                    "type": type(last_exc).__name__ if last_exc else "Unknown",
                    "message": failure_reason,
                }
            )
            current_app.logger.error(
                f"language_analysis.submit_to_llm_feedback: feedback generation failed for record #{record_id}: {failure_reason}"
            )

        data["errors"] = errors
        record.set_language_analysis_data(data)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError committing feedback result", exc_info=exc
            )
            raise self.retry()

    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def finalize(self, record_id: int):
        """
        Stage 5 (default queue): mark language analysis as complete, compute risk factors,
        and trigger processed-report generation.
        """
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError in language_analysis.finalize", exc_info=exc
            )
            raise self.retry()

        if record is None:
            raise Exception(
                f"language_analysis.finalize: SubmissionRecord #{record_id} not found"
            )

        # Remove the bulky intermediate extracted text now that both LLM tasks
        # have completed (or been skipped due to failure).
        data = record.language_analysis_data
        data.pop("_extracted_text", None)
        record.set_language_analysis_data(data)

        record.language_analysis_complete = True

        # Compute/refresh risk factors using current analysis data and project configuration.
        try:
            config = record.period.config if record.period else None
            record.compute_risk_factors(config)
        except Exception as exc:
            # Non-fatal: log and continue — analysis results are still available.
            current_app.logger.exception(
                "Exception computing risk factors in language_analysis.finalize",
                exc_info=exc,
            )

        try:
            log_db_commit(
                "Language analysis workflow completed",
                student=record.owner.student if record.owner else None,
                project_classes=record.owner.config.project_class
                if record.owner and record.owner.config
                else None,
                endpoint=self.name,
            )
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in language_analysis.finalize commit", exc_info=exc
            )
            raise self.retry()

        # Trigger (re-)generation of the processed report now that LLM data is available.
        if record.report is not None:
            _dispatch_process_report(record_id)

    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def error_handler(self, record_id: int, user_id: int):
        """
        Error callback: called when any task in the chain raises an unhandled
        exception.  Marks the analysis as not started (so it can be re-triggered)
        and logs the failure.

        Note: llm_analysis_failed is NOT set here — it is reserved for LLM
        inference and JSON parsing failures only.
        """
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError in language_analysis.error_handler", exc_info=exc
            )
            return

        if record is None:
            current_app.logger.error(
                f"language_analysis.error_handler: SubmissionRecord #{record_id} not found"
            )
            return

        # Reset progress flags so the analysis can be re-triggered
        record.language_analysis_started = False
        record.language_analysis_complete = False

        # Record the workflow-level failure in the JSON blob
        data = record.language_analysis_data
        data.pop("_extracted_text", None)  # clean up large intermediate data
        data.setdefault("errors", []).append(
            {
                "stage": "workflow",
                "type": "UnhandledError",
                "message": "An unhandled exception occurred in the language analysis workflow. Check Celery logs.",
            }
        )
        record.set_language_analysis_data(data)

        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in language_analysis.error_handler commit",
                exc_info=exc,
            )
