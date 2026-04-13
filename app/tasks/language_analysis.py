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
from billiard.exceptions import SoftTimeLimitExceeded
from celery import states
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import ProjectClass, ProjectClassConfig, SubmissionPeriodRecord, SubmissionRecord, TaskRecord, Tenant
from ..shared.asset_tools import AssetCloudAdapter
from ..shared.ai_calibration import mahalanobis_distance
from ..task_queue import progress_update
from ..shared.llm_thresholds import (
    classify_burstiness,
    classify_mattr,
    classify_mtld,
    classify_sentence_cv,
)
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
        # The parser normally provides sentence boundaries; since it is disabled,
        # add the rule-based sentencizer so that doc.sents is available.
        if not _nlp.has_pipe("senter") and not _nlp.has_pipe("sentencizer"):
            _nlp.add_pipe("sentencizer", first=True)
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
# Handles simple (Figure 1), chapter-relative (Figure 3.1), and appendix (Figure A.1)
# numbering styles.
_CAPTION_LINE = re.compile(
    r"^\s*(?:figure|fig\.|table)\s+(?:[A-Z]\.)?\d+(?:\.\d+)?",
    re.IGNORECASE | re.MULTILINE,
)

# Figure/table reference label patterns.
#
# group(1) — canonical label key: "1", "3.1", "A.1"
# group(2) — optional subfigure suffix letter ("a", "b") — NOT included in the key.
#
# (?:[A-Z]\.)? with IGNORECASE matches appendix-letter prefixes ("A.", "B.") but not
# digit characters, so "3." in "3.1" is never mistaken for a prefix.
_FIG_REF = re.compile(
    r"\b(?:figure|fig\.)\s+((?:[A-Z]\.)?\d+(?:\.\d+)?)([a-z])?",
    re.IGNORECASE,
)
_TAB_REF = re.compile(
    r"\btable\s+((?:[A-Z]\.)?\d+(?:\.\d+)?)([a-z])?",
    re.IGNORECASE,
)

# Numbered bibliography entry: [N] or N. followed by an uppercase letter.
# \d{1,3} rejects large numbers (page ranges, ISSN fragments) that can appear at
# line-starts after PDF text wrapping.  Requiring [A-Z] after the whitespace rules
# out "3313.\n  issn:…" continuations; real entries always start with an author
# surname or institution name (uppercase).
_NUMBERED_ENTRY = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}\.)\s+[A-Z]", re.MULTILINE)

# Numbered citation in main text: [N] or [N, M, ...]
_NUMBERED_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

# Appendix section heading.  Matches "Appendix", "Appendix A", "APPENDIX B",
# "Appendix A: Title", "Appendix B — Extra Data", etc. on their own line.
#
# Design notes:
#   (?im)          — inline IGNORECASE + MULTILINE flags
#   (?-i:[A-Z])    — uppercase letter only (IGNORECASE disabled for this group)
#                    so "Appendix a" or "appendix contents" do NOT match
#   [ \t]+         — space/tab only (not \s) so the optional group cannot
#                    span a newline and consume the next line
#   (?:[:\t \-\.].*)?  — optional subtitle text following the letter label
_APPENDIX_HEADING = re.compile(
    r"(?im)^\s*appendix(?:[ \t]+(?-i:[A-Z])(?:[:\t \-\.].*)?)?$"
)

# Author-year reference entry signals.
# A year in parentheses is the minimal marker of an author-year bibliography entry.
_REF_YEAR = re.compile(r"\(\d{4}[a-z]?\)")
# arXiv identifier — near-certain evidence that a line belongs to the reference list.
_ARXIV_ID = re.compile(r"\barXiv:\d{4}\.\d{4,5}\b", re.IGNORECASE)
# DOI — also strong evidence of a reference list line.
_DOI = re.compile(r"\bdoi:\s*10\.\d{4,}", re.IGNORECASE)


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


# Minimum fraction of pre_core that must precede an appendix heading for it
# to be treated as a genuine section heading rather than a TOC entry or an
# early cross-reference such as "see Appendix A for details".
_MIN_APPENDIX_FRACTION = 0.25


def _split_document(raw_text: str) -> tuple[str, str, str]:
    """
    Split raw extracted text into three named regions::

        (_core, _references, _appendices)

    Any region may be an empty string if not detected.  The function is the
    single authoritative entry point for all document splitting; downstream
    code should call this instead of ``_split_text`` directly.

    Algorithm
    ---------
    Step 1.  Locate the last bibliography heading → pre_core, pre_biblio
             (via ``_split_text``).

    Step 2a. Search *pre_biblio* for an appendix heading (type B report:
             core → references → appendices).  If found::

               _core        = pre_core
               _references  = pre_biblio up to appendix heading
               _appendices  = pre_biblio from appendix heading onwards

    Step 2b. Otherwise search *pre_core* for an appendix heading (type A
             report: core → appendices → references).  The heading must
             appear after ``_MIN_APPENDIX_FRACTION`` of pre_core to exclude
             TOC entries and early cross-references.  The first qualifying
             match marks the start of the appendix section::

               _core        = pre_core up to appendix heading
               _references  = pre_biblio
               _appendices  = pre_core from appendix heading onwards

    Step 2c. No appendix heading found anywhere::

               _core        = pre_core
               _references  = pre_biblio
               _appendices  = ""
    """
    pre_core, pre_biblio = _split_text(raw_text)

    # Step 2a — type B: appendix follows reference list
    app_match = _APPENDIX_HEADING.search(pre_biblio)
    if app_match:
        return (
            pre_core,
            pre_biblio[: app_match.start()],
            pre_biblio[app_match.start() :],
        )

    # Step 2b — type A: appendix precedes reference list
    min_pos = int(len(pre_core) * _MIN_APPENDIX_FRACTION)
    for match in _APPENDIX_HEADING.finditer(pre_core):
        if match.start() > min_pos:
            return (
                pre_core[: match.start()],
                pre_biblio,
                pre_core[match.start() :],
            )

    # Step 2c — no appendices detected
    return pre_core, pre_biblio, ""


# ---------------------------------------------------------------------------
# Pattern used to decide whether a line contains English prose.
# See _strip_math_lines() for the full rationale.
# ---------------------------------------------------------------------------

_ENGLISH_WORD = re.compile(r"[a-zA-Z]{5,}")

# Code-listing detection used to exclude source-code sentences from sentence CV.
_CODE_CHARS = frozenset("=()[]{}#")
_CODE_CHAR_RATIO_THRESHOLD = 0.04   # >4 % of chars are code punctuation
_UNDERSCORE_TOKEN_THRESHOLD = 0.15  # >15 % of whitespace-split tokens contain '_'


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


_MIN_CODE_BLOCK_LINES = 3  # runs shorter than this are kept (false-positive protection)


