#!/usr/bin/env python3
"""
arxiv_control_analysis.py — Download arXiv papers and run the full language
analysis pipeline (MATTR, MTLD, Goh-Barabási burstiness, sentence-length CV)
to build a control-sample distribution from known-human, non-LLM text.

Paper sets analysed:
  1. All papers by each arXiv author (scraped from their arXiv author page).
     Default authors: Seery (djs61), Byrnes (byrnes_c), Burrage (burrage_c).
  2. ~200 papers from the astro-ph.CO category submitted before a fixed cutoff
     date (default: 2026-04-20) to ensure a stable, reproducible reference set.

Results are written to an Excel file with one worksheet per set.

Usage
-----
  arxiv_analysis_venv/bin/python arxiv_control_analysis.py [options]

Options
-------
  --output PATH              Output .xlsx path  [default: arxiv_control_results.xlsx]
  --pdf-cache DIR            Directory for downloaded PDFs  [default: arxiv_pdf_cache/]
  --author SHEET URL         Worksheet name + author page URL (repeatable)
                             [default: three authors listed above]
  --category CAT             arXiv subject category  [default: astro-ph.CO]
  --category-max N           Max papers to fetch from category  [default: 200]
  --category-before DATE     Cutoff date YYYY-MM-DD for category papers  [default: 2026-04-20]
  --no-author                Skip all author sets
  --no-category              Skip the category set

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
from pathlib import Path

import feedparser
import pandas as pd
import requests

# All algorithm code comes from the shared core module.
from language_analysis_core import analyse_paper, _get_nlp

# ---------------------------------------------------------------------------
# arXiv helpers
# ---------------------------------------------------------------------------

ARXIV_API_BASE = "https://export.arxiv.org/api/query"
ARXIV_PDF_BASE = "https://arxiv.org/pdf"
_API_DELAY = 3.0   # seconds between API requests (arXiv policy)
_PDF_DELAY = 3.0   # seconds between PDF downloads

# Simple regex helpers for HTML scraping — avoids a BeautifulSoup dependency.
_HTML_TAG = re.compile(r'<[^>]+>')
_WHITESPACE = re.compile(r'\s+')

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
_AUTHOR_LINK = re.compile(r'<a[^>]*>([^<]+)</a>')


def _strip_html(s: str) -> str:
    return html_module.unescape(_WHITESPACE.sub(" ", _HTML_TAG.sub("", s)).strip())


def _arxiv_id_approx_date(arxiv_id: str) -> str:
    """Derive an approximate submission date from a modern arXiv ID (YYMM.NNNNN)."""
    m = re.match(r'^(\d{2})(\d{2})\.\d+$', arxiv_id)
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
            authors = ", ".join(
                a.get("name", "") for a in getattr(entry, "authors", [])
            )
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


def process_paper_set(
    label: str,
    papers: list[dict],
    cache_dir: Path,
    first_download: bool,
) -> list[dict]:
    """Download PDFs and run analysis for each paper in *papers*.

    Returns a list of result dicts (one per paper, metadata merged in).
    """
    rows = []
    total = len(papers)

    for idx, meta in enumerate(papers, 1):
        arxiv_id = meta["arxiv_id"]
        print(f"  [{idx}/{total}] {arxiv_id}  \"{meta['title'][:60]}\"")

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
                    "mattr_flag": "unknown",
                    "mtld_flag": "unknown",
                    "burstiness_flag": "unknown",
                    "sentence_cv_flag": "unknown",
                    "error": "PDF download failed",
                }
            )
        else:
            print(f"    Analysing …", end=" ", flush=True)
            metrics = analyse_paper(pdf_path)
            row.update(metrics)
            if metrics["error"]:
                print(f"ERROR: {metrics['error']}")
            else:
                all_numeric = all(
                    metrics.get(k) is not None
                    for k in ("mattr", "mtld", "burstiness", "sentence_cv")
                )
                if all_numeric:
                    print(
                        f"MATTR={metrics['mattr']:.3f}  MTLD={metrics['mtld']:.1f}  "
                        f"B={metrics['burstiness']:.3f}  CV={metrics['sentence_cv']:.3f}"
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
    ["djs61",     "https://arxiv.org/a/seery_d_1.html"],
    ["byrnes_c",  "https://arxiv.org/a/0000-0003-2583-6536.html"],
    ["burrage_c", "https://arxiv.org/a/burrage_c_1.html"],
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run language analysis on arXiv papers and export to Excel."
    )
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
        help="Worksheet name and arXiv author page URL (repeatable). "
             "Default: Seery, Byrnes, Burrage.",
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
    parser.add_argument("--no-author", action="store_true", help="Skip all author paper sets")
    parser.add_argument("--no-category", action="store_true", help="Skip category paper set")
    args = parser.parse_args()

    if not args.authors:
        args.authors = _DEFAULT_AUTHORS

    cache_dir = Path(args.pdf_cache)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Pre-load spaCy model once so the first paper doesn't pay a silent delay
    print("Loading spaCy model …", flush=True)
    _get_nlp()
    print("spaCy model ready.\n")

    sheets: dict[str, list[dict]] = {}
    first_download = True

    # ---- Author sets --------------------------------------------------------
    if not args.no_author:
        for sheet_name, page_url in args.authors:
            print(f"\n=== Fetching papers from author page: {page_url} ===")
            author_papers = fetch_author_page(page_url)
            print(f"Found {len(author_papers)} papers.\n")

            if author_papers:
                print(f"=== Analysing {sheet_name} papers ({len(author_papers)}) ===")
                rows = process_paper_set(sheet_name, author_papers, cache_dir, first_download=first_download)
                sheets[sheet_name] = rows
                first_download = False

            time.sleep(_API_DELAY)

    # ---- Category set -------------------------------------------------------
    if not args.no_category:
        search_query = _build_category_query(args.category, args.category_before)
        date_note = f" (before {args.category_before})" if args.category_before else ""
        print(f"\n=== Fetching papers from category: {args.category}{date_note} (max {args.category_max}) ===")
        cat_papers = fetch_arxiv_papers(search_query, max_results=args.category_max)
        print(f"Found {len(cat_papers)} papers.\n")

        if cat_papers:
            print(f"=== Analysing {args.category} papers ({len(cat_papers)}) ===")
            rows = process_paper_set(
                args.category, cat_papers, cache_dir, first_download=first_download
            )
            sheets[args.category] = rows

    # ---- Write output -------------------------------------------------------
    if not sheets:
        print("No data to write — exiting.")
        return

    write_excel(Path(args.output), sheets)


if __name__ == "__main__":
    main()
