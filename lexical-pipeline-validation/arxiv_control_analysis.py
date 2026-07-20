#!/usr/bin/env python3
"""
arxiv_control_analysis.py — Download arXiv papers and compute lexical metrics
(MATTR, MTLD, Goh-Barabási burstiness, sentence-length CV) to build a
control-sample distribution from known-human, pre-LLM text.

Role in the analysis chain
--------------------------
This script is the data-collection stage for the arXiv control samples.  It
sits between language_analysis_core.py (which it calls for metric computation)
and lexical_diversity_pipeline.py (which consumes its Excel output for
comparative analysis against student reports).

    language_analysis_core.py  ←  algorithm implementation
            ↓
    arxiv_control_analysis.py  (this script)
            ↓  writes
    arxiv_control_results.xlsx  (one sheet per paper set)
            ↓  consumed by
    lexical_diversity_pipeline.py  ←  also reads AI dashboard export
                                       (student metrics + Calibrations sheet)

This script produces ONLY raw lexical metrics; it does NOT compute Mahalanobis
distances. Distance computation and all plotting are done by
lexical_diversity_pipeline.py. To compare arXiv σ values with production
values, run lexical_diversity_pipeline.py with --calibration-file pointing to
an AI dashboard export that contains a Calibrations sheet.

Cache
-----
Repeated runs re-process the same PDFs from disk by default, which is slow.
Use --cache (default: analysis_cache.sqlite) to persist computed metrics
between runs using analysis_cache.py.  The cache is keyed by SHA-256 of the
raw extracted PDF text — stable for a given file and PyMuPDF version.  If
PyMuPDF is upgraded, all cache entries become cold misses; the pymupdf_version
column in the cache database lets you detect this.

Cache invalidation is manual: delete the .sqlite file or pass --no-cache.
See analysis_cache.py for details.

Paper sets analysed
-------------------
  1. All papers by each arXiv author (scraped from their arXiv author page).
     Default authors: Seery (djs61), Byrnes (byrnes_c), Burrage (burrage_c).
  2. ~200 papers from the astro-ph.CO category submitted before a fixed cutoff
     date (default: 2026-04-20) to ensure a stable, reproducible reference set.
  3. Local PDF folders (default: ai_cache/ → sheet "Claude-ai").

Usage
-----
  arxiv_analysis_venv/bin/python arxiv_control_analysis.py [options]

Options
-------
  --output PATH              Output .xlsx path  [default: arxiv_control_results.xlsx]
  --pdf-cache DIR            Directory for downloaded PDFs  [default: arxiv_pdf_cache/]
  --author SHEET URL         Worksheet name + author page URL (repeatable)
  --category CAT             arXiv subject category  [default: astro-ph.CO]
  --category-max N           Max papers to fetch from category  [default: 200]
  --category-before DATE     Cutoff date YYYY-MM-DD  [default: 2026-04-20]
  --pdf-folder SHEET DIR     Worksheet name + local folder of PDFs (repeatable)
  --no-author                Skip all author sets
  --no-category              Skip the category set
  --no-pdf-folder            Skip all local PDF folder sets
  --cache PATH               SQLite cache path  [default: analysis_cache.sqlite]
  --no-cache                 Bypass the cache entirely for this run

Requirements (run inside arxiv_analysis_venv)
---------------------------------------------
  spacy + en_core_web_sm, feedparser, pymupdf, lexicalrichness,
  numpy, pandas, openpyxl, requests

All language analysis algorithm code lives in language_analysis_core.py.
"""

from __future__ import annotations

import argparse
import html as html_module
import re
import sys
import time
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import feedparser
import pandas as pd
import requests

# All algorithm code comes from the shared core module.
from language_analysis_core import (
    analyse_paper,
    analyse_paper_from_text,
    extract_pdf_text,
    get_pymupdf_version,
    _get_nlp,
)

if TYPE_CHECKING:
    from analysis_cache import AnalysisCache

# ---------------------------------------------------------------------------
# arXiv helpers
# ---------------------------------------------------------------------------