def _strip_code_blocks(text: str, min_run: int = _MIN_CODE_BLOCK_LINES) -> str:
    """Remove contiguous blocks of source-code lines from *text*.

    Uses _looks_like_code() per line, but only strips lines that belong to a
    run of >= min_run consecutive code-like lines.  Blank lines inside a run
    are treated as neutral and do not break it — a blank line between two code
    lines stays in the run, matching how code is commonly extracted from PDFs.

    Mirrors strip_code_blocks() in language_analysis_core.py.
    """
    lines = text.splitlines()

    # Tag each line: True = code-like, False = prose, None = blank
    tags: list[bool | None] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            tags.append(None)
        else:
            tags.append(_looks_like_code(stripped))

    # Resolve blank lines: a blank line is treated as code only when both its
    # preceding and following non-blank lines are code-like.
    # Forward pass: tentatively propagate True through blanks.
    resolved: list[bool] = [False] * len(tags)
    last = False
    for i, t in enumerate(tags):
        if t is True:
            last = True
        elif t is False:
            last = False
        else:  # blank
            pass  # keep last unchanged
        resolved[i] = last

    # Backward pass: un-mark blank lines whose next non-blank line is prose.
    last = False
    for i in range(len(tags) - 1, -1, -1):
        t = tags[i]
        if t is True:
            last = True
        elif t is False:
            last = False
        # blank inherits from forward pass unless backward pass disagrees
        if tags[i] is None and not last:
            resolved[i] = False

    # Remove runs of True that are long enough.
    keep = [True] * len(lines)
    i = 0
    while i < len(resolved):
        if resolved[i]:
            j = i
            while j < len(resolved) and resolved[j]:
                j += 1
            if (j - i) >= min_run:
                for k in range(i, j):
                    keep[k] = False
            i = j
        else:
            i += 1

    return "\n".join(line for line, k in zip(lines, keep) if k)


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

    For the heuristic fallback the text is first truncated at any appendix
    heading (appendices frequently follow the reference list and would
    otherwise inflate the count).  Lines are then filtered to those that
    carry strong signals of an author-year entry: a year in parentheses,
    an arXiv identifier, or a DOI.  If fewer than three such candidate
    lines are found the simple total-line count is used as a fallback to
    avoid under-counting documents whose format is unusual.
    """
    # Trim at the first appendix heading so appendix content is not counted.
    app_match = _APPENDIX_HEADING.search(biblio_text)
    if app_match:
        biblio_text = biblio_text[: app_match.start()]

    numbered = _NUMBERED_ENTRY.findall(biblio_text)
    if numbered:
        # Strip to just the bracket/dot keys for cross-referencing
        keys = [k.strip().strip(".").strip("[]") for k in numbered]
        # Validate: a genuine numbered bibliography must start near 1.
        # If the minimum numeric key is large (e.g. 82 from a wrapped page-range
        # "p.\n82. TITLE") treat the whole match as a false positive and fall through
        # to the author-year heuristic.
        try:
            if min(int(k) for k in keys) <= 5:
                return len(keys), keys
        except ValueError:
            return len(keys), keys  # non-integer keys — trust the match

    # Heuristic: count non-blank lines after the heading as a rough entry count.
    lines = [ln.strip() for ln in biblio_text.splitlines() if ln.strip()]
    # Skip the heading line itself.
    body_lines = [
        ln
        for ln in lines[1:]
        if ln and not ln.lower().startswith(("ref", "biblio", "works"))
    ]

    # Stage 1: prefer lines that look like author-year reference entries.
    # Signals: year in parentheses, arXiv identifier, or a DOI.
    entry_candidates = [
        ln
        for ln in body_lines
        if _REF_YEAR.search(ln) or _ARXIV_ID.search(ln) or _DOI.search(ln)
    ]

    # Stage 2: if too few candidates found, fall back to the total line count.
    if len(entry_candidates) >= 3:
        return len(entry_candidates), []
    return len(body_lines), []


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

    Labels are normalised to their canonical form before deduplication:
    - Chapter-relative numbers: "Figure 3.1", "Figure 4.5" → keys "3.1", "4.5"
    - Appendix figures:         "Figure A.1", "Figure B.3" → keys "A.1", "B.3"
    - Subfigure panels:         "Figure 3.1a", "Figure 3.1b" → key "3.1"
      (panel letters are stripped; panels are not counted as separate figures)
    """
    fig_labels: dict[str, str] = {}  # key -> display string, e.g. "3.1" -> "Figure 3.1"
    tab_labels: dict[str, str] = {}

    # _FIG_REF group(1) = canonical key; group(2) = optional subfigure suffix (ignored).
    for m in _FIG_REF.finditer(text):
        n = m.group(1)
        if n not in fig_labels:
            fig_labels[n] = f"Figure {n}"

    for m in _TAB_REF.finditer(text):
        n = m.group(1)
        if n not in tab_labels:
            tab_labels[n] = f"Table {n}"

    # A label is considered cited if it appears more than once in the text.
    # The citation pattern accepts an optional trailing subfigure suffix so that
    # "Figure 3.1a" counts as a citation of key "3.1".
    def _cited(pattern: str) -> bool:
        return len(re.findall(pattern, text, re.IGNORECASE)) > 1

    uncaptioned_figs = [
        label
        for n, label in fig_labels.items()
        if not _cited(rf"\b(?:figure|fig\.)\s+{re.escape(n)}[a-z]?\b")
    ]
    uncaptioned_tabs = [
        label
        for n, label in tab_labels.items()
        if not _cited(rf"\btable\s+{re.escape(n)}[a-z]?\b")
    ]

    return uncaptioned_figs, uncaptioned_tabs


def _compute_mattr_mtld(main_text: str) -> tuple[float | None, float | None]:
    """
    Compute MATTR (window=100) and MTLD for *main_text*.
    Returns (mattr, mtld), either of which may be None on failure.
    Requires at least 100 words; fewer returns (None, None).

    Code blocks are stripped before analysis to prevent source-code identifiers
    from artificially inflating vocabulary diversity.
    """
    try:
        from lexicalrichness import LexicalRichness

        lex = LexicalRichness(_strip_code_blocks(main_text))
        if lex.words < 100:
            print(
                f"_compute_matr_mtld: too few words to compute MATTR and MTLD statistics ({lex.words} words detected)"
            )
            return None, None
        mattr = float(lex.mattr(window_size=100))
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


def _looks_like_code(text: str) -> bool:
    """Return True when *text* looks more like source code than prose.

    Two independent signals, either of which is sufficient:
      1. High density of code-typical punctuation (=, (, ), [, ], {, }, #).
      2. High fraction of whitespace-split tokens that contain an underscore
         (Python/C-style identifiers).
    """
    if not text:
        return False
    code_ratio = sum(1 for ch in text if ch in _CODE_CHARS) / len(text)
    if code_ratio > _CODE_CHAR_RATIO_THRESHOLD:
        return True
    tokens = text.split()
    if tokens:
        underscore_ratio = sum(1 for t in tokens if "_" in t) / len(tokens)
        if underscore_ratio > _UNDERSCORE_TOKEN_THRESHOLD:
            return True
    return False


def _compute_sentence_cv(text: str) -> float | None:
    """
    Compute the coefficient of variation (CV = σ/μ) of sentence lengths for *text*.

    Sentence length is measured as the number of non-punctuation, non-space tokens
    per sentence, using spaCy's sentence segmentation.  Returns None if fewer than
    5 sentences are found (insufficient data for a stable estimate).

    Sentences that look like source code (high code-punctuation density or high
    underscore-identifier fraction) are excluded before computing the CV.
    """
    nlp = _get_nlp()
    doc = nlp(text)

    lengths = [
        sum(1 for tok in sent if not tok.is_punct and not tok.is_space)
        for sent in doc.sents
        if not _looks_like_code(sent.text)
    ]
    # Discard empty or single-token sentences (e.g. section headings misread as sentences)
    lengths = [ln for ln in lengths if ln > 1]

    if len(lengths) < 5:
        return None

    mu = float(np.mean(lengths))
    if mu == 0.0:
        return None
    sigma = float(np.std(lengths, ddof=1))
    return sigma / mu


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


def _ai_concern_flag(
    mattr: float | None,
    mtld: float | None,
    sentence_cv: float | None,
    calibration: dict | None,
) -> dict:
    """
    Classify the overall AI concern level using the Mahalanobis distance from
    the pre-LLM centroid in (MATTR, MTLD, sentence_CV) space.

    Background
    ----------
    Let x = (MATTR, MTLD, sentence_CV) and let μ, Σ be the mean vector and
    covariance matrix estimated from a set of pre-LLM submissions (years
    2019/20–2021/22 by default).  The squared Mahalanobis distance

        D² = (x − μ)ᵀ Σ⁻¹ (x − μ)

    follows a chi²(df=3) distribution under the null hypothesis that the
    submission was drawn from the same pre-LLM population.  We therefore
    classify using survival-function (upper-tail) p-value thresholds:

        p > 0.05          → "low"    (D² < chi²_0.95(3) ≈ 7.815, σ < 2.80)
        0.01 < p ≤ 0.05   → "medium" (D² ≥ chi²_0.95(3), σ ≥ 2.80)
        p ≤ 0.01          → "high"   (D² ≥ chi²_0.99(3) ≈ 11.345, σ ≥ 3.37)

    The chi² thresholds are derived at runtime from scipy.stats.chi2.isf so
    the source of the cut-off values is transparent and not hard-coded.

    Because MATTR and MTLD are strongly correlated the empirical covariance
    matrix is often ill-conditioned; the calibration module inverts it via the
    Moore-Penrose pseudoinverse (numpy.linalg.pinv), which is robust to this.

    Graceful degradation
    --------------------
    Returns concern="uncalibrated" (with sigma=None, p_value=None) when:
      - calibration is None (tenant has not yet run the calibration step), or
      - any of the three required metric values is None (report too short for
        reliable measurement).

    Returns
    -------
    dict with keys:
        "concern"  : "low" | "medium" | "high" | "uncalibrated"
        "sigma"    : float | None  — Mahalanobis sigma (= sqrt(D²))
        "p_value"  : float | None  — P(chi²(3) > D²)
    """
    from scipy.stats import chi2 as _chi2

    _UNCALIBRATED = {"concern": "uncalibrated", "sigma": None, "p_value": None}

    if calibration is None or mattr is None or mtld is None or sentence_cv is None:
        return _UNCALIBRATED

    try:
        sigma, p_value = mahalanobis_distance(mattr, mtld, sentence_cv, calibration)
    except Exception:
        return _UNCALIBRATED

    # Derive thresholds from the chi²(df=3) distribution at the desired
    # significance levels.  isf(q, df) = inverse survival function = the value
    # x such that P(chi²(df) > x) = q.
    #
    #   isf(0.05, 3) ≈ 7.815  →  sqrt ≈ 2.795  (commonly quoted as 2.80)
    #   isf(0.01, 3) ≈ 11.345 →  sqrt ≈ 3.368  (commonly quoted as 3.37)
    _SIGMA_MEDIUM = float(_chi2.isf(0.05, df=3) ** 0.5)  # p < 0.05 threshold
    _SIGMA_HIGH = float(_chi2.isf(0.01, df=3) ** 0.5)    # p < 0.01 threshold

    if sigma >= _SIGMA_HIGH:
        concern = "high"
    elif sigma >= _SIGMA_MEDIUM:
        concern = "medium"
    else:
        concern = "low"

    return {"concern": concern, "sigma": sigma, "p_value": p_value}


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

