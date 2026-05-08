#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import re

# ---------------------------------------------------------------------------
# Bibliography heading pattern.
# ---------------------------------------------------------------------------

_BIBLIO_HEADING = re.compile(
    r"^\s*(references|bibliography|works\s+cited)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

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

# Minimum fraction of pre_core that must precede an appendix heading for it
# to be treated as a genuine section heading rather than a TOC entry or an
# early cross-reference such as "see Appendix A for details".
_MIN_APPENDIX_FRACTION = 0.25

# ---------------------------------------------------------------------------
# Math-line filtering.
# ---------------------------------------------------------------------------

_ENGLISH_WORD = re.compile(r"[a-zA-Z]{5,}")

# ---------------------------------------------------------------------------
# Heading detection patterns.
# ---------------------------------------------------------------------------

# Chapter heading: "Chapter 1", "Chapter 2  The Standard Model", "Chapter 1: Introduction"
_CHAPTER_HEADING = re.compile(r"^\s*chapter\s+(\d+)[\s:.\-–—]*(.*)?$", re.IGNORECASE)

# Numbered top-level section: "1.", "2", "3.  Title" — exactly one numeric component
# Requires at least one non-whitespace character after the number (to exclude bare numbers).
_NUMBERED_TOP_HEADING = re.compile(r"^\s*(\d+)\.?\s+(\S.*)?$")

# Numbered subsection: "1.1", "2.3.4", etc. — two or more dot-separated components
_NUMBERED_SUB_HEADING = re.compile(r"^\s*\d+\.\d+")

# Sentence-ending punctuation (excludes trailing period as allowed by spec)
_SENTENCE_END_MID = re.compile(r"[.?!](?!\s*$)")


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


def _strip_toc_lines(text: str) -> str:
    """
    Remove lines that look like table-of-contents entries from *text*.

    Two patterns are matched:
      1. Space-separated dot leaders: ". . . . ." (3+ repetitions)
      2. Consecutive dots: "...." (4+ consecutive)

    Both patterns are characteristic of PDF-extracted TOC pages.  These lines
    are pure navigational noise for the LLM and can trigger pathological
    grammar-constrained generation (the model quotes the dotted leaders verbatim
    as an "excerpt", producing an unbounded string that Ollama cannot terminate).
    """
    _TOC_LEADER_RE = re.compile(r"(?:\.\s){3,}|\.{4,}")
    lines = text.splitlines()
    return "\n".join(line for line in lines if not _TOC_LEADER_RE.search(line))


def _strip_math_lines(text: str) -> str:
    """
    Remove lines that consist predominantly of mathematical notation produced
    by PDF text extraction of LaTeX-typeset equations.

    A line is *kept* if and only if it contains at least one run of five or
    more consecutive ASCII letters, or is blank (blank lines preserve paragraph
    structure).
    """
    kept = []
    for line in text.splitlines():
        if not line.strip() or _ENGLISH_WORD.search(line):
            kept.append(line)
    return "\n".join(kept)


def _strip_chapter_prefix(line: str) -> str:
    """Strip 'Chapter N' prefix and any trailing punctuation from a heading line."""
    m = _CHAPTER_HEADING.match(line)
    if m:
        return (m.group(2) or "").strip()
    return line.strip()


def _strip_number_prefix(line: str) -> str:
    """Strip leading numeric prefix (e.g. '2.') from a heading line."""
    m = _NUMBERED_TOP_HEADING.match(line)
    if m:
        return (m.group(2) or "").strip()
    return line.strip()


def _is_unnumbered_heading(line: str, prev_blank: bool, next_blank: bool) -> bool:
    """Return True if *line* qualifies as an unnumbered short heading."""
    stripped = line.strip()
    if not stripped:
        return False
    if len(stripped) > 60:
        return False
    # Must be surrounded by blank lines (or doc boundary)
    if not prev_blank or not next_blank:
        return False
    # No sentence-ending punctuation except an optional trailing period
    if _SENTENCE_END_MID.search(stripped):
        return False
    # Must not match numbered patterns
    if _NUMBERED_TOP_HEADING.match(line) or _NUMBERED_SUB_HEADING.match(line):
        return False
    # Must not match chapter pattern
    if _CHAPTER_HEADING.match(line):
        return False
    return True


def _detect_top_level_sections(text: str) -> tuple[list[dict], str]:
    """
    Parse *text* to identify top-level structural sections.

    Returns ``(sections, style)`` where:

    - *sections* is a list of ``{"heading": str, "full_text": str}`` dicts in
      document order.  The heading string has its numeric prefix stripped; the
      full_text includes the heading line itself and all subordinate content.
    - *style* is one of ``"chapter"``, ``"numbered"``, ``"unnumbered"``, or
      ``"none"`` (no detectable headings).

    Heading detection priority (earlier rules take precedence):

    1. Chapter headings — always top-level when present.
    2. Single-number headings (``1.``, ``2``) — top-level only when no chapter
       headings exist; subordinate otherwise.
    3. Numbered subsections (``1.1``, ``2.3.4``) — never top-level.
    4. Unnumbered short headings — top-level only when neither chapters nor
       numbered headings are found.
    """
    lines = text.splitlines()
    n = len(lines)

    # ------------------------------------------------------------------
    # Pass 1: categorise each line.
    # ------------------------------------------------------------------
    # Each entry: ("chapter"|"numbered_top"|"numbered_sub"|"unnumbered"|"body", display_heading)
    categories: list[tuple[str, str]] = []

    for i, line in enumerate(lines):
        stripped = line.strip()

        if not stripped:
            categories.append(("blank", ""))
            continue

        if _CHAPTER_HEADING.match(line):
            categories.append(("chapter", ""))
            continue

        if _NUMBERED_SUB_HEADING.match(line):
            categories.append(("numbered_sub", ""))
            continue

        m_top = _NUMBERED_TOP_HEADING.match(line)
        if m_top:
            # Exclude lines where the numeric part itself contains dots (already
            # caught by numbered_sub), but also guard against "1234 words" style.
            # The regex already enforces exactly one numeric component.
            categories.append(("numbered_top", ""))
            continue

        # Unnumbered: check blank neighbours
        prev_blank = (i == 0) or (not lines[i - 1].strip())
        next_blank = (i == n - 1) or (not lines[i + 1].strip())
        if _is_unnumbered_heading(line, prev_blank, next_blank):
            categories.append(("unnumbered", ""))
            continue

        categories.append(("body", ""))

    # ------------------------------------------------------------------
    # Pass 2: determine document style.
    # ------------------------------------------------------------------
    has_chapter = any(c == "chapter" for c, _ in categories)
    has_numbered_top = any(c == "numbered_top" for c, _ in categories)
    has_unnumbered = any(c == "unnumbered" for c, _ in categories)

    if has_chapter:
        style = "chapter"
        top_level_cats = {"chapter"}
    elif has_numbered_top:
        style = "numbered"
        top_level_cats = {"numbered_top"}
    elif has_unnumbered:
        style = "unnumbered"
        top_level_cats = {"unnumbered"}
    else:
        return [], "none"

    # ------------------------------------------------------------------
    # Pass 3: locate top-level heading line indices.
    # ------------------------------------------------------------------
    # For chapter style: a chapter heading may span two lines when the title
    # is on the line immediately following "Chapter N" with no trailing text.
    top_level_indices: list[int] = []
    skip_next = False

    for i, (cat, _) in enumerate(categories):
        if skip_next:
            skip_next = False
            continue
        if cat in top_level_cats:
            top_level_indices.append(i)
            # If this is a chapter heading with no inline title, check next
            # non-blank line to see if it forms part of the heading.
            if cat == "chapter":
                m = _CHAPTER_HEADING.match(lines[i])
                if m and not (m.group(2) or "").strip():
                    # No inline title — look at next non-blank line
                    for j in range(i + 1, min(i + 3, n)):
                        if lines[j].strip():
                            # Treat as continuation title only if it's body text
                            if categories[j][0] not in top_level_cats and categories[j][0] not in ("numbered_sub",):
                                skip_next = (j == i + 1)
                            break

    if not top_level_indices:
        return [], "none"

    # ------------------------------------------------------------------
    # Pass 4: build section dicts.
    # ------------------------------------------------------------------
    sections: list[dict] = []

    for k, start_idx in enumerate(top_level_indices):
        end_idx = top_level_indices[k + 1] if k + 1 < len(top_level_indices) else n

        # Build the heading string
        line = lines[start_idx]
        if style == "chapter":
            m = _CHAPTER_HEADING.match(line)
            inline_title = (m.group(2) or "").strip() if m else ""
            if not inline_title:
                # Look for title on next non-blank line inside this section
                for j in range(start_idx + 1, end_idx):
                    candidate = lines[j].strip()
                    if candidate:
                        # Use next non-blank line as title if it's not a sub-heading
                        if not _NUMBERED_SUB_HEADING.match(lines[j]) and not _CHAPTER_HEADING.match(lines[j]):
                            inline_title = candidate
                        break
            heading_text = inline_title
        elif style == "numbered":
            heading_text = _strip_number_prefix(line)
        else:
            heading_text = line.strip()

        # Skip bare-number headings (nothing after stripping the numeric prefix)
        if not heading_text:
            continue

        full_text = "\n".join(lines[start_idx:end_idx]).rstrip()
        sections.append({"heading": heading_text, "full_text": full_text})

    if not sections:
        return [], "none"

    return sections, style
