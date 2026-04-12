"""
language_analysis_core.py — Standalone mirror of the MPS language analysis pipeline.

Provides clean (non-diagnostic) implementations of every metric computed by
the production Celery pipeline (app/tasks/language_analysis.py) and the
classification thresholds from app/shared/llm_thresholds.py, with no
Flask/Celery/SQLAlchemy dependencies.

Used by:
    test_language_analysis.py  — single-PDF diagnostic tool
    arxiv_control_analysis.py  — batch arXiv control-sample runner

Keeping all shared algorithm code here means both tools stay automatically in
sync with each other.  When the production pipeline changes, only this file
(and the production file) need updating.

spaCy dependency
----------------
Burstiness and sentence CV require spaCy + the en_core_web_sm model.
These are available in the arxiv_analysis_venv/ Python 3.12 environment.
Both functions return None gracefully if spaCy is not installed.
"""

from __future__ import annotations

import re

import numpy as np

# ---------------------------------------------------------------------------
# Classification thresholds (mirrors app/shared/llm_thresholds.py)
# ---------------------------------------------------------------------------

# MATTR — Moving Average Type-Token Ratio (window = 100 tokens)
# Human academic normal range: 0.70–0.85
MATTR_STRONG_THRESHOLD = 0.60
MATTR_NOTE_LOW_THRESHOLD = 0.70
MATTR_NOTE_HIGH_THRESHOLD = 0.85

# MTLD — Measure of Textual Lexical Diversity (threshold = 0.72)
# Human academic normal range: 70–120
MTLD_NOTE_THRESHOLD = 70
MTLD_STRONG_THRESHOLD = 50
MTLD_HIGH_NOTE_THRESHOLD = 120

# Goh-Barabási burstiness B = (σ − μ) / (σ + μ)
# Human normal range: 0.2–0.6
BURSTINESS_STRONG_LOW = 0.0
BURSTINESS_NOTE_LOW = 0.2
BURSTINESS_NOTE_HIGH = 0.6
BURSTINESS_STRONG_HIGH = 0.8

# Sentence-length coefficient of variation CV = σ / μ
# Human academic normal range: 0.55–0.85
SENT_CV_STRONG_LOW = 0.35
SENT_CV_NOTE_LOW = 0.55
SENT_CV_NOTE_HIGH = 0.85
SENT_CV_STRONG_HIGH = 1.10


def classify_mattr(value: float | None) -> str:
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
    if value is None:
        return "unknown"
    if value > MTLD_HIGH_NOTE_THRESHOLD:
        return "note"
    if value < MTLD_STRONG_THRESHOLD:
        return "strong"
    if value < MTLD_NOTE_THRESHOLD:
        return "note"
    return "ok"


def classify_burstiness(value: float | None) -> str:
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


# ---------------------------------------------------------------------------
# Pattern constants (mirrors app/tasks/language_analysis.py)
# ---------------------------------------------------------------------------