# ---------------------------------------------------------------------------
# Context-window-aware chunking constants.
#
# Token estimates use 1.4 tokens/word — a conservative BPE approximation
# for academic English prose.  All overhead figures are generous upper-bound
# estimates to avoid exceeding the context window.
# ---------------------------------------------------------------------------

_TOKENS_PER_WORD = 1.4

# Overhead tokens for the full single-pass assessment call:
#   system prompt (~1 200) + structured response with 26 criteria (~2 000).
_SINGLE_PASS_OVERHEAD_TOKENS = 3200

# Overhead tokens for each map-phase (evidence extraction) chunk call:
#   small system prompt (~400) + evidence array response (~400).
_MAP_PASS_OVERHEAD_TOKENS = 800

# Overhead tokens for the synthesis (reduce) pass:
#   full system prompt (~1 200) + full response (~2 000) + safety margin.
_SYNTHESIS_OVERHEAD_TOKENS = 3500

# Minimum num_ctx to request for the synthesis pass even when OLLAMA_CONTEXT_SIZE
# is set to a smaller value, to give the evidence summary enough room.
_SYNTHESIS_MIN_CTX = 8192

# Overhead tokens for the dedicated metadata extraction call:
#   small system prompt (~250) + small schema response (~250).
_METADATA_OVERHEAD_TOKENS = 500

# Overhead tokens for a single feedback chunk call:
#   small system prompt (~200) + feedback array response (~200).
_FEEDBACK_OVERHEAD_TOKENS = 400

# Maximum evidence entries retained per criterion code after map-phase
# aggregation.  Minority-polarity entries are always kept (one each).
_MAX_EVIDENCE_PER_CRITERION = 3

# Excerpt character limit applied when the synthesis evidence text would
# otherwise overflow the synthesis context window.
_MAX_EXCERPT_CHARS = 150


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
# Shared LLM call helper.
# ---------------------------------------------------------------------------


def _call_llm(
    client,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema: dict,
    options: dict | None = None,
    validate_fn=None,
    label: str = "llm",
) -> tuple[dict | None, str, Exception | None]:
    """
    Submit a prompt to the Ollama LLM with the standard retry logic.

    Returns (parsed_result, last_accumulated_text, last_exception).
    parsed_result is None if all attempts failed.
    """
    import ollama

    accumulated = ""
    last_exc: Exception | None = None
    parsed_result: dict | None = None

    for attempt in range(_LLM_RETRY_ATTEMPTS):
        accumulated = ""
        try:
            kwargs: dict = dict(
                model=model,
                prompt=user_prompt,
                system=system_prompt,
                format=schema,
                stream=True,
            )
            if options:
                kwargs["options"] = options

            stream = client.generate(**kwargs)
            for chunk in stream:
                if hasattr(chunk, "response"):
                    accumulated += chunk.response
                elif isinstance(chunk, dict):
                    accumulated += chunk.get("response", "")

            parsed = json.loads(accumulated)
            if validate_fn is not None and not validate_fn(parsed):
                raise ValueError(
                    f"LLM response missing required keys; got: {list(parsed.keys())}"
                )
            parsed_result = parsed
            last_exc = None
            break

        except ollama.ResponseError as exc:
            last_exc = exc
            status = getattr(exc, "status_code", 0)
            if 400 <= status < 500:
                current_app.logger.error(f"{label}: permanent HTTP {status} error: {exc}")
                break
            current_app.logger.warning(
                f"{label}: transient HTTP error on attempt {attempt + 1}: {exc}"
            )
            if attempt < _LLM_RETRY_ATTEMPTS - 1:
                time.sleep(_LLM_RETRY_DELAY)

        except SoftTimeLimitExceeded:
            raise  # must not be swallowed — propagate so the task fails cleanly

        except (json.JSONDecodeError, ValueError) as exc:
            last_exc = exc
            current_app.logger.warning(
                f"{label}: JSON parse failure on attempt {attempt + 1}: {exc}"
            )
            if attempt < _LLM_RETRY_ATTEMPTS - 1:
                time.sleep(_LLM_RETRY_DELAY)

        except Exception as exc:
            last_exc = exc
            current_app.logger.warning(
                f"{label}: transient error on attempt {attempt + 1}: {exc}"
            )
            if attempt < _LLM_RETRY_ATTEMPTS - 1:
                time.sleep(_LLM_RETRY_DELAY)

    return parsed_result, accumulated, last_exc


# ---------------------------------------------------------------------------
# Feedback deduplication helper.
# ---------------------------------------------------------------------------


def _deduplicate_feedback(items: list[str], max_items: int) -> list[str]:
    """
    Deduplicate feedback strings and return at most *max_items* entries.
    Longer items are preferred as a proxy for specificity.
    """
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        normalised = item.strip().lower()
        if normalised not in seen:
            seen.add(normalised)
            unique.append(item.strip())
    unique.sort(key=len, reverse=True)
    return unique[:max_items]


# ---------------------------------------------------------------------------
# Regex patterns for metadata region location.
# ---------------------------------------------------------------------------

