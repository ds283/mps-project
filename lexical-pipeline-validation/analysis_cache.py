"""
analysis_cache.py — SQLite-backed results cache for the MPS
lexical-pipeline-validation scripts.

Role in the analysis chain
--------------------------
This module provides persistent caching for arxiv_control_analysis.py,
avoiding redundant PDF processing and (future) LLM inference on repeated
runs. It stores results keyed by the SHA-256 hash of the raw extracted PDF
text, which is stable for a given file and PyMuPDF version.

The module does NOT implement any analysis logic — it is purely a cache
manager. All metric computation is done by language_analysis_core.py.

                language_analysis_core.py
                        ↓ computes metrics
    arxiv_control_analysis.py  ←→  analysis_cache.py  (this file)
                        ↓ writes results
                arxiv_control_results.xlsx
                        ↓ consumed by
            lexical_diversity_pipeline.py

Tables
------
text_metrics
    One row per unique PDF text (PRIMARY KEY = SHA-256(raw_text)).
    Stores lexical metrics: mattr, mtld, burstiness, sentence_cv, word_count,
    page_count, reference_count, plus provenance columns: pymupdf_version,
    pipeline_version (from language_analysis_core.PIPELINE_VERSION),
    source_path, arxiv_id, computed_at.

llm_metrics
    One row per (text_hash × LLM model × context_size × prompt_version).
    Scaffolded now (Q-D from design notes); currently all rows have
    mean_nll = NULL because NLL_ENABLED = False in language_analysis_core.py
    (Ollama does not yet expose logprob computation). A NULL row is stored
    to record that the LLM was called, preventing re-submission on the next
    run. When NLL_ENABLED becomes True, existing NULL rows remain; new runs
    will compute real values.

Both tables are created with CREATE TABLE IF NOT EXISTS and the database is
opened in WAL mode for concurrent-safe access.

Cache invalidation
------------------
There is NO automatic invalidation on PIPELINE_VERSION bump. When any metric
computation changes, the operator must either delete the .sqlite file or
invoke arxiv_control_analysis.py with --no-cache to bypass the cache for
that run.

The pymupdf_version column in text_metrics lets operators detect when a
PyMuPDF upgrade has silently changed all text_hash values (and thus caused
a cold-cache miss for every paper).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional


class AnalysisCache:
    """SQLite-backed cache for language analysis results.

    Open with a path; use as a context manager (recommended) or call
    close() manually.  The database is created on first open.

    Usage::

        with AnalysisCache("analysis_cache.sqlite") as cache:
            cached = cache.get_metrics(text_hash)
            if cached is None:
                result = analyse_paper_from_text(raw_text, page_count)
                cache.store_metrics(text_hash, result, source_path=str(pdf_path))
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._open()

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> "AnalysisCache":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _open(self) -> None:
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS text_metrics (
                text_hash         TEXT    PRIMARY KEY,
                source_path       TEXT,
                arxiv_id          TEXT,
                page_count        INTEGER,
                word_count        INTEGER,
                reference_count   INTEGER,
                mattr             REAL,
                mtld              REAL,
                burstiness        REAL,
                sentence_cv       REAL,
                pymupdf_version   TEXT,
                pipeline_version  INTEGER,
                computed_at       TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_text_metrics_arxiv_id
                ON text_metrics(arxiv_id);

            CREATE TABLE IF NOT EXISTS llm_metrics (
                text_hash         TEXT    NOT NULL
                    REFERENCES text_metrics(text_hash),
                model             TEXT    NOT NULL,
                context_size      INTEGER NOT NULL,
                prompt_version    INTEGER NOT NULL,
                prompt_hash       TEXT,
                mean_nll          REAL,
                nll_cv            REAL,
                computed_at       TEXT,
                PRIMARY KEY (text_hash, model, context_size, prompt_version)
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # text_metrics — lexical metric cache
    # ------------------------------------------------------------------

    def get_metrics(self, text_hash: str) -> Optional[dict]:
        """Return cached lexical metrics for *text_hash*, or None on miss."""
        row = self._conn.execute(
            "SELECT * FROM text_metrics WHERE text_hash = ?", (text_hash,)
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    def store_metrics(
        self,
        text_hash: str,
        metrics: dict,
        source_path: Optional[str] = None,
        arxiv_id: Optional[str] = None,
        pymupdf_version: Optional[str] = None,
    ) -> None:
        """Insert or replace a text_metrics row for *text_hash*.

        *metrics* is the dict returned by analyse_paper_from_text().
        """
        from language_analysis_core import PIPELINE_VERSION  # noqa: PLC0415

        now = datetime.now().isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO text_metrics
                (text_hash, source_path, arxiv_id,
                 page_count, word_count, reference_count,
                 mattr, mtld, burstiness, sentence_cv,
                 pymupdf_version, pipeline_version, computed_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                text_hash,
                source_path,
                arxiv_id,
                metrics.get("page_count"),
                metrics.get("word_count"),
                metrics.get("reference_count"),
                metrics.get("mattr"),
                metrics.get("mtld"),
                metrics.get("burstiness"),
                metrics.get("sentence_cv"),
                pymupdf_version,
                PIPELINE_VERSION,
                now,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # llm_metrics — NLL scaffold (currently always NULL)
    # ------------------------------------------------------------------

    def get_nll(
        self,
        text_hash: str,
        model: str,
        context_size: int,
        prompt_version: int,
        prompt_hash: str,
    ) -> Optional[dict]:
        """Return cached NLL metrics, or None on miss.

        A hit with mean_nll = NULL indicates the LLM was called but NLL
        was unavailable (NLL_ENABLED = False).  Callers should treat this
        as a valid cache entry and not re-submit.
        """
        row = self._conn.execute(
            """
            SELECT * FROM llm_metrics
             WHERE text_hash = ? AND model = ? AND context_size = ?
               AND prompt_version = ?
            """,
            (text_hash, model, context_size, prompt_version),
        ).fetchone()
        if row is None:
            return None
        cached_prompt_hash = row["prompt_hash"]
        if cached_prompt_hash and cached_prompt_hash != prompt_hash:
            import warnings  # noqa: PLC0415

            warnings.warn(
                f"prompt_hash mismatch for text_hash={text_hash!r}: "
                f"cached={cached_prompt_hash!r} current={prompt_hash!r}. "
                "Returning cached result; re-run with --no-cache to refresh.",
                stacklevel=2,
            )
        return dict(row)

    def store_nll(
        self,
        text_hash: str,
        model: str,
        context_size: int,
        prompt_version: int,
        prompt_hash: str,
        nll_data: dict,
    ) -> None:
        """Insert or replace an llm_metrics row.

        *nll_data* may contain mean_nll=None when NLL_ENABLED=False; the
        row is stored anyway to prevent re-submission on the next run.
        """
        now = datetime.now().isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO llm_metrics
                (text_hash, model, context_size, prompt_version,
                 prompt_hash, mean_nll, nll_cv, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                text_hash,
                model,
                context_size,
                prompt_version,
                prompt_hash,
                nll_data.get("mean_nll"),
                nll_data.get("nll_cv"),
                now,
            ),
        )
        self._conn.commit()
