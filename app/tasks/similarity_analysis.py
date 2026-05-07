#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import json

import redis as redis_lib
from celery import chain
from flask import current_app
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import SimilarityOrchestrationJob, SimilarityConcern, SubmissionRecord, TaskRecord, User
from ..shared.llm_services import _call_llm
from ..shared.scraped_text_store import (
    get_scraped_text,
    get_similarity_chunks,
    store_minhash_signatures,
    store_similarity_chunks,
)
from ..shared.text_utils import _detect_top_level_sections, _split_document, _strip_math_lines
from ..task_queue import progress_update

# ---------------------------------------------------------------------------
# Pipeline constants
# ---------------------------------------------------------------------------

CHUNK_EXTRACTION_PROMPT_VERSION = 1

CHUNK_TYPES = [
    "abstract",
    "introduction",
    "literature_review",
    "methodology",
    "results",
    "discussion",
    "conclusions",
]

CHUNK_SIMILARITY_THRESHOLD = {
    "abstract": 0.75,
    "introduction": 0.80,
    "literature_review": 0.82,
    "methodology": 0.78,
    "results": 0.88,
    "discussion": 0.85,
    "conclusions": 0.78,
}

MINHASH_LSH_THRESHOLD = 0.15
MINHASH_NUM_PERM = 128

_CHUNK_EXTRACTION_CTX_KEY = "OLLAMA_CHUNK_EXTRACTION_CONTEXT_SIZE"
_CHUNK_EXTRACTION_CTX_DEFAULT = 12288

# ---------------------------------------------------------------------------
# Lazy sentence-transformers model loader
# ---------------------------------------------------------------------------

_st_model = None


def _get_st_model():
    global _st_model
    if _st_model is None:
        from sentence_transformers import SentenceTransformer

        _st_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _st_model


# ---------------------------------------------------------------------------
# LLM prompt builders
# ---------------------------------------------------------------------------


def _build_heading_classification_system_prompt() -> str:
    chunk_list = "\n".join(f'  - "{ct}"' for ct in CHUNK_TYPES)
    return f"""You are a document structure classifier for undergraduate and postgraduate physics project reports.

Your task is to classify each top-level section heading into exactly one of the following categories, or null if none fits:

{chunk_list}

Guidelines for ambiguous cases:
- "Background and Motivation" → "introduction"
- "Theory" or "Theoretical Framework" → "methodology" (unless clearly a literature survey → "literature_review")
- "Analysis" → "results" if it presents findings; "methodology" if it describes an analytical approach
- "Summary" at the end of the document → "conclusions"
- "Results and Discussion" → "results"
- "Discussion and Conclusions" → "conclusions"
- Preface, Acknowledgements, Notation, Abbreviations, List of Figures → null

Rules:
1. Classify every heading supplied. Do not omit any.
2. Use only the category strings listed above or null. Do not invent categories.
3. Do not merge or rename headings. Use the exact heading string as the key.
4. Return exactly as many keys as headings supplied."""


def _build_heading_classification_user_prompt(headings: list[str]) -> str:
    numbered = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headings))
    return (
        "The following are the top-level section headings from a physics project report.\n"
        "Classify each one.\n\n"
        f"{numbered}"
    )


def _build_heading_classification_schema(headings: list[str]) -> dict:
    value_schema = {
        "type": ["string", "null"],
        "enum": list(CHUNK_TYPES) + [None],
    }
    return {
        "type": "object",
        "properties": {h: value_schema for h in headings},
        "required": headings,
        "additionalProperties": False,
    }


# ---------------------------------------------------------------------------
# Redis helper (reuses orchestration Redis)
# ---------------------------------------------------------------------------


def _get_redis() -> redis_lib.Redis:
    url = current_app.config.get("ORCHESTRATION_REDIS_URL")
    if not url:
        raise RuntimeError("ORCHESTRATION_REDIS_URL is not set in the Flask configuration")
    return redis_lib.Redis.from_url(url, decode_responses=False)