_PREFACE_HEADING_RE = re.compile(
    r"^\s*(preface|personal\s+statement"
    r"|declaration(?:\s+of\s+(?:originality|contribution))?"
    r"|acknowledgements?(?:\s+and\s+contribution(?:\s+statement)?)?"
    r"|contribution\s+statement|author.?s?\s+contribution"
    r"|personal\s+contribution)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_AI_HEADING_RE = re.compile(
    r"^\s*((?:use\s+of\s+)?(?:generative\s+)?ai(?:\s+tools?)?(?:\s+(?:statement|declaration|disclosure|policy|use))?"
    r"|statement\s+on\s+(?:generative\s+)?ai(?:\s+use)?"
    r"|declaration\s+on\s+(?:generative\s+)?ai(?:\s+use)?"
    r"|chatgpt\s+(?:statement|use|policy)"
    r"|large\s+language\s+model\s+(?:statement|use|policy))\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_AI_KEYWORD_SENTENCE_RE = re.compile(
    r"(?:[A-Z][^.!?\n]*)?"
    r"(?:generative\s+ai|chatgpt|gpt-?\d*|large\s+language\s+model"
    r"|github\s+copilot|claude\s+ai|gemini\s+ai|copilot\s+ai)"
    r"[^.!?\n]*[.!?]",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Metadata region extraction (regex-based location step).
# ---------------------------------------------------------------------------


def _extract_metadata_regions(text: str) -> str:
    """
    Locate candidate text regions for the dedicated metadata LLM call using regex.

    Returns a condensed string containing:
      - front matter up to the first chapter heading (or first 1 500 words),
      - any paragraph block whose heading matches a preface pattern,
      - any paragraph block whose heading matches an AI declaration pattern,
      - fallback: sentences containing AI-related keywords if no heading was found.

    This text is passed verbatim to the metadata LLM; it is never submitted to
    the main assessment LLM.
    """
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]

    # Collect front matter: stop at "Chapter 1" / "Introduction" or after 1 500 words.
    front_end_idx = len(paragraphs)
    word_count = 0
    for i, para in enumerate(paragraphs):
        if re.match(
            r"^\s*(chapter\s+1\b|1[.\s]\s*introduction\b|introduction\s*$)",
            para,
            re.IGNORECASE,
        ):
            front_end_idx = i
            break
        word_count += len(para.split())
        front_end_idx = i + 1
        if word_count >= 1500:
            break

    candidate_indices: set[int] = set(range(front_end_idx))

    # Locate named preface and AI sections anywhere in the document.
    for i, para in enumerate(paragraphs):
        stripped = para.strip()
        if not (_PREFACE_HEADING_RE.match(stripped) or _AI_HEADING_RE.match(stripped)):
            continue
        candidate_indices.add(i)
        for j in range(i + 1, min(i + 25, len(paragraphs))):
            body = paragraphs[j].strip()
            # Stop when we reach what looks like the next section heading:
            # a single short line without terminal punctuation.
            is_next_heading = (
                "\n" not in body
                and len(body.split()) <= 10
                and not body.endswith((".", ",", ";", ":", "?", "!"))
            )
            if is_next_heading and j > i + 1:
                break
            candidate_indices.add(j)

    region_text = "\n\n".join(paragraphs[i] for i in sorted(candidate_indices))

    # If no named AI section was found, append any AI-keyword sentences from the
    # full document as a last-resort fallback.
    ai_section_found = any(
        _AI_HEADING_RE.match(paragraphs[i].strip()) for i in candidate_indices
    )
    if not ai_section_found:
        ai_sentences = _AI_KEYWORD_SENTENCE_RE.findall(text)
        if ai_sentences:
            region_text += (
                "\n\n---\n\nPossible AI use statements found elsewhere in document:\n"
                + "\n".join(s.strip() for s in ai_sentences[:5])
            )

    return region_text


# ---------------------------------------------------------------------------
# Document chunking.
# ---------------------------------------------------------------------------


def _build_chunks(text: str, max_words: int) -> list[str]:
    """
    Split *text* into chunks of at most *max_words* words, breaking at paragraph
    boundaries (double newlines) where possible.  Falls back to sentence
    boundaries for paragraphs that individually exceed *max_words*.
    """
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current_paras: list[str] = []
    current_words = 0

    for para in paragraphs:
        w = len(para.split())
        if w > max_words:
            # Oversized single paragraph — split at sentence boundaries.
            if current_paras:
                chunks.append("\n\n".join(current_paras))
                current_paras, current_words = [], 0
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                sw = len(sent.split())
                if current_words + sw > max_words and current_paras:
                    chunks.append("\n\n".join(current_paras))
                    current_paras, current_words = [sent], sw
                else:
                    current_paras.append(sent)
                    current_words += sw
        elif current_words + w > max_words and current_paras:
            chunks.append("\n\n".join(current_paras))
            current_paras, current_words = [para], w
        else:
            current_paras.append(para)
            current_words += w

    if current_paras:
        chunks.append("\n\n".join(current_paras))

    return chunks


# ---------------------------------------------------------------------------
# Map-phase (chunk evidence extraction) helpers.
# ---------------------------------------------------------------------------

_LLM_CHUNK_SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion_code": {"type": "string"},
                    "excerpt": {"type": "string"},
                    "observation": {"type": "string"},
                    "polarity": {
                        "type": "string",
                        "enum": ["supports", "undermines", "neutral"],
                    },
                },
                "required": ["criterion_code", "excerpt", "observation", "polarity"],
            },
        },
        "metadata_hits": {
            "type": "object",
            "properties": {
                "stated_word_count_found": {"type": "boolean"},
                "stated_word_count": {"type": ["integer", "null"]},
                "genai_statement_found": {"type": "boolean"},
                "genai_statement": {"type": "string"},
                "preface_found": {"type": "boolean"},
                "preface_precis": {"type": "string"},
            },
            "required": [
                "stated_word_count_found",
                "stated_word_count",
                "genai_statement_found",
                "genai_statement",
                "preface_found",
                "preface_precis",
            ],
        },
    },
    "required": ["evidence", "metadata_hits"],
}


def _build_chunk_system_prompt(chunk_idx: int, total_chunks: int) -> str:
    """Compact system prompt for the map-phase evidence extraction call."""
    criterion_lines = []
    for band_idx, band in enumerate(GRADE_BANDS, start=1):
        for crit_idx, criterion in enumerate(band["criteria"], start=1):
            criterion_lines.append(f"  {band_idx}.{crit_idx}: {criterion}")
    criterion_list = "\n".join(criterion_lines)

    return f"""You are extracting evidence from a portion of a student project report.

This is chunk {chunk_idx + 1} of {total_chunks}. Do NOT assess or classify the work overall.

For each passage that is relevant to any of the criteria listed below, record one evidence entry:
  - criterion_code: the numeric code from the list (e.g. "1.1", "3.4")
  - excerpt: verbatim quote of at most 2 sentences from this chunk
  - observation: one sentence explaining why the passage is relevant
  - polarity: "supports" if the passage shows the criterion is met, "undermines" if it shows the criterion is not met, or "neutral"

If no genuine evidence exists for a criterion in this chunk, do not record an entry for it. An empty evidence array is correct when the chunk contains no relevant passages.

Also check metadata_hits for:
  - A stated word count (e.g. "Word count: 12,345")
  - A statement about generative AI use or non-use
  - A preface or personal contribution statement

## Criteria

{criterion_list}"""


def _build_chunk_user_prompt(chunk_text: str, chunk_idx: int, total_chunks: int) -> str:
    return (
        f"Please extract evidence from the following text "
        f"(chunk {chunk_idx + 1} of {total_chunks}):\n\n---\n\n{chunk_text}\n\n---"
    )


# ---------------------------------------------------------------------------
# Metadata extraction helpers.
# ---------------------------------------------------------------------------

_LLM_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "stated_word_count_found": {"type": "boolean"},
        "stated_word_count": {"type": ["integer", "null"]},
        "genai_statement_found": {"type": "boolean"},
        "genai_statement": {"type": "string"},
        "preface_found": {"type": "boolean"},
        "preface_precis": {"type": "string"},
    },
    "required": [
        "stated_word_count_found",
        "stated_word_count",
        "genai_statement_found",
        "genai_statement",
        "preface_found",
        "preface_precis",
    ],
}


def _build_metadata_system_prompt() -> str:
    return """You are extracting structured metadata from a student project report.

Your task is to identify and extract the following items, if present in the provided text:

1. **Stated word count**: An explicit word count declared by the student (e.g. under a label such as "Word count:", "Total word count:", or similar). Record the integer value if found.

2. **Generative AI statement**: Any statement about the student's use — or explicit non-use — of generative AI tools such as ChatGPT, GitHub Copilot, or similar. Copy the verbatim text of the statement, or its first sentence if it is very long. This is a personal declaration by the student, not a reference to AI in the domain of study.

3. **Preface / personal contribution statement**: A section (typically headed "Preface", "Personal Statement", "Declaration of Contribution", or similar) describing the student's personal contribution to the project work. Provide a 1–3 sentence précis of what the student claims they personally did.

Record items not found as: stated_word_count_found = false, stated_word_count = null, genai_statement_found = false, genai_statement = "", preface_found = false, preface_precis = ""."""


def _build_metadata_user_prompt(candidate_text: str) -> str:
    return (
        f"Please extract metadata from the following document excerpt:\n\n"
        f"---\n\n{candidate_text}\n\n---"
    )


# ---------------------------------------------------------------------------
# Map-phase evidence aggregation helpers.
# ---------------------------------------------------------------------------

# All valid criterion codes — used to filter out hallucinated codes from the LLM.
_ALL_CRITERION_CODES: frozenset = frozenset(
    f"{band_idx}.{crit_idx}"
    for band_idx, band in enumerate(GRADE_BANDS, start=1)
    for crit_idx in range(1, len(band["criteria"]) + 1)
)


