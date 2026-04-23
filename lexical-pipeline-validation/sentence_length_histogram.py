"""
sentence_length_histogram.py — Plot the distribution of sentence lengths in a PDF.

Uses the text-extraction and cleaning pipeline from language_analysis_core.py,
then tokenises sentences with spaCy (same logic as compute_sentence_cv).

Usage:
    python sentence_length_histogram.py [PDF_PATH]

Default PDF: Project_report_Final_version_1_.pdf

Output:
    - Summary statistics printed to stdout
    - sentence_length_histogram.png saved in the current directory
    - Interactive plot window (if a display is available)

Requires the arxiv_analysis_venv environment (spaCy, PyMuPDF, matplotlib).
"""

from __future__ import annotations

import sys

import numpy as np

from language_analysis_core import (
    _get_nlp,
    _looks_like_code,
    extract_pdf_text,
    split_document,
    strip_math_lines,
)


def collect_sentence_lengths(clean_content_text: str) -> list[int]:
    """Return per-sentence token counts using the same logic as compute_sentence_cv.

    Sentences that look like source code (high code-punctuation density or high
    underscore-identifier fraction) are silently discarded before counting.
    Also prints the longest surviving sentence to stdout.
    """
    nlp = _get_nlp()
    doc = nlp(clean_content_text)

    pairs = [
        (
            sum(1 for tok in sent if not tok.is_punct and not tok.is_space),
            sent.text.strip(),
        )
        for sent in doc.sents
    ]
    # Drop trivial and code-like sentences
    pairs = [(ln, txt) for ln, txt in pairs if ln > 1 and not _looks_like_code(txt)]

    if pairs:
        max_len, max_sent = max(pairs, key=lambda p: p[0])
        print(f"\n--- Longest sentence ({max_len} tokens) ---")
        print(max_sent)

    return [ln for ln, _ in pairs]


def main():
    pdf_path = (
        sys.argv[1] if len(sys.argv) > 1 else "Project_report_Final_version_1_.pdf"
    )

    print(f"Extracting text from: {pdf_path}")
    raw_text, page_count = extract_pdf_text(pdf_path)
    print(f"  Pages: {page_count}")

    _core, _references, _appendices = split_document(raw_text)
    content_text = (_core + "\n\n" + _appendices) if _appendices else _core
    clean_content = strip_math_lines(content_text)

    print("Tokenising sentences with spaCy …")
    lengths = collect_sentence_lengths(clean_content)

    if not lengths:
        print("No sentences found — cannot produce histogram.")
        sys.exit(1)

    arr = np.array(lengths, dtype=float)
    mean_len = arr.mean()
    median_len = float(np.median(arr))
    std_len = arr.std(ddof=1)
    cv = std_len / mean_len if mean_len > 0 else float("nan")

    print("\n--- Sentence-length statistics ---")
    print(f"  Sentences : {len(lengths)}")
    print(f"  Min       : {int(arr.min())}")
    print(f"  Max       : {int(arr.max())}")
    print(f"  Mean      : {mean_len:.2f}")
    print(f"  Median    : {median_len:.1f}")
    print(f"  Std dev   : {std_len:.2f}")
    print(f"  CV (σ/μ)  : {cv:.3f}")

    # --- Histogram ---
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))

    ax.hist(lengths, bins=50, color="steelblue", edgecolor="white", linewidth=0.4)
    ax.axvline(
        mean_len,
        color="crimson",
        linewidth=1.5,
        linestyle="--",
        label=f"Mean = {mean_len:.1f}",
    )
    ax.axvline(
        median_len,
        color="darkorange",
        linewidth=1.5,
        linestyle=":",
        label=f"Median = {median_len:.1f}",
    )

    ax.set_xlabel("Sentence length (tokens)", fontsize=12)
    ax.set_ylabel("Count", fontsize=12)
    ax.set_title(
        f"Sentence-length distribution\n{pdf_path}  |  n={len(lengths)}  CV={cv:.3f}",
        fontsize=11,
    )
    ax.legend()
    fig.tight_layout()

    out_path = "sentence_length_histogram.png"
    fig.savefig(out_path, dpi=150)
    print(f"\nHistogram saved to: {out_path}")


if __name__ == "__main__":
    main()