ARXIV_API_BASE = "https://export.arxiv.org/api/query"
ARXIV_PDF_BASE = "https://arxiv.org/pdf"
_API_DELAY = 3.0  # seconds between API requests (arXiv policy)
_PDF_DELAY = 3.0  # seconds between PDF downloads

# Simple regex helpers for HTML scraping — avoids a BeautifulSoup dependency.
_HTML_TAG = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")

# Patterns for the arXiv author page (https://arxiv.org/a/<id>.html)
_PAGE_ENTRY_ID = re.compile(r'href="/abs/([0-9]+\.[0-9]+)"[^>]*title="Abstract"')
_PAGE_TITLE = re.compile(
    r'class="list-title mathjax">\s*<span[^>]*>Title:</span>\s*(.*?)\s*</div>',
    re.DOTALL,
)
_PAGE_AUTHORS = re.compile(
    r'class="list-authors">(.*?)</div>',
    re.DOTALL,
)
_AUTHOR_LINK = re.compile(r"<a[^>]*>([^<]+)</a>")


def _strip_html(s: str) -> str:
    return html_module.unescape(_WHITESPACE.sub(" ", _HTML_TAG.sub("", s)).strip())


def _arxiv_id_approx_date(arxiv_id: str) -> str:
    """Derive an approximate submission date from a modern arXiv ID (YYMM.NNNNN)."""
    m = re.match(r"^(\d{2})(\d{2})\.\d+$", arxiv_id)
    if not m:
        return ""
    yy, mm = int(m.group(1)), int(m.group(2))
    year = 2000 + yy if yy < 90 else 1900 + yy
    return f"{year}-{mm:02d}"


def fetch_author_page(page_url: str) -> list[dict]:
    """Scrape an arXiv author page (e.g. https://arxiv.org/a/seery_d_1.html).

    Returns a list of dicts with keys: arxiv_id, title, authors, published.
    All papers on the page are returned; arXiv loads the full list on a single
    page so no pagination is needed.
    """
    print(f"  Fetching author page: {page_url} …", flush=True)
    resp = requests.get(page_url, timeout=30)
    resp.raise_for_status()
    html = resp.text

    ids = _PAGE_ENTRY_ID.findall(html)
    titles = [_strip_html(t) for t in _PAGE_TITLE.findall(html)]
    author_blocks = _PAGE_AUTHORS.findall(html)

    papers: list[dict] = []
    for i, arxiv_id in enumerate(ids):
        title = titles[i] if i < len(titles) else ""
        if i < len(author_blocks):
            raw_authors = _AUTHOR_LINK.findall(author_blocks[i])
            authors = ", ".join(a.strip() for a in raw_authors)
        else:
            authors = ""
        papers.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": authors,
                "published": _arxiv_id_approx_date(arxiv_id),
            }
        )

    print(f"  Found {len(papers)} papers on author page.")
    return papers


def _arxiv_id_from_entry(entry) -> str:
    """Extract bare arXiv ID (e.g. '2301.12345') from a feedparser entry."""
    raw = entry.id.split("/abs/")[-1]
    return raw.split("v")[0]  # strip version suffix


def fetch_arxiv_papers(search_query: str, max_results: int) -> list[dict]:
    """Fetch paper metadata from the arXiv Atom API.

    Paginates in batches of 100.  Returns a list of dicts with keys:
      arxiv_id, title, authors, published
    """
    batch = 100
    papers: list[dict] = []
    start = 0

    while len(papers) < max_results:
        want = min(batch, max_results - len(papers))
        params = {
            "search_query": search_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": start,
            "max_results": want,
        }
        print(f"  arXiv API: query={search_query!r}  start={start}  max={want} …", flush=True)
        resp = requests.get(ARXIV_API_BASE, params=params, timeout=30)
        resp.raise_for_status()

        feed = feedparser.parse(resp.text)
        entries = feed.entries
        if not entries:
            break

        for entry in entries:
            arxiv_id = _arxiv_id_from_entry(entry)
            authors = ", ".join(a.get("name", "") for a in getattr(entry, "authors", []))
            papers.append(
                {
                    "arxiv_id": arxiv_id,
                    "title": entry.get("title", "").replace("\n", " ").strip(),
                    "authors": authors,
                    "published": entry.get("published", "")[:10],
                }
            )

        start += len(entries)
        if len(entries) < want:
            break  # no more results

        if len(papers) < max_results:
            time.sleep(_API_DELAY)

    return papers[:max_results]