def _merge_chunk_evidence(chunk_results: dict) -> dict:
    """
    Aggregate per-chunk evidence from the map phase.

    Preponderance is preserved: if a criterion is overwhelmingly supported
    (e.g. 6 'supports', 0 'undermines') that dominance is reflected in both
    the retained excerpts and the count header written into the synthesis prompt.
    The retention policy is:
      - Keep at most _MAX_EVIDENCE_PER_CRITERION entries total per criterion.
      - Always include at least one entry from every polarity that exists
        (genuine minority evidence is informative).
      - Fill remaining slots with entries from the dominant polarity.

    Metadata is merged with OR semantics for booleans and first-found semantics
    for string values (the first chunk that identifies a field wins).

    Returns:
        {
          "criteria": {
            code: {
              "entries": [evidence_dict, ...],
              "counts": {"supports": N, "undermines": N, "neutral": N,
                         "chunks_with_evidence": N}
            }
          },
          "metadata": { stated_word_count_found, stated_word_count,
                         genai_statement_found, genai_statement,
                         preface_found, preface_precis }
        }
    """
    from collections import defaultdict

    raw: dict[str, dict[str, list]] = defaultdict(
        lambda: {"supports": [], "undermines": [], "neutral": []}
    )
    chunks_with_evidence: dict[str, set] = defaultdict(set)
    metadata: dict = {
        "stated_word_count_found": False,
        "stated_word_count": None,
        "genai_statement_found": False,
        "genai_statement": "",
        "preface_found": False,
        "preface_precis": "",
    }

    for chunk_idx_str, chunk_data in chunk_results.items():
        chunk_idx = int(chunk_idx_str)

        # Merge metadata (OR / first-found).
        hits = chunk_data.get("metadata_hits", {})
        if hits.get("stated_word_count_found") and not metadata["stated_word_count_found"]:
            metadata["stated_word_count_found"] = True
            metadata["stated_word_count"] = hits.get("stated_word_count")
        if hits.get("genai_statement_found") and not metadata["genai_statement_found"]:
            metadata["genai_statement_found"] = True
            metadata["genai_statement"] = hits.get("genai_statement", "")
        if hits.get("preface_found") and not metadata["preface_found"]:
            metadata["preface_found"] = True
            metadata["preface_precis"] = hits.get("preface_precis", "")

        # Accumulate evidence.
        for entry in chunk_data.get("evidence", []):
            code = entry.get("criterion_code", "")
            polarity = entry.get("polarity", "neutral")
            if code not in _ALL_CRITERION_CODES:
                continue
            if polarity not in ("supports", "undermines", "neutral"):
                polarity = "neutral"
            raw[code][polarity].append(entry)
            chunks_with_evidence[code].add(chunk_idx)

    # Apply retention policy.
    criteria: dict = {}
    for code, polarities in raw.items():
        supports = polarities["supports"]
        undermines = polarities["undermines"]
        neutral = polarities["neutral"]

        counts = {
            "supports": len(supports),
            "undermines": len(undermines),
            "neutral": len(neutral),
            "chunks_with_evidence": len(chunks_with_evidence[code]),
        }

        # Sort polarities by count descending to find dominant.
        by_count = sorted(
            [("supports", supports), ("undermines", undermines), ("neutral", neutral)],
            key=lambda x: len(x[1]),
            reverse=True,
        )
        dominant_name, dominant_entries = by_count[0]

        # One entry from each minority polarity that actually exists.
        minority: list[dict] = []
        for _, entries in by_count[1:]:
            if entries:
                minority.append(entries[0])

        # Fill remaining slots with dominant entries.
        remaining = max(_MAX_EVIDENCE_PER_CRITERION - len(minority), 0)
        retained = dominant_entries[:remaining] + minority

        criteria[code] = {"entries": retained, "counts": counts}

    return {"criteria": criteria, "metadata": metadata}


# ---------------------------------------------------------------------------
# Synthesis (reduce-phase) helpers.
# ---------------------------------------------------------------------------


def _build_synthesis_evidence_text(merged: dict, total_chunks: int) -> str:
    """
    Format aggregated chunk evidence as structured text for the synthesis prompt.
    This replaces the document text in the synthesis user prompt.

    Per-criterion count headers convey preponderance to the synthesis LLM so it
    can distinguish criteria with overwhelming evidence from those that are
    genuinely ambiguous.
    """
    criteria_data: dict = merged["criteria"]
    metadata: dict = merged["metadata"]
    chunk_word = "chunk" if total_chunks == 1 else "chunks"

    lines = [f"## Extracted evidence ({total_chunks} {chunk_word})", ""]

    for band_idx, band in enumerate(GRADE_BANDS, start=1):
        lines.append(f"### Band {band_idx} — {band['band']}")
        for crit_idx, criterion in enumerate(band["criteria"], start=1):
            code = f"{band_idx}.{crit_idx}"
            crit_data = criteria_data.get(code)
            lines.append(f"\n**{code}** {criterion}")
            if crit_data is None:
                lines.append("  (No evidence found in any chunk)")
                continue

            counts = crit_data["counts"]
            count_summary = (
                f"{counts['supports']} supporting, "
                f"{counts['undermines']} undermining, "
                f"{counts['neutral']} neutral "
                f"across {counts['chunks_with_evidence']} of {total_chunks} {chunk_word}"
            )
            lines.append(f"  Evidence count: {count_summary}")

            for entry in crit_data["entries"]:
                tag = entry["polarity"].upper()
                excerpt = entry["excerpt"]
                if len(excerpt) > _MAX_EXCERPT_CHARS:
                    excerpt = excerpt[:_MAX_EXCERPT_CHARS] + "…"
                lines.append(f'  [{tag}] "{excerpt}"')
                lines.append(f"  {entry['observation']}")
        lines.append("")

    lines.append("## Document metadata")
    if metadata["stated_word_count_found"]:
        lines.append(f"- Stated word count: {metadata['stated_word_count']}")
    else:
        lines.append("- Stated word count: not found")

    if metadata["genai_statement_found"]:
        lines.append(f'- GenAI statement: "{metadata["genai_statement"]}"')
    else:
        lines.append("- GenAI statement: not found")

    if metadata["preface_found"]:
        lines.append(f'- Preface/personal contribution: "{metadata["preface_precis"]}"')
    else:
        lines.append("- Preface/personal contribution: not found")

    return "\n".join(lines)


