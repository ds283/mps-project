#!/usr/bin/env python3
"""
Standalone diagnostic script for the language analysis pipeline.

Replicates text extraction, cleaning, page/word counting, lexical metrics,
and reference/figure/table detection from app/tasks/language_analysis.py
WITHOUT submitting anything to an LLM.

Usage:
    python test_language_analysis.py <path-to-pdf>

Outputs verbose diagnostics for each stage, including the raw bibliography
text and matched/unmatched entries to help diagnose reference-counting failures.

NOTE: spaCy-dependent metrics (burstiness, sentence CV) are not computed here
because spaCy cannot be installed in the build environment. These metrics are
still computed in the production Celery pipeline.
"""

import re
import sys
import textwrap
from pathlib import Path

# ---------------------------------------------------------------------------
# Classification thresholds (from app/shared/llm_thresholds.py)
# ---------------------------------------------------------------------------

MATTR_STRONG_THRESHOLD = 0.60
MATTR_NOTE_LOW_THRESHOLD = 0.70
MATTR_NOTE_HIGH_THRESHOLD = 0.85

MTLD_NOTE_THRESHOLD = 70
MTLD_STRONG_THRESHOLD = 50
MTLD_HIGH_NOTE_THRESHOLD = 120


def classify_mattr(value):
    if value is None:
        return "unknown"
    if value < MATTR_STRONG_THRESHOLD:
        return "strong"
    if value < MATTR_NOTE_LOW_THRESHOLD:
        return "note"
    if value > MATTR_NOTE_HIGH_THRESHOLD:
        return "note"
    return "ok"


def classify_mtld(value):
    if value is None:
        return "unknown"
    if value > MTLD_HIGH_NOTE_THRESHOLD:
        return "note"
    if value < MTLD_STRONG_THRESHOLD:
        return "strong"
    if value < MTLD_NOTE_THRESHOLD:
        return "note"
    return "ok"


# ---------------------------------------------------------------------------
# Pattern constants
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
# Regex patterns (from language_analysis.py)
# ---------------------------------------------------------------------------