def download_pdf(arxiv_id: str, cache_dir: Path) -> Path | None:
    """Download the PDF for *arxiv_id* to *cache_dir*, if not already cached.

    Returns the local path, or None if the download fails.
    """
    dest = cache_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    if dest.exists() and dest.stat().st_size > 1024:
        return dest  # already cached

    url = f"{ARXIV_PDF_BASE}/{arxiv_id}"
    try:
        resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                fh.write(chunk)
        return dest
    except Exception as exc:
        print(f"    WARNING: download failed for {arxiv_id}: {exc}", file=sys.stderr)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return None


# ---------------------------------------------------------------------------
# Process a set of papers
# ---------------------------------------------------------------------------


def _run_analysis_with_cache(
    pdf_path: Path,
    arxiv_id: Optional[str],
    cache: Optional["AnalysisCache"],
    llama_server_url: Optional[str] = None,
) -> dict:
    """Run language analysis on *pdf_path*, consulting *cache* when available.

    Returns the same metrics dict as analyse_paper_from_text().  On a cache
    hit, prints "(cached)" and skips reprocessing.  Falls back to direct
    analysis if text extraction fails or the cache raises an unexpected error.

    When *llama_server_url* is provided, NLL metrics are computed and stored
    in the llm_metrics cache table alongside the lexical metrics.
    """
    if cache is not None:
        try:
            raw_text, page_count = extract_pdf_text(str(pdf_path))
            text_hash = sha256(raw_text.encode()).hexdigest()
            cached = cache.get_metrics(text_hash)
            if cached is not None:
                # Cache hit for lexical metrics — but NLL may not have been
                # computed yet (e.g. previous run had no llama-server URL).
                if llama_server_url is not None and cached.get("mean_nll") is None:
                    nll_cached = cache.get_nll(text_hash)
                    if nll_cached is None or nll_cached.get("mean_nll") is None:
                        # Compute NLL now and store it.
                        from language_analysis_core import compute_nll, strip_math_lines, split_document  # noqa: PLC0415

                        _core, _, _appendices = split_document(raw_text)
                        content_text = (_core + "\n\n" + _appendices) if _appendices else _core
                        clean_content = strip_math_lines(content_text)
                        mean_nll, nll_cv = compute_nll(clean_content, llama_server_url)
                        nll_data = {"mean_nll": mean_nll, "nll_cv": nll_cv}
                        cache.store_nll(text_hash, nll_data=nll_data)
                        cached["mean_nll"] = mean_nll
                        cached["nll_cv"] = nll_cv
                    else:
                        cached["mean_nll"] = nll_cached.get("mean_nll")
                        cached["nll_cv"] = nll_cached.get("nll_cv")
                print("(cached)", end=" ", flush=True)
                return cached
            metrics = analyse_paper_from_text(raw_text, page_count=page_count, llama_server_url=llama_server_url)
            if not metrics.get("error"):
                cache.store_metrics(
                    text_hash,
                    metrics,
                    source_path=str(pdf_path),
                    arxiv_id=arxiv_id,
                    pymupdf_version=get_pymupdf_version(),
                )
                if llama_server_url is not None:
                    nll_data = {"mean_nll": metrics.get("mean_nll"), "nll_cv": metrics.get("nll_cv")}
                    cache.store_nll(text_hash, nll_data=nll_data)
            return metrics
        except Exception as exc:
            print(f"(cache error: {exc}) ", end="", file=sys.stderr)
            # Fall through to direct analysis below
    return analyse_paper(pdf_path, llama_server_url=llama_server_url)