def _build_synthesis_user_prompt(evidence_text: str) -> str:
    return (
        "The full report has been pre-read and relevant passages extracted by assessment criterion.\n"
        "Use the evidence below to produce your final grade band assessment.\n\n"
        "The evidence entries include counts of supporting and undermining passages per criterion. "
        "Use these counts to judge preponderance, not just the individual quoted excerpts: "
        "a criterion with 6 supporting and 0 undermining passages deserves 'Strong evidence', "
        "not 'Partial evidence'.\n\n"
        "For criteria with no evidence entries, use 'Not evident' with low confidence.\n\n"
        "For the metadata fields (stated_word_count, genai_statement, preface), copy the values "
        "recorded in the 'Document metadata' section verbatim into your response.\n\n"
        f"{evidence_text}"
    )


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

        # --- split into core, references, and appendices ---------------------
        # _split_document() implements the priority-ordered 3-way split:
        #   _core       — main body text (no references, no appendices)
        #   _references — bibliography / reference list
        #   _appendices — appendix sections (may be empty)
        _core, _references, _appendices = _split_document(raw_text)

        # Strip math-extraction noise from the core body text.  Appendix text
        # is also stripped separately for appendix word counting.
        # See _strip_math_lines() for full rationale and threshold choice.
        clean_core_text = _strip_math_lines(_core)

        # Content text for figure/table detection: core + appendices (not refs).
        _content_text = _core + ("\n\n" + _appendices if _appendices else "")

        # Stripped content text for lexical diversity and sentence-structure metrics.
        # Appendices are included because they are the student's own writing, consistent
        # with the text submitted to the LLM.  Word count stays core-only (see above).
        clean_content_text = _strip_math_lines(_content_text)

        _t_counting = time.monotonic()

        # --- word count (core body only — appendices excluded) ---------------
        try:
            wc = _word_count(clean_core_text)
            metrics["word_count"] = wc
            # Appendix word count stored separately so the UI can surface both.
            if _appendices:
                appendix_wc = _word_count(_strip_math_lines(_appendices))
                if appendix_wc > 0:
                    metrics["appendix_word_count"] = appendix_wc
        except Exception as exc:
            errors.append(
                {"stage": "word_count", "type": type(exc).__name__, "message": str(exc)}
            )
            metrics["word_count"] = None

        # --- bibliography count and citation check ----------------------------
        try:
            ref_count, ref_keys = _count_bibliography(_references)
            metrics["reference_count"] = ref_count

            uncited = _check_uncited(_core, ref_keys)
            references_info["uncited"] = uncited
        except Exception as exc:
            errors.append(
                {"stage": "references", "type": type(exc).__name__, "message": str(exc)}
            )
            metrics["reference_count"] = None
            references_info["uncited"] = []

        # --- figure and table cross-reference check --------------------------
        try:
            uncaptioned_figs, uncaptioned_tabs = _check_figure_table_refs(_content_text)
            # Count distinct canonical labels (e.g. "3.1", "A.1") in core + appendices.
            fig_labels = {m.group(1) for m in _FIG_REF.finditer(_content_text)}
            tab_labels = {m.group(1) for m in _TAB_REF.finditer(_content_text)}
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
            mattr, mtld = _compute_mattr_mtld(clean_content_text)
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

        # --- sentence CV -----------------------------------------------------
        try:
            metrics["sentence_cv"] = _compute_sentence_cv(clean_content_text)
        except Exception as exc:
            errors.append(
                {"stage": "sentence_cv", "type": type(exc).__name__, "message": str(exc)}
            )
            metrics["sentence_cv"] = None

        # --- pattern matching ------------------------------------------------
        try:
            patterns_info = _count_patterns(raw_text)
        except Exception as exc:
            errors.append(
                {"stage": "patterns", "type": type(exc).__name__, "message": str(exc)}
            )

        # --- classification flags --------------------------------------------
        mattr_flag = classify_mattr(metrics.get("mattr"))
        mtld_flag = classify_mtld(metrics.get("mtld"))
        burst_flag = classify_burstiness(metrics.get("burstiness"))
        cv_flag = classify_sentence_cv(metrics.get("sentence_cv"))

        # Fetch calibration data from the tenant associated with this project class.
        calibration: dict | None = None
        try:
            pclass = record.period.config.project_class
            tenant = pclass.tenant if pclass else None
            calibration = tenant.ai_calibration_data if tenant else None
        except Exception:
            calibration = None

        ai_result = _ai_concern_flag(
            metrics.get("mattr"),
            metrics.get("mtld"),
            metrics.get("sentence_cv"),
            calibration,
        )

        flags = {
            "mattr_flag": mattr_flag,
            "mtld_flag": mtld_flag,
            "burstiness_flag": burst_flag,
            "sentence_cv_flag": cv_flag,
            "ai_concern": ai_result["concern"],
            "mahalanobis_sigma": ai_result["sigma"],
            "mahalanobis_pvalue": ai_result["p_value"],
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

    @celery.task(bind=True, default_retry_delay=30, soft_time_limit=7200, time_limit=7260)
    def submit_to_llm(self, record_id: int):
        """
        Stage 3 (llm_tasks queue): submit the extracted report text to an Ollama
        LLM for grade-band assessment.

        Short documents that fit within the context window are submitted in a
        single pass (unchanged behaviour).  Longer documents use a two-phase
        map-reduce strategy:

          Map phase — each chunk is submitted with _LLM_CHUNK_SCHEMA to
                      extract per-criterion evidence fragments.  A dedicated
                      metadata call (regex location + _LLM_METADATA_SCHEMA)
                      extracts the GenAI statement and preface text from the
                      identified front-matter regions.  All intermediate
                      results are persisted to the JSON blob after each chunk
                      so the task is safely resumable on Celery retry.

          Reduce phase — _merge_chunk_evidence() aggregates the map results,
                         preserving preponderance (evidence counts per criterion
                         are passed to the synthesis LLM alongside excerpts).
                         The synthesis call uses the full _LLM_RESPONSE_SCHEMA
                         and produces output structurally identical to the
                         single-pass result.

        Retries up to _LLM_RETRY_ATTEMPTS times per LLM call; permanent
        failures set llm_analysis_failed.  Records with llm_analysis_failed=True
        are not retried until an administrator explicitly clears the flag.
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

        # Build the text for grade-band assessment: core body + appendices.
        # The reference list is excluded (bibliographic entries are noise for
        # the LLM assessor).  Math-extraction artefacts are stripped so that
        # equation fragments do not waste context tokens.
        _core, _references, _appendices = _split_document(raw_text)
        clean_text = _strip_math_lines(_core)
        if _appendices:
            clean_text = clean_text + "\n\n" + _strip_math_lines(_appendices)

        context_size: int = current_app.config.get("OLLAMA_CONTEXT_SIZE", 4096)
        base_url: str = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model: str = current_app.config.get("OLLAMA_MODEL", "llama3.1:70b")

        import ollama

        client = ollama.Client(host=base_url)

        # Release the DB connection back to the pool before the long-running LLM call.
        # The connection can sit idle for 5-10+ minutes during LLM inference, which
        # may exceed the MySQL server-side wait_timeout and leave it stale.  All
        # required data has already been read into local Python variables above.
        # The record will be reloaded from the DB before each subsequent write.
        db.session.close()

        single_pass_word_budget = max(
            int((context_size - _SINGLE_PASS_OVERHEAD_TOKENS) / _TOKENS_PER_WORD), 0
        )
        doc_words = len(clean_text.split())
        errors: list = data.get("errors", [])
        _t_llm = time.monotonic()

        accumulated = ""
        last_exc: Exception | None = None
        parsed_result: dict | None = None
        num_chunks = 1  # updated to actual chunk count on the chunked path

        if doc_words <= single_pass_word_budget:
            # ----------------------------------------------------------------
            # Single-pass path: document fits within the context window.
            # ----------------------------------------------------------------
            document_text, was_truncated = _truncate_text(clean_text)
            parsed_result, accumulated, last_exc = _call_llm(
                client,
                model,
                _build_system_prompt(was_truncated),
                _build_user_prompt(document_text),
                _LLM_RESPONSE_SCHEMA,
                options={"num_ctx": context_size},
                validate_fn=_validate_llm_response,
                label=f"submit_to_llm/single-pass (record #{record_id})",
            )

        else:
            # ----------------------------------------------------------------
            # Chunked map-reduce path: document exceeds single-pass budget.
            # ----------------------------------------------------------------
            chunk_word_budget = max(
                int((context_size - _MAP_PASS_OVERHEAD_TOKENS) / _TOKENS_PER_WORD), 500
            )
            chunks = _build_chunks(clean_text, chunk_word_budget)
            total_chunks = len(chunks)
            num_chunks = total_chunks
            current_app.logger.info(
                f"language_analysis.submit_to_llm: record #{record_id} — "
                f"{doc_words} words, {total_chunks} chunk(s) of ~{chunk_word_budget} words "
                f"(context_size={context_size})"
            )

            # -- Step 1: dedicated metadata extraction (regex → LLM) ------
            metadata_result: dict | None = data.get("_llm_metadata")
            if metadata_result is None:
                candidate_text = _extract_metadata_regions(clean_text)
                meta_parsed, _, meta_exc = _call_llm(
                    client,
                    model,
                    _build_metadata_system_prompt(),
                    _build_metadata_user_prompt(candidate_text),
                    _LLM_METADATA_SCHEMA,
                    options={"num_ctx": context_size},
                    label=f"submit_to_llm/metadata (record #{record_id})",
                )
                if meta_parsed is not None:
                    metadata_result = meta_parsed
                else:
                    # Non-fatal: map phase metadata_hits act as a fallback.
                    current_app.logger.warning(
                        f"language_analysis.submit_to_llm: metadata extraction failed "
                        f"for record #{record_id}: {meta_exc}; "
                        f"map-phase metadata_hits will be used instead"
                    )
                    metadata_result = {
                        "stated_word_count_found": False,
                        "stated_word_count": None,
                        "genai_statement_found": False,
                        "genai_statement": "",
                        "preface_found": False,
                        "preface_precis": "",
                    }
                data["_llm_metadata"] = metadata_result
                record = db.session.get(SubmissionRecord, record_id)
                if record is None:
                    raise Exception(f"submit_to_llm: SubmissionRecord #{record_id} not found on reload (metadata)")
                record.set_language_analysis_data(data)
                try:
                    db.session.commit()
                except SQLAlchemyError as exc:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError committing metadata result", exc_info=exc
                    )
                    raise self.retry()
                db.session.close()

            # -- Step 2: map phase (per-chunk evidence extraction) ---------
            chunk_state = data.get("_llm_chunks", {})

            # Reset persisted state if chunk topology changed between retries
            # (e.g. OLLAMA_CONTEXT_SIZE was adjusted by an administrator).
            if chunk_state.get("total_chunks") != total_chunks:
                chunk_state = {
                    "total_chunks": total_chunks,
                    "chunk_word_budget": chunk_word_budget,
                    "completed": [],
                    "results": {},
                }

            completed_chunks: set[int] = set(chunk_state.get("completed", []))
            chunk_results: dict = chunk_state.get("results", {})
            chunk_failed = False
            chunk_failure_reason = ""

            for idx, chunk_text in enumerate(chunks):
                if idx in completed_chunks:
                    continue  # already persisted on a previous Celery attempt

                chunk_parsed, accumulated, last_exc = _call_llm(
                    client,
                    model,
                    _build_chunk_system_prompt(idx, total_chunks),
                    _build_chunk_user_prompt(chunk_text, idx, total_chunks),
                    _LLM_CHUNK_SCHEMA,
                    options={"num_ctx": context_size},
                    label=f"submit_to_llm/chunk {idx + 1}/{total_chunks} (record #{record_id})",
                )

                if chunk_parsed is None:
                    chunk_failed = True
                    chunk_failure_reason = f"chunk {idx + 1}/{total_chunks} failed: {last_exc}"
                    break

                chunk_results[str(idx)] = chunk_parsed
                completed_chunks.add(idx)
                chunk_state = {
                    "total_chunks": total_chunks,
                    "chunk_word_budget": chunk_word_budget,
                    "completed": list(completed_chunks),
                    "results": chunk_results,
                }
                data["_llm_chunks"] = chunk_state
                record = db.session.get(SubmissionRecord, record_id)
                if record is None:
                    raise Exception(f"submit_to_llm: SubmissionRecord #{record_id} not found on reload (chunk {idx + 1})")
                record.set_language_analysis_data(data)
                try:
                    db.session.commit()
                except SQLAlchemyError as exc:
                    db.session.rollback()
                    current_app.logger.exception(
                        f"SQLAlchemyError committing chunk {idx + 1} result", exc_info=exc
                    )
                    raise self.retry()
                db.session.close()

            if chunk_failed:
                # Record failure and return; intermediate state is preserved in
                # data["_llm_chunks"] so a subsequent re-trigger can resume.
                elapsed = round(time.monotonic() - _t_llm, 1)
                data.setdefault("timings", {})["llm_s"] = elapsed
                # Reload record — the session was closed after the last successful chunk commit.
                record = db.session.get(SubmissionRecord, record_id)
                if record is None:
                    raise Exception(f"submit_to_llm: SubmissionRecord #{record_id} not found on reload (chunk failure)")
                record.llm_analysis_failed = True
                record.llm_failure_reason = chunk_failure_reason
                if accumulated:
                    data["llm_raw_response"] = accumulated
                errors.append({
                    "stage": "llm_submission",
                    "type": type(last_exc).__name__ if last_exc else "ChunkFailure",
                    "message": chunk_failure_reason,
                })
                current_app.logger.error(
                    f"language_analysis.submit_to_llm: {chunk_failure_reason} "
                    f"for record #{record_id}"
                )
                data["errors"] = errors
                record.set_language_analysis_data(data)
                try:
                    db.session.commit()
                except SQLAlchemyError as exc:
                    db.session.rollback()
                    current_app.logger.exception(
                        "SQLAlchemyError committing chunk failure", exc_info=exc
                    )
                    raise self.retry()
                return

            # -- Step 3: synthesis (reduce phase) -------------------------
            merged = _merge_chunk_evidence(chunk_results)

            # Override aggregated metadata with the dedicated extraction result,
            # which is more reliable (regex-located, purpose-built prompt).
            merged["metadata"] = {
                "stated_word_count_found": metadata_result.get("stated_word_count_found", False),
                "stated_word_count": metadata_result.get("stated_word_count"),
                "genai_statement_found": metadata_result.get("genai_statement_found", False),
                "genai_statement": metadata_result.get("genai_statement", ""),
                "preface_found": metadata_result.get("preface_found", False),
                "preface_precis": metadata_result.get("preface_precis", ""),
            }

            evidence_text = _build_synthesis_evidence_text(merged, total_chunks)
            synthesis_ctx = max(context_size, _SYNTHESIS_MIN_CTX)

            parsed_result, accumulated, last_exc = _call_llm(
                client,
                model,
                _build_system_prompt(False),
                _build_synthesis_user_prompt(evidence_text),
                _LLM_RESPONSE_SCHEMA,
                options={"num_ctx": synthesis_ctx},
                validate_fn=_validate_llm_response,
                label=f"submit_to_llm/synthesis (record #{record_id})",
            )

            # Overwrite synthesis metadata fields with dedicated extraction result
            # (the synthesis LLM copies them from the evidence text, but the
            # dedicated call is the authoritative source).
            if parsed_result is not None:
                for field in (
                    "stated_word_count_found",
                    "stated_word_count",
                    "genai_statement_found",
                    "genai_statement",
                    "preface_found",
                    "preface_precis",
                ):
                    if field in metadata_result:
                        parsed_result[field] = metadata_result[field]

        # ----------------------------------------------------------------
        # Common outcome handling (single-pass and chunked-synthesis paths).
        # ----------------------------------------------------------------
        data.setdefault("timings", {})["llm_s"] = round(time.monotonic() - _t_llm, 1)

        # Store LLM provenance in the JSON blob and on the model columns so
        # past runs can be compared if a larger model or wider context window
        # is deployed later.
        data["llm_meta"] = {
            "model": model,
            "context_size": context_size,
            "num_chunks": num_chunks,
        }
        # Reload the record with a fresh DB connection before writing results.
        # The session was closed before the LLM call to prevent connection staleness.
        record = db.session.get(SubmissionRecord, record_id)
        if record is None:
            raise Exception(f"submit_to_llm: SubmissionRecord #{record_id} not found on final reload")
        record.llm_model_name = model
        record.llm_context_size = context_size
        record.llm_num_chunks = num_chunks

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
            # Clean up intermediate chunking state.
            data.pop("_llm_chunks", None)
            data.pop("_llm_metadata", None)
        else:
            failure_reason = str(last_exc) if last_exc else "Unknown error"
            record.llm_analysis_failed = True
            record.llm_failure_reason = failure_reason
            data["llm_raw_response"] = accumulated
            errors.append(
                {
                    "stage": "llm_submission",
                    "type": type(last_exc).__name__ if last_exc else "Unknown",
                    "message": failure_reason,
                }
            )
            current_app.logger.error(
                f"language_analysis.submit_to_llm: LLM submission failed for "
                f"record #{record_id}: {failure_reason}"
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

    @celery.task(bind=True, default_retry_delay=30, soft_time_limit=7200, time_limit=7260)
    def submit_to_llm_feedback(self, record_id: int):
        """
        Stage 4 (llm_tasks queue): submit the extracted report text to an Ollama
        LLM for formative feedback generation (positive feedback and improvement
        suggestions).  Runs after submit_to_llm in the chain so both tasks share
        the same _extracted_text without redundant downloads.

        If the document exceeds the per-chunk feedback word budget, it is split
        into chunks via _build_chunks() and each chunk is submitted independently.
        Results from all successful chunks are merged using _deduplicate_feedback().
        At least one chunk must succeed for feedback to be stored; partial success
        (some chunks succeed, others fail) is accepted — the task is non-fatal.

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

        # Build submission text using the 3-tier strategy:
        #   Tier 1: core + appendices if they fit within the context window.
        #   Tier 2: core only (appendix stripped) if that fits.
        #   Tier 3: core chunked if it still exceeds the budget.
        # The reference list is never submitted (same rationale as submit_to_llm).
        _core, _, _appendices = _split_document(raw_text)
        clean_core = _strip_math_lines(_core)
        clean_full = (
            clean_core + "\n\n" + _strip_math_lines(_appendices)
            if _appendices
            else clean_core
        )

        context_size: int = current_app.config.get("OLLAMA_CONTEXT_SIZE", 4096)
        base_url: str = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model: str = current_app.config.get("OLLAMA_MODEL", "llama3.1:70b")

        import ollama

        client = ollama.Client(host=base_url)

        # Release the DB connection before the long-running LLM call (same rationale
        # as submit_to_llm).  The record will be reloaded before the final write.
        db.session.close()

        _t_feedback = time.monotonic()

        feedback_word_budget = max(
            int((context_size - _FEEDBACK_OVERHEAD_TOKENS) / _TOKENS_PER_WORD), 500
        )
        full_words = len(clean_full.split())
        core_words = len(clean_core.split())

        if full_words <= feedback_word_budget:
            # Tier 1: core + appendices fits within the context window.
            chunk_texts = [clean_full]
        elif core_words <= feedback_word_budget:
            # Tier 2: appendix stripped; core fits without chunking.
            chunk_texts = [clean_core]
            current_app.logger.info(
                f"language_analysis.submit_to_llm_feedback: record #{record_id} — "
                f"appendix excluded to fit context window ({full_words} → {core_words} words)"
            )
        else:
            # Tier 3: core still exceeds budget; chunk it.
            chunk_texts = _build_chunks(clean_core, feedback_word_budget)
            if not chunk_texts:
                chunk_texts = [clean_core]
            current_app.logger.info(
                f"language_analysis.submit_to_llm_feedback: record #{record_id} — "
                f"{core_words} core words split into {len(chunk_texts)} chunk(s) "
                f"(full_words={full_words})"
            )

        feedback_results: list[dict] = []
        last_exc: Exception | None = None

        for chunk_idx, chunk_text in enumerate(chunk_texts):
            chunk_parsed, _, chunk_exc = _call_llm(
                client,
                model,
                _build_feedback_system_prompt(False),
                _build_feedback_user_prompt(chunk_text),
                _LLM_FEEDBACK_RESPONSE_SCHEMA,
                options={"num_ctx": context_size},
                validate_fn=_validate_feedback_response,
                label=(
                    f"submit_to_llm_feedback/chunk {chunk_idx + 1}/{len(chunk_texts)} "
                    f"(record #{record_id})"
                ),
            )
            if chunk_parsed is not None:
                feedback_results.append(chunk_parsed)
            else:
                last_exc = chunk_exc
                current_app.logger.warning(
                    f"language_analysis.submit_to_llm_feedback: chunk {chunk_idx + 1}/"
                    f"{len(chunk_texts)} failed for record #{record_id}: {chunk_exc}"
                )

        data.setdefault("timings", {})["llm_feedback_s"] = round(
            time.monotonic() - _t_feedback, 1
        )
        errors: list = data.get("errors", [])

        # Reload the record with a fresh DB connection before writing results.
        record = db.session.get(SubmissionRecord, record_id)
        if record is None:
            raise Exception(f"submit_to_llm_feedback: SubmissionRecord #{record_id} not found on reload")

        if feedback_results:
            # Merge all successful chunk results.
            all_positive: list[str] = []
            all_improvements: list[str] = []
            for r in feedback_results:
                all_positive.extend(r.get("positive_feedback", []))
                all_improvements.extend(r.get("improvements", []))
            data["llm_feedback"] = {
                "positive_feedback": _deduplicate_feedback(all_positive, 3),
                "improvements": _deduplicate_feedback(all_improvements, 3),
            }
            # Explicitly mark success (False = ran and succeeded).  This completes the
            # three-way semantics: None = not yet run, False = succeeded, True = failed.
            record.llm_feedback_failed = False
            record.llm_feedback_failure_reason = None
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
                f"language_analysis.submit_to_llm_feedback: all chunks failed for "
                f"record #{record_id}: {failure_reason}"
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

    # ---------------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def recalculate_ai_concern(self, task_id: str, tenant_id: int, pclass_ids=None, years=None):
        """
        Re-evaluate the Mahalanobis-based AI concern flag for all completed
        SubmissionRecords belonging to *tenant_id*, optionally filtered to
        specific project class IDs and/or academic years.

        This task is launched after the tenant's AI calibration has been updated,
        so that existing submissions reflect the new centroid without needing a
        full re-run of the language analysis pipeline.

        For each eligible record the task:
          1. Loads the language_analysis JSON blob.
          2. Fetches the tenant's current calibration data.
          3. Re-evaluates _ai_concern_flag() for the stored (MATTR, MTLD, CV) values.
          4. Updates the flags sub-dict (ai_concern, mahalanobis_sigma, mahalanobis_pvalue).
          5. Re-runs compute_risk_factors() to keep the risk_factors blob in sync.
          6. Commits.
        """
        self.update_state(state="STARTED", meta={"msg": "Preparing AI concern recalculation"})
        progress_update(task_id, TaskRecord.RUNNING, 5, "Querying submissions…")

        # Fetch tenant and its calibration.
        try:
            tenant: Tenant = db.session.query(Tenant).filter_by(id=tenant_id).first()
        except SQLAlchemyError as exc:
            current_app.logger.exception("recalculate_ai_concern: DB error loading tenant", exc_info=exc)
            progress_update(task_id, TaskRecord.FAILURE, 100, "Database error loading tenant", autocommit=True)
            return

        if tenant is None:
            msg = f"recalculate_ai_concern: Tenant #{tenant_id} not found"
            current_app.logger.error(msg)
            progress_update(task_id, TaskRecord.FAILURE, 100, "Tenant not found", autocommit=True)
            return

        calibration = tenant.ai_calibration_data
        if calibration is None:
            msg = "recalculate_ai_concern: tenant has no calibration data — aborting"
            current_app.logger.warning(msg)
            progress_update(task_id, TaskRecord.FAILURE, 100, "No calibration data available", autocommit=True)
            return

        # Build query for target records.
        try:
            q = (
                db.session.query(SubmissionRecord)
                .join(SubmissionPeriodRecord, SubmissionRecord.period_id == SubmissionPeriodRecord.id)
                .join(ProjectClassConfig, SubmissionPeriodRecord.config_id == ProjectClassConfig.id)
                .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
                .filter(ProjectClass.tenant_id == tenant_id)
                .filter(SubmissionRecord.language_analysis_complete == True)  # noqa: E712
            )
            if pclass_ids:
                q = q.filter(ProjectClass.id.in_(pclass_ids))
            if years:
                q = q.filter(ProjectClassConfig.year.in_(years))

            records = q.all()
        except SQLAlchemyError as exc:
            current_app.logger.exception("recalculate_ai_concern: DB error querying records", exc_info=exc)
            progress_update(task_id, TaskRecord.FAILURE, 100, "Database error querying records", autocommit=True)
            return

        total = len(records)
        progress_update(task_id, TaskRecord.RUNNING, 10, f"Recalculating AI concern for {total} submission(s)…")

        updated = 0
        for i, record in enumerate(records, start=1):
            try:
                la = record.language_analysis_data
                metrics = la.get("metrics", {})
                flags = la.get("flags", {})

                ai_result = _ai_concern_flag(
                    metrics.get("mattr"),
                    metrics.get("mtld"),
                    metrics.get("sentence_cv"),
                    calibration,
                )

                flags["ai_concern"] = ai_result["concern"]
                flags["mahalanobis_sigma"] = ai_result["sigma"]
                flags["mahalanobis_pvalue"] = ai_result["p_value"]
                la["flags"] = flags
                record.set_language_analysis_data(la)

                # Re-compute risk factors to keep them in sync with the new concern level.
                try:
                    config = record.period.config if record.period else None
                    record.compute_risk_factors(config)
                except Exception as exc:
                    current_app.logger.warning(
                        f"recalculate_ai_concern: could not recompute risk factors for record #{record.id}: {exc}"
                    )

                updated += 1

                # Commit in batches of 50 to bound memory and reduce lock contention.
                if updated % 50 == 0:
                    try:
                        db.session.commit()
                    except SQLAlchemyError as exc:
                        db.session.rollback()
                        current_app.logger.exception(
                            "recalculate_ai_concern: DB error during batch commit", exc_info=exc
                        )

                pct = 10 + int(85 * i / total)
                progress_update(task_id, TaskRecord.RUNNING, pct, f"Processed {i}/{total}…")

            except Exception as exc:
                current_app.logger.warning(
                    f"recalculate_ai_concern: error processing record #{record.id}: {exc}"
                )

        # Final commit for any remaining records.
        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception("recalculate_ai_concern: final commit error", exc_info=exc)
            progress_update(task_id, TaskRecord.FAILURE, 100, "Database error on final commit", autocommit=True)
            return

        progress_update(
            task_id,
            TaskRecord.SUCCESS,
            100,
            f"AI concern recalculated for {updated} submission(s).",
            autocommit=True,
        )

    return recalculate_ai_concern
