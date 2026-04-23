#!/usr/bin/env python3
"""
Standalone diagnostic script for the language analysis pipeline.

Replicates text extraction, cleaning, page/word counting, lexical metrics,
and reference/figure/table detection from app/tasks/language_analysis.py
WITHOUT submitting anything to an LLM.

Usage:
    python test_language_analysis.py <path-to-pdf>

    Run inside arxiv_analysis_venv for the full set of metrics including
    spaCy-based burstiness and sentence-length CV:

        arxiv_analysis_venv/bin/python test_language_analysis.py <path-to-pdf>

Outputs verbose diagnostics for each stage, including the raw bibliography
text and matched/unmatched entries to help diagnose reference-counting failures.

All algorithm implementations live in language_analysis_core.py.  This script
adds diagnostic-only output (verbose bibliography matching, document-split
tracing, etc.) on top of the core functions.
"""

import re
import sys
import textwrap
from pathlib import Path

# All shared algorithm code lives in language_analysis_core.
from language_analysis_core import (
    # Classification
    classify_mattr,
    classify_mtld,
    classify_burstiness,
    classify_sentence_cv,
    # Patterns (needed for verbose displays)
    HEDGING_PATTERNS,
    FILLER_PATTERNS,
    EM_DASH_PATTERN,
    # Regex (needed for verbose bibliography diagnostics)
    _BIBLIO_HEADING,
    _APPENDIX_HEADING,
    _NUMBERED_ENTRY,
    _REF_YEAR,
    _ARXIV_ID_PAT,
    _DOI,
    _FIG_REF,
    _TAB_REF,
    _MIN_APPENDIX_FRACTION,
    # Pipeline functions
    extract_pdf_text,
    split_document,
    strip_math_lines,
    word_count,
    check_uncited,
    check_figure_table_refs,
    compute_mattr_mtld,
    compute_burstiness,
    compute_sentence_cv,
    count_patterns,
)

# ---------------------------------------------------------------------------
# Verbose document-split diagnostics
# ---------------------------------------------------------------------------


def print_split_diagnostics(raw_text: str, _core: str, _references: str, _appendices: str) -> None:
    """Print detailed tracing of how split_document() divided the document."""
    pre_core_len = len(_core)
    pre_biblio_len = len(_references) + len(_appendices)
    print(f"\n  Bibliography split: pre_core={pre_core_len} chars, pre_biblio={pre_biblio_len} chars")

    all_biblio = list(_BIBLIO_HEADING.finditer(raw_text))
    print(f"  _BIBLIO_HEADING matched {len(all_biblio)} time(s):")
    for i, m in enumerate(all_biblio):
        ctx_start = max(0, m.start() - 60)
        ctx_end = min(len(raw_text), m.end() + 60)
        ctx = raw_text[ctx_start:ctx_end].replace("\n", "↵")
        print(f"    [{i}] pos={m.start()}  match={m.group()!r}  context: ...{ctx}...")

    if not _references and not _appendices:
        print("  *** WARNING: No bibliography heading found. Reference count will use heuristic. ***")

    # Report which layout type was detected
    if _appendices:
        # Determine if Type A or Type B by checking where appendix heading falls
        # relative to the reference boundary
        if _references:
            print(f"\n  Type detected: B (core → references → appendices)")
        else:
            print(f"\n  Type detected: A (core → appendices → references)")
        print(f"  _core={len(_core)} chars, _references={len(_references)} chars, _appendices={len(_appendices)} chars")

        all_app = list(_APPENDIX_HEADING.finditer(raw_text))
        print(f"  _APPENDIX_HEADING matched {len(all_app)} time(s) in full document:")
        for i, m in enumerate(all_app):
            ctx_start = max(0, m.start() - 60)
            ctx_end = min(len(raw_text), m.end() + 60)
            ctx = raw_text[ctx_start:ctx_end].replace("\n", "↵")
            print(f"    [{i}] pos={m.start()}  match={m.group()!r}  context: ...{ctx}...")
    else:
        min_pos = int(len(_core) * _MIN_APPENDIX_FRACTION)
        print(f"\n  No appendix heading detected (type C / no appendix).  "
              f"Heuristic min_pos was {min_pos} chars.")
        print(f"  _core={len(_core)} chars, _references={len(_references)} chars, _appendices=0 chars")


# ---------------------------------------------------------------------------
# Verbose bibliography counting
# ---------------------------------------------------------------------------