def process_paper_set(
    label: str,
    papers: list[dict],
    cache_dir: Path,
    first_download: bool,
    cache: Optional["AnalysisCache"] = None,
    llama_server_url: Optional[str] = None,
) -> list[dict]:
    """Download PDFs and run analysis for each paper in *papers*.

    Returns a list of result dicts (one per paper, metadata merged in).
    Pass *cache* to skip reprocessing PDFs whose text hash is already stored.
    Pass *llama_server_url* to compute and store NLL metrics.
    """
    rows = []
    total = len(papers)

    for idx, meta in enumerate(papers, 1):
        arxiv_id = meta["arxiv_id"]
        print(f'  [{idx}/{total}] {arxiv_id}  "{meta["title"][:60]}"')

        # Rate-limit PDF downloads; skip delay for already-cached files
        pdf_path = cache_dir / f"{arxiv_id.replace('/', '_')}.pdf"
        already_cached = pdf_path.exists() and pdf_path.stat().st_size > 1024

        if not already_cached and (idx > 1 or not first_download):
            time.sleep(_PDF_DELAY)

        pdf_path = download_pdf(arxiv_id, cache_dir)

        row = dict(meta)
        if pdf_path is None:
            row.update(
                {
                    "page_count": None,
                    "word_count": None,
                    "mattr": None,
                    "mtld": None,
                    "burstiness": None,
                    "sentence_cv": None,
                    "mean_nll": None,
                    "nll_cv": None,
                    "mattr_flag": "unknown",
                    "mtld_flag": "unknown",
                    "burstiness_flag": "unknown",
                    "sentence_cv_flag": "unknown",
                    "error": "PDF download failed",
                }
            )
        else:
            print(f"    Analysing …", end=" ", flush=True)
            metrics = _run_analysis_with_cache(pdf_path, arxiv_id, cache, llama_server_url=llama_server_url)
            row.update(metrics)
            if metrics.get("error"):
                print(f"ERROR: {metrics['error']}")
            else:
                all_numeric = all(metrics.get(k) is not None for k in ("mattr", "mtld", "burstiness", "sentence_cv"))
                if all_numeric:
                    nll_str = f"  NLL={metrics['mean_nll']:.3f}" if metrics.get("mean_nll") is not None else ""
                    print(
                        f"MATTR={metrics['mattr']:.3f}  MTLD={metrics['mtld']:.1f}  "
                        f"B={metrics['burstiness']:.3f}  CV={metrics['sentence_cv']:.3f}"
                        f"{nll_str}"
                    )
                else:
                    print("done (some metrics None)")

        rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Process a local folder of PDFs
# ---------------------------------------------------------------------------


def process_local_folder(
    label: str,
    folder_path: Path,
    cache: Optional["AnalysisCache"] = None,
    llama_server_url: Optional[str] = None,
) -> list[dict]:
    """Run analysis on every PDF in folder_path.

    Returns rows in the same format as process_paper_set, using the PDF
    filename stem as the arxiv_id/title placeholder (no download needed).
    Pass *cache* to skip reprocessing PDFs whose text hash is already stored.
    Pass *llama_server_url* to compute and store NLL metrics.
    """
    pdfs = sorted(folder_path.glob("*.pdf"))
    rows = []
    total = len(pdfs)
    if total == 0:
        print(f"  WARNING: no PDF files found in {folder_path}", file=sys.stderr)
        return rows

    for idx, pdf_path in enumerate(pdfs, 1):
        stem = pdf_path.stem
        print(f"  [{idx}/{total}] {stem[:60]}")
        meta = {
            "arxiv_id": stem,
            "title": stem,
            "authors": "",
            "published": "",
        }
        print(f"    Analysing …", end=" ", flush=True)
        metrics = _run_analysis_with_cache(pdf_path, arxiv_id=None, cache=cache, llama_server_url=llama_server_url)
        row = meta | metrics
        if metrics.get("error"):
            print(f"ERROR: {metrics['error']}")
        else:
            all_numeric = all(metrics.get(k) is not None for k in ("mattr", "mtld", "burstiness", "sentence_cv"))
            if all_numeric:
                nll_str = f"  NLL={metrics['mean_nll']:.3f}" if metrics.get("mean_nll") is not None else ""
                print(
                    f"MATTR={metrics['mattr']:.3f}  MTLD={metrics['mtld']:.1f}  "
                    f"B={metrics['burstiness']:.3f}  CV={metrics['sentence_cv']:.3f}"
                    f"{nll_str}"
                )
            else:
                print("done (some metrics None)")
        rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Excel output