HEDGING_PATTERNS = [
    r"it is important to note that",
    r"it is worth noting that",
    r"it is crucial to note that",
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

EM_DASH_PATTERN = r"(\u2014|---)"

# ---------------------------------------------------------------------------
# Word groups for burstiness analysis (mirrors app/tasks/language_analysis.py)
# ---------------------------------------------------------------------------

BURSTINESS_WORD_GROUPS = [
    {"group": "suggest",    "lemmas": {"suggest"}},
    {"group": "indicate",   "lemmas": {"indicate"}},
    {"group": "demonstrate","lemmas": {"demonstrate"}},
    {"group": "show",       "lemmas": {"show"}},
    {"group": "appear",     "lemmas": {"appear"}},
    {"group": "estimate",   "lemmas": {"estimate"}},
    {"group": "assume",     "lemmas": {"assume"}},
    {"group": "imply",      "lemmas": {"imply"}},
    {"group": "significant","lemmas": {"significant", "insignificant"}},
    {"group": "important",  "lemmas": {"important", "relevant"}},
    {"group": "consistent", "lemmas": {"consistent", "inconsistent"}},
    {"group": "unexpected", "lemmas": {"unexpected", "surprising"}},
    {"group": "clear",      "lemmas": {"clear", "unclear"}},
    {"group": "compare",    "lemmas": {"compare"}},
    {"group": "contrast",   "lemmas": {"contrast", "differ"}},
    {"group": "agree",      "lemmas": {"agree", "disagree", "confirm"}},
    {"group": "support",    "lemmas": {"support", "contradict"}},
]

BURSTINESS_MIN_OCCURRENCES = 8

# ---------------------------------------------------------------------------
# Regex patterns (mirrors app/tasks/language_analysis.py)
# ---------------------------------------------------------------------------

_BIBLIO_HEADING = re.compile(
    r"^\s*(references|bibliography|works\s+cited)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CAPTION_LINE = re.compile(
    r"^\s*(?:figure|fig\.|table)\s+(?:[A-Z]\.)?\d+(?:\.\d+)?",
    re.IGNORECASE | re.MULTILINE,
)
_FIG_REF = re.compile(
    r"\b(?:figure|fig\.)\s+((?:[A-Z]\.)?\d+(?:\.\d+)?)([a-z])?",
    re.IGNORECASE,
)
_TAB_REF = re.compile(
    r"\btable\s+((?:[A-Z]\.)?\d+(?:\.\d+)?)([a-z])?",
    re.IGNORECASE,
)
_NUMBERED_ENTRY = re.compile(r"^\s*(\[\d{1,3}\]|\d{1,3}\.)\s+[A-Z]", re.MULTILINE)
_NUMBERED_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_ENGLISH_WORD = re.compile(r"[a-zA-Z]{5,}")
_APPENDIX_HEADING = re.compile(
    r"(?im)^\s*appendix(?:[ \t]+(?-i:[A-Z])(?:[:\t \-\.].*)?)?$"
)
_REF_YEAR = re.compile(r"\(\d{4}[a-z]?\)")
_ARXIV_ID_PAT = re.compile(r"\barXiv:\d{4}\.\d{4,5}\b", re.IGNORECASE)
_DOI = re.compile(r"\bdoi:\s*10\.\d{4,}", re.IGNORECASE)

_MIN_APPENDIX_FRACTION = 0.25

# ---------------------------------------------------------------------------
# spaCy model — lazy singleton
# ---------------------------------------------------------------------------

_nlp = None


def _get_nlp():
    """Load the spaCy en_core_web_sm model on first call; return the cached instance."""
    global _nlp
    if _nlp is None:
        import spacy  # noqa: PLC0415 — intentional late import
        _nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
        _nlp.add_pipe("sentencizer")
    return _nlp


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------


def extract_pdf_text(path: str) -> tuple[str, int]:
    """Extract body text and page count from a PDF using PyMuPDF (fitz).

    Header/footer strips (top 8 % and bottom 8 % of each page) and non-text
    blocks are discarded, matching the production pipeline behaviour.
    """
    import fitz  # noqa: PLC0415

    doc = fitz.open(path)
    pages = []
    for page in doc:
        page_height = page.rect.height
        blocks = page.get_text("blocks")
        body_blocks = [
            b[4]
            for b in blocks
            if b[1] > page_height * 0.08
            and b[3] < page_height * 0.92
            and b[6] == 0
        ]
        pages.append("\n".join(body_blocks))
    page_count = len(doc)
    doc.close()
    return "\n\n".join(pages), page_count


# ---------------------------------------------------------------------------
# Document splitting
# ---------------------------------------------------------------------------


def _split_at_last_biblio(text: str) -> tuple[str, str]:
    """Split at the last bibliography heading."""
    matches = list(_BIBLIO_HEADING.finditer(text))
    if matches:
        m = matches[-1]
        return text[: m.start()], text[m.start():]
    return text, ""


def split_document(raw_text: str) -> tuple[str, str, str]:
    """Split raw extracted text into (_core, _references, _appendices).

    Mirrors _split_document() in app/tasks/language_analysis.py.

    Returns three strings; any region may be empty if not detected.

    Layout detection (in priority order):

      Type B — core → references → appendices:
        Appendix heading found inside the post-bibliography text.

      Type A — core → appendices → references:
        Appendix heading found inside the pre-bibliography text, past the
        first 25 % of the document (to exclude TOC entries).

      Type C — no appendix detected:
        core = everything before the last bibliography heading;
        references = everything from that heading onwards.
    """
    pre_core, pre_biblio = _split_at_last_biblio(raw_text)

    # Type B: appendix lives after the reference list
    app_match = _APPENDIX_HEADING.search(pre_biblio)
    if app_match:
        return pre_core, pre_biblio[: app_match.start()], pre_biblio[app_match.start():]

    # Type A: appendix lives before the reference list (heuristic position guard)
    min_pos = int(len(pre_core) * _MIN_APPENDIX_FRACTION)
    for match in _APPENDIX_HEADING.finditer(pre_core):
        if match.start() > min_pos:
            return pre_core[: match.start()], pre_biblio, pre_core[match.start():]

    # Type C: no appendix
    return pre_core, pre_biblio, ""


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------


def strip_math_lines(text: str) -> str:
    """Remove lines that contain no run of 5+ ASCII letters (equation fragments).

    Mirrors _strip_math_lines() in app/tasks/language_analysis.py.
    """
    kept = []
    for line in text.splitlines():
        if not line.strip() or _ENGLISH_WORD.search(line):
            kept.append(line)
    return "\n".join(kept)


# ---------------------------------------------------------------------------
# Word count
# ---------------------------------------------------------------------------


def word_count(main_text: str) -> int:
    """Count words in *main_text* after removing figure/table caption lines."""
    clean = _CAPTION_LINE.sub("", main_text)
    return len(clean.split())


# ---------------------------------------------------------------------------
# Bibliography / reference counting
# ---------------------------------------------------------------------------


def count_bibliography(biblio_text: str) -> tuple[int, list[str]]:
    """Count references in *biblio_text*.

    Returns (count, keys) where *keys* is a list of numeric strings for
    numbered reference styles (used for uncited-reference detection), or []
    for author-year styles.

    Mirrors _count_bibliography() in app/tasks/language_analysis.py.
    """
    # Safety net: truncate at any appendix heading that survived into the
    # reference section (the split should already have handled this).
    app_match = _APPENDIX_HEADING.search(biblio_text)
    if app_match:
        biblio_text = biblio_text[: app_match.start()]

    # Numbered bibliography (e.g. [1], [12], 1., 42.)
    numbered = _NUMBERED_ENTRY.findall(biblio_text)
    if numbered:
        keys = [k.strip().strip(".").strip("[]") for k in numbered]
        try:
            if min(int(k) for k in keys) <= 5:
                return len(keys), keys
        except ValueError:
            return len(keys), keys  # non-integer keys — trust the match

    # Author-year heuristic: count lines that carry a year, arXiv ID, or DOI
    lines = [ln.strip() for ln in biblio_text.splitlines() if ln.strip()]
    body_lines = [
        ln for ln in lines[1:]
        if not ln.lower().startswith(("ref", "biblio", "works"))
    ]
    candidates = [
        ln for ln in body_lines
        if _REF_YEAR.search(ln) or _ARXIV_ID_PAT.search(ln) or _DOI.search(ln)
    ]
    if len(candidates) >= 3:
        return len(candidates), []
    return len(body_lines), []


def check_uncited(main_text: str, keys: list[str]) -> list[str]:
    """Return numbered reference keys that appear in *keys* but not cited in *main_text*."""
    if not keys:
        return []
    cited: set[str] = set()
    for match in _NUMBERED_CITATION.finditer(main_text):
        for num in match.group(1).split(","):
            cited.add(num.strip())
    return [k for k in keys if k not in cited]


# ---------------------------------------------------------------------------
# Figure / table cross-reference checking
# ---------------------------------------------------------------------------


def check_figure_table_refs(text: str) -> tuple[list[str], list[str]]:
    """Return (uncaptioned_figures, uncaptioned_tables).

    A label is considered uncaptioned when it appears only once in *text*
    (i.e. is not both defined as a caption and referenced in the body).

    Mirrors _check_figure_table_refs() in app/tasks/language_analysis.py.
    """
    fig_labels: dict[str, str] = {}
    tab_labels: dict[str, str] = {}

    for m in _FIG_REF.finditer(text):
        n = m.group(1)
        if n not in fig_labels:
            fig_labels[n] = f"Figure {n}"

    for m in _TAB_REF.finditer(text):
        n = m.group(1)
        if n not in tab_labels:
            tab_labels[n] = f"Table {n}"

    def _cited(pattern: str) -> bool:
        return len(re.findall(pattern, text, re.IGNORECASE)) > 1

    uncaptioned_figs = [
        label for n, label in fig_labels.items()
        if not _cited(rf"\b(?:figure|fig\.)\s+{re.escape(n)}[a-z]?\b")
    ]
    uncaptioned_tabs = [
        label for n, label in tab_labels.items()
        if not _cited(rf"\btable\s+{re.escape(n)}[a-z]?\b")
    ]
    return uncaptioned_figs, uncaptioned_tabs


# ---------------------------------------------------------------------------
# Lexical metrics: MATTR + MTLD
# ---------------------------------------------------------------------------


def compute_mattr_mtld(text: str) -> tuple[float | None, float | None]:
    """Compute MATTR (window=100) and MTLD (threshold=0.72) on *text*.

    Returns (None, None) when fewer than 100 words are present or on error.
    Mirrors _compute_mattr_mtld() in app/tasks/language_analysis.py.
    """
    try:
        from lexicalrichness import LexicalRichness  # noqa: PLC0415
        lex = LexicalRichness(text)
        if lex.words < 100:
            return None, None
        return float(lex.mattr(window_size=100)), float(lex.mtld(threshold=0.72))
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# Burstiness (Goh-Barabási B) — requires spaCy
# ---------------------------------------------------------------------------


def compute_burstiness(raw_text: str) -> float | None:
    """Compute aggregate Goh-Barabási burstiness over BURSTINESS_WORD_GROUPS.

    B = (σ − μ) / (σ + μ)  where σ and μ are the std and mean of
    inter-arrival token distances for each word group.  The aggregate is the
    mean over groups with ≥ BURSTINESS_MIN_OCCURRENCES occurrences.

    Returns None if spaCy is unavailable or no group has enough occurrences.
    Mirrors _compute_burstiness() in app/tasks/language_analysis.py.
    """
    try:
        nlp = _get_nlp()
    except Exception:
        return None

    doc = nlp(raw_text)
    token_lemmas = [
        (i, tok.lemma_.lower()) for i, tok in enumerate(doc) if tok.is_alpha
    ]

    eligible: list[float] = []
    for group_def in BURSTINESS_WORD_GROUPS:
        target: set[str] = group_def["lemmas"]
        positions = [i for i, lemma in token_lemmas if lemma in target]
        if len(positions) < BURSTINESS_MIN_OCCURRENCES:
            continue
        arrivals = np.diff(positions).astype(float)
        mu = float(np.mean(arrivals))
        sigma = float(np.std(arrivals, ddof=1)) if len(arrivals) > 1 else 0.0
        denom = sigma + mu
        eligible.append(float((sigma - mu) / denom) if denom != 0 else 0.0)

    return float(np.mean(eligible)) if eligible else None


# ---------------------------------------------------------------------------
# Sentence-length CV — requires spaCy
# ---------------------------------------------------------------------------


def compute_sentence_cv(clean_content_text: str) -> float | None:
    """Compute coefficient of variation of sentence lengths (CV = σ/μ).

    Sentence length = count of non-punctuation, non-space tokens per sentence.
    Returns None if spaCy is unavailable or fewer than 5 sentences are found.
    Mirrors _compute_sentence_cv() in app/tasks/language_analysis.py.
    """
    try:
        nlp = _get_nlp()
    except Exception:
        return None

    doc = nlp(clean_content_text)
    lengths = [
        sum(1 for tok in sent if not tok.is_punct and not tok.is_space)
        for sent in doc.sents
    ]
    lengths = [ln for ln in lengths if ln > 1]
    if len(lengths) < 5:
        return None
    arr = np.array(lengths, dtype=float)
    mu = arr.mean()
    if mu == 0.0:
        return None
    return float(arr.std(ddof=1) / mu)


# ---------------------------------------------------------------------------
# Pattern counts (hedging / filler / em-dash)
# ---------------------------------------------------------------------------


def count_patterns(text: str) -> dict:
    """Count occurrences of hedging, filler, and em-dash patterns in *text*.

    Returns a dict with keys: hedging_total, hedging_detail, filler_total,
    filler_detail, em_dash_count.
    Mirrors _count_patterns() in app/tasks/language_analysis.py.
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

    return {
        "hedging_total": hedging_total,
        "hedging_detail": hedging_detail,
        "filler_total": filler_total,
        "filler_detail": filler_detail,
        "em_dash_count": len(re.findall(EM_DASH_PATTERN, text)),
    }


# ---------------------------------------------------------------------------
# Full single-paper analysis pipeline
# ---------------------------------------------------------------------------


def analyse_paper(pdf_path) -> dict:
    """Run the complete language analysis pipeline on *pdf_path*.

    Returns a dict with keys:
        page_count, word_count,
        mattr, mtld, burstiness, sentence_cv,
        mattr_flag, mtld_flag, burstiness_flag, sentence_cv_flag,
        error   (None on success, otherwise an error string)

    This is the minimal pipeline used by the batch arXiv runner.  The
    diagnostic tool (test_language_analysis.py) calls the individual
    functions directly for more verbose output.
    """
    from pathlib import Path  # noqa: PLC0415

    result: dict = {"error": None}
    try:
        raw_text, page_count = extract_pdf_text(str(pdf_path))
        result["page_count"] = page_count

        _core, _references, _appendices = split_document(raw_text)

        clean_core = strip_math_lines(_core)
        content_text = (_core + "\n\n" + _appendices) if _appendices else _core
        clean_content = strip_math_lines(content_text)

        result["word_count"] = word_count(clean_core)

        mattr, mtld = compute_mattr_mtld(clean_content)
        result["mattr"] = mattr
        result["mtld"] = mtld
        result["mattr_flag"] = classify_mattr(mattr)
        result["mtld_flag"] = classify_mtld(mtld)

        burstiness = compute_burstiness(raw_text)
        result["burstiness"] = burstiness
        result["burstiness_flag"] = classify_burstiness(burstiness)

        sentence_cv = compute_sentence_cv(clean_content)
        result["sentence_cv"] = sentence_cv
        result["sentence_cv_flag"] = classify_sentence_cv(sentence_cv)

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result