def count_bibliography_verbose(biblio_text: str) -> tuple[int, list[str]]:
    """Like count_bibliography() but prints detailed diagnostics."""
    # Appendix truncation
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

    # Numbered entries
    numbered = _NUMBERED_ENTRY.findall(biblio_text)
    print(f"\n  Numbered-entry pattern matched {len(numbered)} times.")
    if numbered:
        print("  Matched keys (first 20):", numbered[:20])
        keys = [k.strip().strip(".").strip("[]") for k in numbered]
        try:
            min_key = min(int(k) for k in keys)
            if min_key <= 5:
                print(f"  Minimum key={min_key} ≤ 5 — treating as genuine numbered bibliography.")
                return len(keys), keys
            else:
                print(f"  Minimum key={min_key} > 5 — likely line-wrap false positive; "
                      f"falling through to author-year heuristic.")
        except ValueError:
            return len(keys), keys  # non-integer keys — trust the match

    # Author-year heuristic
    print("\n  No genuine numbered entries found — falling back to author-year line heuristic.")
    lines = [ln.strip() for ln in biblio_text.splitlines() if ln.strip()]
    body_lines = [
        ln for ln in lines[1:]
        if not ln.lower().startswith(("ref", "biblio", "works"))
    ]
    print(f"  Body lines (non-blank, after skipping heading): {len(body_lines)}")

    candidates = [
        ln for ln in body_lines
        if _REF_YEAR.search(ln) or _ARXIV_ID_PAT.search(ln) or _DOI.search(ln)
    ]
    print(f"\n  Entry candidates (year / arXiv / DOI signal): {len(candidates)}")
    print("  First 20 candidate lines:")
    for ln in candidates[:20]:
        print(f"    {ln[:120]}")

    if len(candidates) >= 3:
        print(f"\n  Using candidate count: {len(candidates)}")
        return len(candidates), []

    print(f"\n  Fewer than 3 candidates — falling back to body line count: {len(body_lines)}")
    print("  First 20 body lines:")
    for ln in body_lines[:20]:
        print(f"    {ln[:120]}")
    return len(body_lines), []


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _hr(title=""):
    width = 72
    if title:
        pad = width - len(title) - 4
        print(f"\n{'=' * 2} {title} {'=' * max(pad, 2)}")
    else:
        print("=" * width)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_language_analysis.py <path-to-pdf>")
        print("       arxiv_analysis_venv/bin/python test_language_analysis.py <path-to-pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    # Detect whether spaCy is available (it needs the Python 3.12 venv)
    try:
        from language_analysis_core import _get_nlp
        _get_nlp()
        spacy_available = True
    except Exception:
        spacy_available = False

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
    print_split_diagnostics(raw_text, _core, _references, _appendices)
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

    # Build content text (core + appendices) used for most metrics
    content_text = (_core + "\n\n" + _appendices) if _appendices else _core
    clean_content_text = strip_math_lines(content_text)

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

    # ---- Stage 8: Burstiness ------------------------------------------------
    _hr("STAGE 8: BURSTINESS (Goh-Barabási B)")
    if spacy_available:
        print("Computing burstiness on raw text (spaCy lemmatisation)...")
        burstiness = compute_burstiness(raw_text)
        print(f"Burstiness B : {burstiness:.4f}  [{classify_burstiness(burstiness)}]"
              if burstiness is not None else "Burstiness B : None  [unknown — no eligible word groups]")
    else:
        burstiness = None
        print("spaCy not available in this environment.")
        print("Run inside arxiv_analysis_venv/bin/python to compute burstiness.")

    # ---- Stage 9: Sentence-length CV ----------------------------------------
    _hr("STAGE 9: SENTENCE-LENGTH CV")
    if spacy_available:
        print("Computing sentence-length CV on core + appendices text (spaCy sentence segmentation)...")
        sentence_cv = compute_sentence_cv(clean_content_text)
        print(f"Sentence CV  : {sentence_cv:.4f}  [{classify_sentence_cv(sentence_cv)}]"
              if sentence_cv is not None else "Sentence CV  : None  [unknown — fewer than 5 sentences]")
    else:
        sentence_cv = None
        print("spaCy not available in this environment.")
        print("Run inside arxiv_analysis_venv/bin/python to compute sentence CV.")

    # ---- Stage 10: Pattern counts -------------------------------------------
    _hr("STAGE 10: HEDGING / FILLER PATTERN COUNTS")
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

    # ---- Stage 11: AI concern summary ----------------------------------------
    _hr("STAGE 11: AI CONCERN SUMMARY")
    mattr_flag     = classify_mattr(mattr)
    mtld_flag      = classify_mtld(mtld)
    burst_flag     = classify_burstiness(burstiness)
    sent_cv_flag   = classify_sentence_cv(sentence_cv)

    print(f"  MATTR flag       : {mattr_flag}")
    print(f"  MTLD flag        : {mtld_flag}")
    print(f"  Burstiness flag  : {burst_flag}")
    print(f"  Sentence CV flag : {sent_cv_flag}")
    if not spacy_available:
        print()
        print("  NOTE: Burstiness and sentence CV were not computed (spaCy unavailable).")
        print("  Run inside arxiv_analysis_venv/bin/python for the full 4-metric assessment.")
    print()

    flags = [mattr_flag, mtld_flag, burst_flag, sent_cv_flag]
    outside = sum(1 for f in flags if f in ("note", "strong"))
    strong_count = sum(1 for f in flags if f == "strong")
    unknown_count = sum(1 for f in flags if f == "unknown")

    if strong_count >= 2 or outside >= 3:
        concern = "HIGH"
    elif strong_count >= 1 or outside >= 2:
        concern = "MEDIUM"
    else:
        concern = "LOW"

    qualifier = " (partial — spaCy metrics unavailable)" if unknown_count >= 2 and not spacy_available else ""
    print(f"  AI concern: {concern}{qualifier}")

    _hr("DONE")


if __name__ == "__main__":
    main()