_BIBLIO_HEADING = re.compile(
    r"^\s*(references|bibliography|works\s+cited)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

# Handles simple (Figure 1), chapter-relative (Figure 3.1), and appendix (Figure A.1).
_CAPTION_LINE = re.compile(
    r"^\s*(?:figure|fig\.|table)\s+(?:[A-Z]\.)?\d+(?:\.\d+)?",
    re.IGNORECASE | re.MULTILINE,
)

# Figure/table label patterns.
# group(1) = canonical label key ("1", "3.1", "A.1")
# group(2) = optional subfigure suffix letter ("a", "b") — NOT part of the key.
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

# Appendix heading: matches "Appendix", "Appendix A", "Appendix B: Title", etc.
# (?-i:[A-Z]) enforces uppercase-only letter even when the overall pattern is IGNORECASE.
# [ \t] (not \s) prevents the optional group from spanning a newline.
_APPENDIX_HEADING = re.compile(
    r"(?im)^\s*appendix(?:[ \t]+(?-i:[A-Z])(?:[:\t \-\.].*)?)?$"
)

# Author-year reference entry signals.
_REF_YEAR = re.compile(r"\(\d{4}[a-z]?\)")
_ARXIV_ID = re.compile(r"\barXiv:\d{4}\.\d{4,5}\b", re.IGNORECASE)
_DOI = re.compile(r"\bdoi:\s*10\.\d{4,}", re.IGNORECASE)

# Appendix heading must appear after this fraction of _pre_core to be treated
# as a genuine section heading rather than an early reference or TOC entry.
_MIN_APPENDIX_FRACTION = 0.25

# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def extract_pdf_text(path: str) -> tuple[str, int]:
    import fitz

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
# Text cleaning / splitting
# ---------------------------------------------------------------------------


def _split_text(text: str) -> tuple[str, str]:
    """Split at the *last* bibliography heading (internal helper)."""
    matches = list(_BIBLIO_HEADING.finditer(text))
    if matches:
        match = matches[-1]
        return text[: match.start()], text[match.start():]
    return text, ""


def split_document(raw_text: str) -> tuple[str, str, str]:
    """
    Split raw extracted text into three named regions:

        (_core, _references, _appendices)

    Any region may be the empty string if not detected.

    Algorithm
    ---------
    Step 1.  Locate the last bibliography heading → pre_core, pre_biblio.

    Step 2a. Search pre_biblio for an appendix heading (type B report:
             core → references → appendices).  If found:
               _core        = pre_core
               _references  = pre_biblio up to appendix heading
               _appendices  = pre_biblio from appendix heading onwards

    Step 2b. Otherwise search pre_core for an appendix heading (type A report:
             core → appendices → references).  Apply a heuristic: the heading
             must appear after _MIN_APPENDIX_FRACTION of pre_core to exclude
             TOC entries and early cross-references.  Use the first qualifying
             match (start of appendix section).  If found:
               _core        = pre_core up to appendix heading
               _references  = pre_biblio
               _appendices  = pre_core from appendix heading onwards

    Step 2c. No appendix heading found anywhere:
               _core        = pre_core
               _references  = pre_biblio
               _appendices  = ""
    """
    pre_core, pre_biblio = _split_text(raw_text)

    print(f"\n  Bibliography split: pre_core={len(pre_core)} chars, pre_biblio={len(pre_biblio)} chars")

    all_biblio_matches = list(_BIBLIO_HEADING.finditer(raw_text))
    print(f"  _BIBLIO_HEADING matched {len(all_biblio_matches)} time(s):")
    for i, m in enumerate(all_biblio_matches):
        ctx_start = max(0, m.start() - 60)
        ctx_end = min(len(raw_text), m.end() + 60)
        ctx = raw_text[ctx_start:ctx_end].replace("\n", "↵")
        print(f"    [{i}] pos={m.start()}  match={m.group()!r}  context: ...{ctx}...")

    if not pre_biblio:
        print("  *** WARNING: No bibliography heading found. Reference count will use heuristic. ***")

    # Step 2a — type B: appendix inside pre_biblio
    app_match = _APPENDIX_HEADING.search(pre_biblio)
    if app_match:
        _core = pre_core
        _references = pre_biblio[: app_match.start()]
        _appendices = pre_biblio[app_match.start():]
        print(f"\n  Type B report detected (appendix inside bibliography/post-reference section).")
        print(f"  Appendix heading at pre_biblio pos {app_match.start()}: {app_match.group()!r}")
        print(f"  _core={len(_core)} chars, _references={len(_references)} chars, _appendices={len(_appendices)} chars")
        return _core, _references, _appendices

    # Step 2b — type A: appendix inside pre_core (with heuristic)
    min_pos = int(len(pre_core) * _MIN_APPENDIX_FRACTION)
    print(f"\n  No appendix heading in pre_biblio. Searching pre_core (heuristic min_pos={min_pos} chars)...")
    all_core_app_matches = list(_APPENDIX_HEADING.finditer(pre_core))
    print(f"  _APPENDIX_HEADING matched {len(all_core_app_matches)} time(s) in pre_core:")
    for i, m in enumerate(all_core_app_matches):
        ctx_start = max(0, m.start() - 60)
        ctx_end = min(len(pre_core), m.end() + 60)
        ctx = pre_core[ctx_start:ctx_end].replace("\n", "↵")
        print(f"    [{i}] pos={m.start()} (>min_pos={m.start() > min_pos})  match={m.group()!r}  context: ...{ctx}...")

    for match in all_core_app_matches:
        if match.start() > min_pos:
            _core = pre_core[: match.start()]
            _references = pre_biblio
            _appendices = pre_core[match.start():]
            print(f"\n  Type A report detected (appendix before reference list).")
            print(f"  Appendix heading at pre_core pos {match.start()}: {match.group()!r}")
            print(f"  _core={len(_core)} chars, _references={len(_references)} chars, _appendices={len(_appendices)} chars")
            return _core, _references, _appendices

    # Step 2c — no appendices
    print(f"\n  No appendix heading detected (type C / no appendix).")
    print(f"  _core={len(pre_core)} chars, _references={len(pre_biblio)} chars, _appendices=0 chars")
    return pre_core, pre_biblio, ""


def strip_math_lines(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if not line.strip() or _ENGLISH_WORD.search(line):
            kept.append(line)
    return "\n".join(kept)


def word_count(main_text: str) -> int:
    clean = _CAPTION_LINE.sub("", main_text)
    return len(clean.split())


# ---------------------------------------------------------------------------
# Reference counting — verbose diagnostic version
# ---------------------------------------------------------------------------


def count_bibliography_verbose(biblio_text: str) -> tuple[int, list[str]]:
    """
    Like _count_bibliography() but prints detailed diagnostics so you can
    see exactly what was matched or why the heuristic fallback was used.
    """
    # --- Appendix truncation (safety net: _references should already be appendix-free) ---
    app_match = _APPENDIX_HEADING.search(biblio_text)
    if app_match:
        print(f"\n  Appendix heading found at pos {app_match.start()} — truncating bibliography there.")
        print(f"  Appendix heading matched: {biblio_text[app_match.start():app_match.end()]!r}")
        biblio_text = biblio_text[: app_match.start()]
        print(f"  Bibliography text after truncation: {len(biblio_text)} chars")
    else:
        print("\n  No appendix heading found in _references — no truncation needed.")

    print("\n  --- Bibliography text (first 3000 chars) ---")
    preview = biblio_text[:3000].replace("\n", "↵\n")
    print(textwrap.indent(preview, "  "))
    if len(biblio_text) > 3000:
        print(f"  ... [{len(biblio_text) - 3000} more chars]")

    # --- Numbered entries ----------------------------------------------------
    numbered = _NUMBERED_ENTRY.findall(biblio_text)
    print(f"\n  Numbered-entry pattern (_NUMBERED_ENTRY) matched {len(numbered)} times.")
    if numbered:
        print("  Matched keys (first 20):", numbered[:20])
        keys = [k.strip().strip(".").strip("[]") for k in numbered]
        try:
            min_key = min(int(k) for k in keys)
            if min_key <= 5:
                print(f"  Minimum key={min_key} ≤ 5 — treating as genuine numbered bibliography.")
                return len(keys), keys
            else:
                print(f"  Minimum key={min_key} > 5 — likely line-wrap false positive; falling through to author-year heuristic.")
        except ValueError:
            return len(keys), keys  # non-integer keys — trust the match

    # --- Author-year heuristic -----------------------------------------------
    print("\n  No genuine numbered entries found — falling back to author-year line heuristic.")
    lines = [ln.strip() for ln in biblio_text.splitlines() if ln.strip()]
    body_lines = [
        ln
        for ln in lines[1:]
        if ln and not ln.lower().startswith(("ref", "biblio", "works"))
    ]
    print(f"  Body lines (non-blank, after skipping heading): {len(body_lines)}")

    entry_candidates = [
        ln for ln in body_lines
        if _REF_YEAR.search(ln) or _ARXIV_ID.search(ln) or _DOI.search(ln)
    ]
    print(f"\n  Entry candidates (year / arXiv / DOI signal): {len(entry_candidates)}")
    print("  First 20 candidate lines:")
    for ln in entry_candidates[:20]:
        print(f"    {ln[:120]}")

    if len(entry_candidates) >= 3:
        print(f"\n  Using candidate count: {len(entry_candidates)}")
        return len(entry_candidates), []

    print(f"\n  Fewer than 3 candidates — falling back to body line count: {len(body_lines)}")
    print("  First 20 body lines:")
    for ln in body_lines[:20]:
        print(f"    {ln[:120]}")
    return len(body_lines), []


def check_uncited(main_text: str, keys: list[str]) -> list[str]:
    if not keys:
        return []
    cited_numbers: set[str] = set()
    for match in _NUMBERED_CITATION.finditer(main_text):
        for num in match.group(1).split(","):
            cited_numbers.add(num.strip())
    return [k for k in keys if k not in cited_numbers]


def check_figure_table_refs(text: str) -> tuple[list[str], list[str]]:
    """
    Normalise figure/table labels before deduplication:
    - Chapter-relative: "Figure 3.1", "Figure 4.5" → keys "3.1", "4.5"
    - Appendix:         "Figure A.1"               → key  "A.1"
    - Subfigure panels: "Figure 3.1a", "Figure 3.1b" → key "3.1" (suffix stripped)
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


# ---------------------------------------------------------------------------
# Lexical metrics
# ---------------------------------------------------------------------------


def compute_mattr_mtld(main_text: str) -> tuple:
    try:
        from lexicalrichness import LexicalRichness
        lex = LexicalRichness(main_text)
        if lex.words < 100:
            print(f"  Too few words ({lex.words}) for MATTR/MTLD.")
            return None, None
        mattr = float(lex.mattr(window_size=100))
        mtld = float(lex.mtld(threshold=0.72))
        return mattr, mtld
    except Exception as exc:
        print(f"  MATTR/MTLD failed: {exc}")
        return None, None


def count_patterns(text: str) -> dict:
    hedging_total = 0
    hedging_detail: dict = {}
    for pattern in HEDGING_PATTERNS:
        count = len(re.findall(pattern, text, re.IGNORECASE))
        hedging_detail[pattern] = count
        hedging_total += count

    filler_total = 0
    filler_detail: dict = {}
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _hr(title=""):
    width = 72
    if title:
        pad = width - len(title) - 4
        print(f"\n{'=' * 2} {title} {'=' * max(pad, 2)}")
    else:
        print("=" * width)


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_language_analysis.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    # ---- Stage 1: Text extraction -------------------------------------------
    _hr("STAGE 1: PDF TEXT EXTRACTION")
    print(f"File: {pdf_path}")
    raw_text, page_count = extract_pdf_text(pdf_path)
    print(f"Page count : {page_count}")
    print(f"Raw chars  : {len(raw_text)}")
    print(f"Raw words  : {len(raw_text.split())}")

    # ---- Stage 2: 3-way document split --------------------------------------
    _hr("STAGE 2: 3-WAY DOCUMENT SPLIT (core / references / appendices)")
    _core, _references, _appendices = split_document(raw_text)
    print(f"\nSplit summary:")
    print(f"  _core        : {len(_core)} chars / {len(_core.split())} words")
    print(f"  _references  : {len(_references)} chars")
    print(f"  _appendices  : {len(_appendices)} chars / {len(_appendices.split())} words")

    # ---- Stage 3: Math-line stripping (core text only) ----------------------
    _hr("STAGE 3: MATH-LINE STRIPPING (core text only)")
    clean_core_text = strip_math_lines(_core)
    raw_lines = len(_core.splitlines())
    clean_lines = len(clean_core_text.splitlines())
    removed = raw_lines - clean_lines
    print(f"Core lines before : {raw_lines}")
    print(f"Core lines after  : {clean_lines}")
    print(f"Lines removed (math/noise): {removed}  ({100*removed/max(raw_lines,1):.1f}%)")
    print(f"Clean core text words: {len(clean_core_text.split())}")

    # ---- Stage 4: Word count ------------------------------------------------
    _hr("STAGE 4: WORD COUNT")
    core_wc = word_count(clean_core_text)
    print(f"Core word count (after caption removal): {core_wc}")

    if _appendices:
        clean_appendices_text = strip_math_lines(_appendices)
        appendix_wc = word_count(clean_appendices_text)
        print(f"Appendix word count                    : {appendix_wc}")
        print(f"Total (core + appendix)                : {core_wc + appendix_wc}")
    else:
        print("Appendix word count                    : 0 (no appendix detected)")

    # ---- Stage 5: Bibliography / reference counting -------------------------
    _hr("STAGE 5: BIBLIOGRAPHY / REFERENCE COUNTING")
    ref_count, ref_keys = count_bibliography_verbose(_references)
    print(f"\nReference count: {ref_count}")
    if ref_keys:
        print(f"Keys (first 30): {ref_keys[:30]}")
        uncited = check_uncited(_core, ref_keys)
        if uncited:
            print(f"Uncited references ({len(uncited)}): {uncited[:30]}")
        else:
            print("All references appear to be cited in main text.")
    else:
        print("(Author-year / heuristic mode — uncited check skipped)")

    # ---- Stage 6: Figure and table detection --------------------------------
    _hr("STAGE 6: FIGURE / TABLE DETECTION")

    # Search core + appendices (not reference list) for figure/table labels.
    content_text = _core + "\n\n" + _appendices if _appendices else _core
    clean_content_text = strip_math_lines(content_text)

    fig_labels_all = {m.group(1) for m in _FIG_REF.finditer(content_text)}
    tab_labels_all = {m.group(1) for m in _TAB_REF.finditer(content_text)}
    print(f"Unique figure labels found in core+appendices: {len(fig_labels_all)}")
    print(f"  {sorted(fig_labels_all)[:30]}")
    print(f"Unique table labels found in core+appendices : {len(tab_labels_all)}")
    print(f"  {sorted(tab_labels_all)[:30]}")

    uncaptioned_figs, uncaptioned_tabs = check_figure_table_refs(content_text)
    if uncaptioned_figs:
        print(f"\nFigures appearing only once (possibly uncaptioned or uncited in text): {uncaptioned_figs}")
    else:
        print("\nAll figure labels appear more than once (caption + body reference).")
    if uncaptioned_tabs:
        print(f"Tables appearing only once (possibly uncaptioned or uncited in text): {uncaptioned_tabs}")
    else:
        print("All table labels appear more than once (caption + body reference).")

    # ---- Stage 7: Lexical metrics -------------------------------------------
    _hr("STAGE 7: LEXICAL METRICS (MATTR / MTLD)")
    print("Computing MATTR and MTLD on core + appendices text (this may take a moment)...")
    mattr, mtld = compute_mattr_mtld(clean_content_text)
    print(f"MATTR : {mattr:.4f}  [{classify_mattr(mattr)}]" if mattr is not None else "MATTR : None  [unknown]")
    print(f"MTLD  : {mtld:.2f}  [{classify_mtld(mtld)}]" if mtld is not None else "MTLD  : None  [unknown]")

    # ---- Stage 8: Pattern counts -------------------------------------------
    _hr("STAGE 8: HEDGING / FILLER PATTERN COUNTS")
    patterns = count_patterns(raw_text)
    print(f"Hedging phrases total : {patterns['hedging_total']}")
    for pat, cnt in patterns["hedging_detail"].items():
        if cnt > 0:
            print(f"  {cnt:3d}  {pat}")
    print(f"Filler phrases total  : {patterns['filler_total']}")
    for pat, cnt in patterns["filler_detail"].items():
        if cnt > 0:
            print(f"  {cnt:3d}  {pat}")
    print(f"Em-dashes / triple-hyphens: {patterns['em_dash_count']}")

    # ---- Stage 9: AI concern summary ----------------------------------------
    _hr("STAGE 9: AI CONCERN SUMMARY")
    mattr_flag = classify_mattr(mattr)
    mtld_flag  = classify_mtld(mtld)

    print(f"  MATTR flag : {mattr_flag}")
    print(f"  MTLD flag  : {mtld_flag}")
    print()
    print("  NOTE: Burstiness (Goh-Barabási B) and sentence-length CV require spaCy,")
    print("  which is not available in the build environment. These metrics are computed")
    print("  in the production Celery pipeline but are omitted from this diagnostic script.")
    print()

    flags = [mattr_flag, mtld_flag]
    outside = sum(1 for f in flags if f in ("note", "strong"))
    strong_count = sum(1 for f in flags if f == "strong")
    if strong_count >= 2 or outside >= 2:
        partial_concern = "high (from available metrics)"
    elif strong_count >= 1 or outside >= 1:
        partial_concern = "medium (from available metrics)"
    else:
        partial_concern = "low (from available metrics)"

    print(f"  Partial AI concern (MATTR + MTLD only): {partial_concern.upper()}")
    print("  Full 4-metric assessment requires burstiness and sentence CV (production only).")

    _hr("DONE")


if __name__ == "__main__":
    main()