# ---------------------------------------------------------------------------

COLUMNS = [
    "arxiv_id",
    "title",
    "authors",
    "published",
    "page_count",
    "word_count",
    "mattr",
    "mtld",
    "burstiness",
    "sentence_cv",
    "mean_nll",
    "nll_cv",
    "mattr_flag",
    "mtld_flag",
    "burstiness_flag",
    "sentence_cv_flag",
    "error",
]


def write_excel(output_path: Path, sheets: dict[str, list[dict]]) -> None:
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        for sheet_name, rows in sheets.items():
            df = pd.DataFrame(rows, columns=COLUMNS)
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    print(f"\nResults written to: {output_path}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_category_query(category: str, before_date: str | None) -> str:
    """Build an arXiv API search query for *category*, optionally capped at *before_date* (YYYY-MM-DD)."""
    query = f"cat:{category}"
    if before_date:
        date_compact = before_date.replace("-", "")
        query += f" AND submittedDate:[19000101 TO {date_compact}]"
    return query


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

_DEFAULT_AUTHORS = [
    ["djs61", "https://arxiv.org/a/seery_d_1.html"],
    ["byrnes_c", "https://arxiv.org/a/0000-0003-2583-6536.html"],
    ["burrage_c", "https://arxiv.org/a/burrage_c_1.html"],
]

_DEFAULT_PDF_FOLDERS = [
    ["Claude-ai", "ai_cache"],
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run language analysis on arXiv papers and export to Excel.")
    parser.add_argument(
        "--output",
        default="arxiv_control_results.xlsx",
        help="Output .xlsx path (default: arxiv_control_results.xlsx)",
    )
    parser.add_argument(
        "--pdf-cache",
        default="arxiv_pdf_cache",
        dest="pdf_cache",
        help="Directory for downloaded PDFs (default: arxiv_pdf_cache/)",
    )
    parser.add_argument(
        "--author",
        nargs=2,
        metavar=("SHEET_NAME", "PAGE_URL"),
        action="append",
        dest="authors",
        help="Worksheet name and arXiv author page URL (repeatable). Default: Seery, Byrnes, Burrage.",
    )
    parser.add_argument(
        "--category",
        default="astro-ph.CO",
        help="arXiv subject category (default: astro-ph.CO)",
    )
    parser.add_argument(
        "--category-max",
        type=int,
        default=200,
        dest="category_max",
        help="Max papers to fetch from category (default: 200)",
    )
    parser.add_argument(
        "--category-before",
        default="2026-04-20",
        dest="category_before",
        metavar="YYYY-MM-DD",
        help="Only include category papers submitted before this date (default: 2026-04-20).",
    )
    parser.add_argument(
        "--pdf-folder",
        nargs=2,
        metavar=("SHEET_NAME", "FOLDER_PATH"),
        action="append",
        dest="pdf_folders",
        help="Worksheet name and path to a local folder of PDFs (repeatable). Default: Claude-ai → ai_cache/",
    )
    parser.add_argument("--no-author", action="store_true", help="Skip all author paper sets")
    parser.add_argument("--no-category", action="store_true", help="Skip category paper set")
    parser.add_argument("--no-pdf-folder", action="store_true", help="Skip all local PDF folder sets")
    parser.add_argument(
        "--cache",
        default="analysis_cache.sqlite",
        metavar="PATH",
        help="SQLite cache path for computed metrics (default: analysis_cache.sqlite)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        dest="no_cache",
        help="Bypass the cache entirely; always recompute metrics from PDFs",
    )
    parser.add_argument(
        "--llama-server-url",
        default=None,
        dest="llama_server_url",
        metavar="URL",
        help="Base URL of a running llama-server instance for NLL computation (e.g. http://localhost:8080).  If omitted, NLL metrics are skipped.",
    )
    args = parser.parse_args()

    if not args.authors:
        args.authors = _DEFAULT_AUTHORS

    if not args.pdf_folders:
        args.pdf_folders = _DEFAULT_PDF_FOLDERS

    cache_dir = Path(args.pdf_cache)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Pre-load spaCy model once so the first paper doesn't pay a silent delay
    print("Loading spaCy model …", flush=True)
    _get_nlp()
    print("spaCy model ready.\n")

    llama_server_url: Optional[str] = args.llama_server_url
    if llama_server_url:
        print(f"NLL computation: llama-server at {llama_server_url}\n")
    else:
        print("NLL computation: disabled (pass --llama-server-url to enable)\n")

    # Open (or bypass) the analysis cache
    cache: Optional["AnalysisCache"] = None
    if not args.no_cache:
        try:
            from analysis_cache import AnalysisCache  # noqa: PLC0415

            cache = AnalysisCache(args.cache)
            print(f"Analysis cache: {args.cache}\n")
        except Exception as exc:
            print(f"WARNING: could not open cache {args.cache!r}: {exc}", file=sys.stderr)
    else:
        print("Analysis cache: disabled (--no-cache)\n")

    sheets: dict[str, list[dict]] = {}
    first_download = True

    try:
        # ---- Author sets ----------------------------------------------------
        if not args.no_author:
            for sheet_name, page_url in args.authors:
                print(f"\n=== Fetching papers from author page: {page_url} ===")
                author_papers = fetch_author_page(page_url)
                print(f"Found {len(author_papers)} papers.\n")

                if author_papers:
                    print(f"=== Analysing {sheet_name} papers ({len(author_papers)}) ===")
                    rows = process_paper_set(
                        sheet_name, author_papers, cache_dir, first_download=first_download, cache=cache, llama_server_url=llama_server_url
                    )
                    sheets[sheet_name] = rows
                    first_download = False

                time.sleep(_API_DELAY)

        # ---- Local PDF folder sets ------------------------------------------
        if not args.no_pdf_folder:
            for sheet_name, folder_str in args.pdf_folders:
                folder_path = Path(folder_str)
                if not folder_path.is_dir():
                    print(
                        f"  WARNING: PDF folder {folder_path!r} does not exist — skipping.",
                        file=sys.stderr,
                    )
                    continue
                print(f"\n=== Analysing local PDFs: {folder_path}  →  sheet '{sheet_name}' ===")
                rows = process_local_folder(sheet_name, folder_path, cache=cache, llama_server_url=llama_server_url)
                if rows:
                    sheets[sheet_name] = rows

        # ---- Category set ---------------------------------------------------
        if not args.no_category:
            search_query = _build_category_query(args.category, args.category_before)
            date_note = f" (before {args.category_before})" if args.category_before else ""
            print(f"\n=== Fetching papers from category: {args.category}{date_note} (max {args.category_max}) ===")
            cat_papers = fetch_arxiv_papers(search_query, max_results=args.category_max)
            print(f"Found {len(cat_papers)} papers.\n")

            if cat_papers:
                print(f"=== Analysing {args.category} papers ({len(cat_papers)}) ===")
                rows = process_paper_set(
                    args.category,
                    cat_papers,
                    cache_dir,
                    first_download=first_download,
                    cache=cache,
                    llama_server_url=llama_server_url,
                )
                sheets[args.category] = rows

    finally:
        if cache is not None:
            cache.close()

    # ---- Write output -------------------------------------------------------
    if not sheets:
        print("No data to write — exiting.")
        return

    write_excel(Path(args.output), sheets)


if __name__ == "__main__":
    main()