def _cleanup_job_redis(job: SimilarityOrchestrationJob) -> None:
    try:
        r = _get_redis()
        r.delete(job.redis_queue_key, job.redis_inflight_key)
    except Exception as exc:
        current_app.logger.warning(
            f"similarity_analysis: could not clean up Redis keys for job {job.uuid}: {exc}"
        )


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def register_similarity_analysis_tasks(celery):

    # -----------------------------------------------------------------------
    # Task 1: extract_chunks  (llm_tasks queue)
    # -----------------------------------------------------------------------

    @celery.task(
        bind=True,
        default_retry_delay=30,
        soft_time_limit=3600,
        time_limit=3660,
    )
    def extract_chunks(self, record_id: int):
        """
        Phase 1/3 of similarity pipeline.

        CPU: detect document headings.
        LLM: classify top-level headings into CHUNK_TYPES.
        CPU: merge section texts by classification.

        Result stored in MongoDB similarity_chunks subdocument.
        """
        from billiard.exceptions import SoftTimeLimitExceeded

        # ------------------------------------------------------------------
        # Load record and guard on language analysis completion
        # ------------------------------------------------------------------
        try:
            record: SubmissionRecord = db.session.get(SubmissionRecord, record_id)
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                f"extract_chunks: SQLAlchemyError loading SubmissionRecord #{record_id}"
            )
            raise self.retry(exc=exc)

        if record is None:
            current_app.logger.warning(
                f"extract_chunks: SubmissionRecord #{record_id} not found — skipping"
            )
            return

        if not record.language_analysis_complete:
            current_app.logger.warning(
                f"extract_chunks: SubmissionRecord #{record_id} language analysis not complete — skipping"
            )
            return

        # ------------------------------------------------------------------
        # Idempotency check
        # ------------------------------------------------------------------
        existing = get_similarity_chunks(record_id)
        if existing is not None and existing.get("chunk_prompt_version") == CHUNK_EXTRACTION_PROMPT_VERSION:
            current_app.logger.info(
                f"extract_chunks: SubmissionRecord #{record_id} already has current chunk extraction — skipping"
            )
            return

        # ------------------------------------------------------------------
        # Retrieve scraped text
        # ------------------------------------------------------------------
        scraped = get_scraped_text(record_id)
        if scraped is None:
            current_app.logger.warning(
                f"extract_chunks: no scraped text in cache for SubmissionRecord #{record_id} — skipping"
            )
            return

        raw_text: str = scraped.get("scraped_text", "")
        if not raw_text:
            current_app.logger.warning(
                f"extract_chunks: empty scraped text for SubmissionRecord #{record_id} — skipping"
            )
            return

        # ------------------------------------------------------------------
        # Phase 1 — CPU heading detection
        # ------------------------------------------------------------------
        _core, _references, _appendices = _split_document(raw_text)
        clean_core = _strip_math_lines(_core)
        top_level_sections, heading_style = _detect_top_level_sections(clean_core)

        context_size: int = current_app.config.get(_CHUNK_EXTRACTION_CTX_KEY, _CHUNK_EXTRACTION_CTX_DEFAULT)
        base_url: str = current_app.config.get("OLLAMA_BASE_URL", "http://localhost:11434")
        model: str = current_app.config.get("OLLAMA_MODEL", "llama3.1:70b")

        _empty_sections = {ct: {"text": "", "present": False} for ct in CHUNK_TYPES}

        if not top_level_sections:
            current_app.logger.warning(
                f"extract_chunks: no top-level sections detected for SubmissionRecord #{record_id} "
                f"(heading_style=none) — storing all chunks as absent"
            )
            store_similarity_chunks(
                record_id, _empty_sections, model, CHUNK_EXTRACTION_PROMPT_VERSION, "none", 0
            )
            return

        # ------------------------------------------------------------------
        # Phase 2 — LLM heading classification
        # ------------------------------------------------------------------
        heading_strings = [s["heading"] for s in top_level_sections]
        system_prompt = _build_heading_classification_system_prompt()
        user_prompt = _build_heading_classification_user_prompt(heading_strings)
        schema = _build_heading_classification_schema(heading_strings)

        db.session.close()

        try:
            parsed_result, _accumulated, last_exc, _est_tok = _call_llm(
                base_url=base_url,
                model=model,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema=schema,
                options={"num_ctx": context_size},
                label=f"extract_chunks/classify_headings (record #{record_id})",
            )
        except SoftTimeLimitExceeded:
            raise

        if parsed_result is None:
            current_app.logger.error(
                f"extract_chunks: LLM classification failed for SubmissionRecord #{record_id} "
                f"— storing all chunks as absent"
            )
            store_similarity_chunks(
                record_id, _empty_sections, model, CHUNK_EXTRACTION_PROMPT_VERSION, heading_style, len(top_level_sections)
            )
            return

        # ------------------------------------------------------------------
        # Phase 3 — CPU merge
        # ------------------------------------------------------------------
        chunk_texts: dict[str, list[str]] = {ct: [] for ct in CHUNK_TYPES}
        for section in top_level_sections:
            heading = section["heading"]
            assigned_type = parsed_result.get(heading)
            if assigned_type and assigned_type in CHUNK_TYPES:
                chunk_texts[assigned_type].append(section["full_text"])

        sections_out = {
            ct: {
                "text": "\n\n".join(chunk_texts[ct]),
                "present": bool(chunk_texts[ct]),
            }
            for ct in CHUNK_TYPES
        }

        # ------------------------------------------------------------------
        # Persist and finish
        # ------------------------------------------------------------------
        store_similarity_chunks(
            record_id,
            sections_out,
            model,
            CHUNK_EXTRACTION_PROMPT_VERSION,
            heading_style,
            len(top_level_sections),
        )

        try:
            record = db.session.get(SubmissionRecord, record_id)
            if record is not None:
                db.session.commit()
        except SQLAlchemyError as exc:
            current_app.logger.warning(
                f"extract_chunks: SQLAlchemyError on session reload for record #{record_id}: {exc}"
            )
            db.session.rollback()
            raise self.retry(exc=exc)

        current_app.logger.info(
            f"extract_chunks: completed for SubmissionRecord #{record_id} "
            f"(style={heading_style}, sections={len(top_level_sections)})"
        )

    # -----------------------------------------------------------------------
    # Task 2: compute_minhash  (default queue)
    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def compute_minhash(self, record_id: int):
        """
        Phase 2/3 of similarity pipeline.

        Compute datasketch MinHash signatures for each present chunk type.
        Stores hashvalue lists in MongoDB similarity_chunks.minhash_signatures.
        """
        from datasketch import MinHash

        chunks = get_similarity_chunks(record_id)
        if chunks is None:
            current_app.logger.warning(
                f"compute_minhash: no similarity_chunks in cache for SubmissionRecord #{record_id} — skipping"
            )
            return

        sections = chunks.get("sections", {})
        if not sections:
            current_app.logger.warning(
                f"compute_minhash: empty sections for SubmissionRecord #{record_id} — skipping"
            )
            return

        # Idempotency: skip if signatures already computed after the last extraction
        if chunks.get("minhash_signatures") and chunks.get("minhash_computed_at") and chunks.get("extracted_at"):
            computed_at = chunks["minhash_computed_at"]
            extracted_at = chunks["extracted_at"]
            if computed_at >= extracted_at:
                current_app.logger.info(
                    f"compute_minhash: signatures already current for SubmissionRecord #{record_id} — skipping"
                )
                return

        signatures: dict[str, list[int]] = {}

        for chunk_type in CHUNK_TYPES:
            section = sections.get(chunk_type, {})
            if not section.get("present", False):
                continue
            text = section.get("text", "")
            if not text:
                continue
            try:
                words = text.lower().split()
                shingles = set()
                for i in range(len(words) - 2):
                    shingles.add(tuple(words[i : i + 3]))

                mh = MinHash(num_perm=MINHASH_NUM_PERM)
                for shingle in shingles:
                    mh.update(" ".join(shingle).encode("utf-8"))

                signatures[chunk_type] = mh.hashvalues.tolist()
            except Exception as exc:
                current_app.logger.warning(
                    f"compute_minhash: failed for chunk '{chunk_type}' of record #{record_id}: {exc}"
                )

        if signatures:
            store_minhash_signatures(record_id, signatures)
            current_app.logger.info(
                f"compute_minhash: stored signatures for {list(signatures.keys())} "
                f"of SubmissionRecord #{record_id}"
            )
        else:
            current_app.logger.warning(
                f"compute_minhash: no signatures produced for SubmissionRecord #{record_id}"
            )

    # -----------------------------------------------------------------------
    # Task 3: run_similarity_check  (default queue)
    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def run_similarity_check(self, record_id: int):
        """
        Phase 3/3 of similarity pipeline.

        Compare this record against all others using MinHash LSH pre-filtering
        followed by sentence-transformer cosine similarity.  Records pairs
        exceeding per-chunk thresholds are stored as SimilarityConcern rows.
        """
        from datasketch import MinHash, MinHashLSH

        from ..shared.scraped_text_store import _get_collection

        chunks = get_similarity_chunks(record_id)
        if chunks is None or not chunks.get("minhash_signatures"):
            current_app.logger.warning(
                f"run_similarity_check: no minhash signatures for SubmissionRecord #{record_id} — skipping"
            )
            return

        current_sections = chunks.get("sections", {})
        current_sigs: dict[str, list[int]] = chunks["minhash_signatures"]

        # ------------------------------------------------------------------
        # Query all other records with computed signatures from MongoDB
        # ------------------------------------------------------------------
        client, collection = _get_collection()
        if collection is None:
            current_app.logger.warning(
                f"run_similarity_check: MongoDB not configured — skipping for record #{record_id}"
            )
            return

        try:
            cursor = collection.find(
                {
                    "submission_record_id": {"$ne": record_id},
                    "similarity_chunks.minhash_signatures": {"$exists": True},
                },
                projection={"submission_record_id": 1, "similarity_chunks": 1, "_id": 0},
            )
            other_docs = list(cursor)
        except Exception as exc:
            current_app.logger.warning(
                f"run_similarity_check: MongoDB query failed for record #{record_id}: {exc}"
            )
            return
        finally:
            client.close()

        if not other_docs:
            current_app.logger.info(
                f"run_similarity_check: no other records with signatures — skipping for record #{record_id}"
            )
            return

        st_model = _get_st_model()
        concerns_to_upsert: list[dict] = []

        # ------------------------------------------------------------------
        # Per-chunk LSH pre-filter + cosine re-rank
        # ------------------------------------------------------------------
        for chunk_type in CHUNK_TYPES:
            if chunk_type not in current_sigs:
                continue
            current_section = current_sections.get(chunk_type, {})
            if not current_section.get("present", False):
                continue
            current_text = current_section.get("text", "")
            if not current_text:
                continue

            current_hashvalues = current_sigs[chunk_type]
            current_mh = MinHash(num_perm=MINHASH_NUM_PERM)
            current_mh.hashvalues[:] = current_hashvalues

            # Build LSH index from other records for this chunk type
            lsh = MinHashLSH(threshold=MINHASH_LSH_THRESHOLD, num_perm=MINHASH_NUM_PERM)
            for doc in other_docs:
                other_id = doc["submission_record_id"]
                other_chunks = doc.get("similarity_chunks", {})
                other_sigs = other_chunks.get("minhash_signatures", {})
                if chunk_type not in other_sigs:
                    continue
                try:
                    other_mh = MinHash(num_perm=MINHASH_NUM_PERM)
                    other_mh.hashvalues[:] = other_sigs[chunk_type]
                    lsh.insert(str(other_id), other_mh)
                except Exception:
                    pass

            try:
                candidates = lsh.query(current_mh)
            except Exception as exc:
                current_app.logger.warning(
                    f"run_similarity_check: LSH query failed for chunk '{chunk_type}' "
                    f"of record #{record_id}: {exc}"
                )
                continue

            if not candidates:
                continue

            # Re-rank candidates with cosine similarity
            doc_map = {str(d["submission_record_id"]): d for d in other_docs}
            for candidate_key in candidates:
                other_id = int(candidate_key)
                other_doc = doc_map.get(candidate_key)
                if other_doc is None:
                    continue

                # Jaccard via MinHash
                other_sigs_map = other_doc.get("similarity_chunks", {}).get("minhash_signatures", {})
                if chunk_type not in other_sigs_map:
                    continue
                other_mh = MinHash(num_perm=MINHASH_NUM_PERM)
                other_mh.hashvalues[:] = other_sigs_map[chunk_type]
                jaccard = float(current_mh.jaccard(other_mh))
                if jaccard < MINHASH_LSH_THRESHOLD:
                    continue

                # Cosine similarity
                other_sections = other_doc.get("similarity_chunks", {}).get("sections", {})
                other_text = other_sections.get(chunk_type, {}).get("text", "")
                if not other_text:
                    continue

                try:
                    embeddings = st_model.encode([current_text, other_text], convert_to_tensor=True)
                    from sentence_transformers import util as st_util

                    cosine = float(st_util.cos_sim(embeddings[0], embeddings[1]))
                except Exception as exc:
                    current_app.logger.warning(
                        f"run_similarity_check: cosine similarity failed for records "
                        f"#{record_id}/#{other_id} chunk '{chunk_type}': {exc}"
                    )
                    continue

                threshold = CHUNK_SIMILARITY_THRESHOLD.get(chunk_type, 0.80)
                if cosine >= threshold:
                    a_id = min(record_id, other_id)
                    b_id = max(record_id, other_id)
                    concerns_to_upsert.append(
                        {
                            "record_a_id": a_id,
                            "record_b_id": b_id,
                            "chunk_type": chunk_type,
                            "minhash_jaccard": jaccard,
                            "transformer_cosine": cosine,
                        }
                    )

        # ------------------------------------------------------------------
        # Persist concerns
        # ------------------------------------------------------------------
        try:
            concerned_record_ids: set[int] = set()

            for concern_data in concerns_to_upsert:
                from datetime import datetime

                stmt = (
                    mysql_insert(SimilarityConcern.__table__)
                    .values(
                        record_a_id=concern_data["record_a_id"],
                        record_b_id=concern_data["record_b_id"],
                        chunk_type=concern_data["chunk_type"],
                        minhash_jaccard=concern_data["minhash_jaccard"],
                        transformer_cosine=concern_data["transformer_cosine"],
                        created_at=datetime.now(),
                        reviewed=False,
                    )
                    .on_duplicate_key_update(
                        minhash_jaccard=concern_data["minhash_jaccard"],
                        transformer_cosine=concern_data["transformer_cosine"],
                        created_at=datetime.now(),
                    )
                )
                db.session.execute(stmt)
                concerned_record_ids.add(concern_data["record_a_id"])
                concerned_record_ids.add(concern_data["record_b_id"])

            # Update risk factors on all concerned records
            for rid in concerned_record_ids:
                rec = db.session.get(SubmissionRecord, rid)
                if rec is None:
                    continue
                config = rec.owner.config if rec.owner else None
                rec.compute_risk_factors(config)

            db.session.commit()

            if concerns_to_upsert:
                current_app.logger.info(
                    f"run_similarity_check: upserted {len(concerns_to_upsert)} concern(s) "
                    f"for SubmissionRecord #{record_id}"
                )
            else:
                current_app.logger.info(
                    f"run_similarity_check: no similarity concerns for SubmissionRecord #{record_id}"
                )

        except SQLAlchemyError as exc:
            current_app.logger.warning(
                f"run_similarity_check: SQLAlchemyError for record #{record_id}: {exc}"
            )
            db.session.rollback()
            raise self.retry(exc=exc)

    # -----------------------------------------------------------------------
    # Internal coordinator callbacks
    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def _similarity_record_done(self, job_id: int, record_id: int):
        """Callback: remove record from inflight, increment completed, re-queue coordinator."""
        try:
            job: SimilarityOrchestrationJob = db.session.get(SimilarityOrchestrationJob, job_id)
            if job is None:
                return

            r = _get_redis()
            r.lrem(job.redis_inflight_key, 0, str(record_id).encode())
            job.increment_completed()

            queue_len = r.llen(job.redis_queue_key)
            inflight_len = r.llen(job.redis_inflight_key)

            if queue_len == 0 and inflight_len == 0:
                job.mark_complete()
                _cleanup_job_redis(job)
            else:
                similarity_rebuild_coordinator.apply_async(args=[job_id], queue="default")

            db.session.commit()

        except SQLAlchemyError as exc:
            db.session.rollback()
            raise self.retry(exc=exc)
        except Exception as exc:
            current_app.logger.warning(
                f"_similarity_record_done: unexpected error for job #{job_id} record #{record_id}: {exc}"
            )

    @celery.task(bind=True, default_retry_delay=30)
    def _similarity_record_error(self, job_id: int, record_id: int):
        """Callback: remove record from inflight, increment failed, re-queue coordinator."""
        try:
            job: SimilarityOrchestrationJob = db.session.get(SimilarityOrchestrationJob, job_id)
            if job is None:
                return

            r = _get_redis()
            r.lrem(job.redis_inflight_key, 0, str(record_id).encode())
            job.increment_failed()

            queue_len = r.llen(job.redis_queue_key)
            inflight_len = r.llen(job.redis_inflight_key)

            if queue_len == 0 and inflight_len == 0:
                job.mark_complete()
                _cleanup_job_redis(job)
            else:
                similarity_rebuild_coordinator.apply_async(args=[job_id], queue="default")

            db.session.commit()

        except SQLAlchemyError as exc:
            db.session.rollback()
            raise self.retry(exc=exc)
        except Exception as exc:
            current_app.logger.warning(
                f"_similarity_record_error: unexpected error for job #{job_id} record #{record_id}: {exc}"
            )

    # -----------------------------------------------------------------------
    # Task 4: similarity_rebuild_coordinator  (default queue)
    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def similarity_rebuild_coordinator(self, job_id: int):
        """
        Per-job coordinator for standalone similarity rebuild.

        Pops one record at a time from the Redis queue, dispatches the
        appropriate sub-chain, and re-queues itself when the chain completes.
        """
        try:
            job: SimilarityOrchestrationJob = db.session.get(SimilarityOrchestrationJob, job_id)
        except SQLAlchemyError as exc:
            raise self.retry(exc=exc)

        if job is None:
            current_app.logger.warning(
                f"similarity_rebuild_coordinator: SimilarityOrchestrationJob #{job_id} not found"
            )
            return

        if not job.is_active:
            return

        job.mark_started()
        try:
            db.session.commit()
        except SQLAlchemyError as exc:
            db.session.rollback()
            raise self.retry(exc=exc)

        try:
            r = _get_redis()
            raw = r.rpoplpush(job.redis_queue_key, job.redis_inflight_key)
        except Exception as exc:
            current_app.logger.warning(
                f"similarity_rebuild_coordinator: Redis error for job #{job_id}: {exc}"
            )
            return

        if raw is None:
            # Queue empty; check if any records still in-flight
            try:
                inflight_len = _get_redis().llen(job.redis_inflight_key)
            except Exception:
                inflight_len = 0

            if inflight_len == 0:
                try:
                    job.mark_complete()
                    _cleanup_job_redis(job)
                    db.session.commit()
                except SQLAlchemyError as exc:
                    db.session.rollback()
                    raise self.retry(exc=exc)
            return

        try:
            entry = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        except (json.JSONDecodeError, ValueError) as exc:
            current_app.logger.warning(
                f"similarity_rebuild_coordinator: malformed queue entry for job #{job_id}: {exc}"
            )
            return

        record_id: int = entry["record_id"]
        compute_only: bool = entry.get("compute_only", False)

        t_done = _similarity_record_done.si(job_id, record_id).set(queue="default")
        t_err = _similarity_record_error.si(job_id, record_id).set(queue="default")

        if compute_only:
            work = chain(
                compute_minhash.si(record_id).set(queue="default"),
                run_similarity_check.si(record_id).set(queue="default"),
                t_done,
            ).on_error(t_err)
        else:
            work = chain(
                extract_chunks.si(record_id).set(queue="llm_tasks"),
                compute_minhash.si(record_id).set(queue="default"),
                run_similarity_check.si(record_id).set(queue="default"),
                t_done,
            ).on_error(t_err)

        work.apply_async()

    # -----------------------------------------------------------------------
    # Task 5: launch_similarity_rebuild  (default queue)
    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def launch_similarity_rebuild(
        self,
        task_id: str,
        user_id: int,
        record_ids: list | None = None,
        scope: str = SimilarityOrchestrationJob.SCOPE_GLOBAL,
        scope_id: int | None = None,
    ):
        """
        Admin entry point for standalone similarity rebuild.

        Classifies each record's current chunk/signature state, creates a
        SimilarityOrchestrationJob, and dispatches the coordinator.
        """
        progress_update(task_id, TaskRecord.RUNNING, 5, "Initialising similarity rebuild…")

        try:
            user = db.session.get(User, user_id) if user_id else None
        except Exception:
            user = None

        try:
            if record_ids is None:
                records = (
                    db.session.query(SubmissionRecord)
                    .filter(SubmissionRecord.language_analysis_complete == True)  # noqa: E712
                    .all()
                )
                record_ids = [r.id for r in records]

            progress_update(task_id, TaskRecord.RUNNING, 10, f"Found {len(record_ids)} eligible records")

            # ------------------------------------------------------------------
            # Classify each record
            # ------------------------------------------------------------------
            queue_entries: list[dict] = []
            for rid in record_ids:
                chunks = get_similarity_chunks(rid)
                if chunks is None or chunks.get("chunk_prompt_version") != CHUNK_EXTRACTION_PROMPT_VERSION:
                    queue_entries.append({"record_id": rid, "compute_only": False})
                else:
                    queue_entries.append({"record_id": rid, "compute_only": True})

            if not queue_entries:
                progress_update(task_id, TaskRecord.SUCCESS, 100, "No records to process", autocommit=True)
                return

            # ------------------------------------------------------------------
            # Create SimilarityOrchestrationJob
            # ------------------------------------------------------------------
            job = SimilarityOrchestrationJob.build(
                scope=scope,
                scope_id=scope_id,
                total_count=len(queue_entries),
                rebuild_mode=True,
                owner=user,
                description=f"Similarity rebuild: {len(queue_entries)} records",
            )
            db.session.add(job)
            db.session.flush()

            # Push entries to Redis queue
            r = _get_redis()
            for entry in queue_entries:
                r.lpush(job.redis_queue_key, json.dumps(entry).encode())

            db.session.commit()

            # ------------------------------------------------------------------
            # Dispatch coordinator
            # ------------------------------------------------------------------
            similarity_rebuild_coordinator.apply_async(args=[job.id], queue="default")

            progress_update(
                task_id,
                TaskRecord.SUCCESS,
                100,
                f"Similarity rebuild job #{job.id} dispatched for {len(queue_entries)} records",
                autocommit=True,
            )

        except SQLAlchemyError as exc:
            current_app.logger.exception(f"launch_similarity_rebuild: SQLAlchemyError: {exc}")
            db.session.rollback()
            progress_update(task_id, TaskRecord.FAILURE, 100, f"Database error: {exc}", autocommit=True)
            raise self.retry(exc=exc)

        except Exception as exc:
            current_app.logger.exception(f"launch_similarity_rebuild: unexpected error: {exc}")
            progress_update(task_id, TaskRecord.FAILURE, 100, f"Unexpected error: {exc}", autocommit=True)

    return (
        extract_chunks,
        compute_minhash,
        run_similarity_check,
        similarity_rebuild_coordinator,
        launch_similarity_rebuild,
    )
