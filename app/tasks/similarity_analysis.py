#
# Created by David Seery on 07/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from flask import current_app
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    ProjectClass,
    ProjectClassConfig,
    SimilarityConcern,
    SubmissionPeriodRecord,
    SubmissionRecord,
)
from ..shared.llm_services import _call_llm
from ..shared.scraped_text_store import (
    get_scraped_text,
    get_similarity_chunks,
    store_minhash_signatures,
    store_similarity_chunks,
)
from ..shared.text_utils import _detect_top_level_sections, _split_document, _strip_math_lines
from .pipeline_tracking import get_pipeline_redis, record_step_end, record_step_start

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

        _r = None
        try:
            _r = get_pipeline_redis()
        except Exception:
            pass
        _t0 = record_step_start(_r, record_id, "extract_chunks")

        # ------------------------------------------------------------------
        # Load record and guard on language analysis completion
        # ------------------------------------------------------------------
        try:
            record: SubmissionRecord = db.session.get(SubmissionRecord, record_id)
        except SQLAlchemyError as exc:
            record_step_end(_r, record_id, "extract_chunks", _t0, error=repr(exc))
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
        # Idempotency check — also detects document re-uploads by comparing
        # scraped_text.updated_at against similarity_chunks.extracted_at so
        # that a new upload forces re-extraction even when the prompt version
        # is unchanged.
        # ------------------------------------------------------------------
        scraped = get_scraped_text(record_id)
        existing = get_similarity_chunks(record_id)
        scraped_updated_at = scraped.get("updated_at") if scraped else None
        chunks_extracted_at = existing.get("extracted_at") if existing else None

        if (
            existing is not None
            and existing.get("chunk_prompt_version") == CHUNK_EXTRACTION_PROMPT_VERSION
            and scraped_updated_at is not None
            and chunks_extracted_at is not None
            and chunks_extracted_at >= scraped_updated_at
        ):
            current_app.logger.info(
                f"extract_chunks: SubmissionRecord #{record_id} already has current chunk extraction — skipping"
            )
            return

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
            try:
                rec = db.session.get(SubmissionRecord, record_id)
                if rec is not None:
                    rec.llm_chunking_failed = True
                    rec.llm_chunking_failure_reason = "LLM heading classification returned no result"
                    db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.warning(
                    f"extract_chunks: could not set llm_chunking_failed for record #{record_id}: {exc}"
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

        record_step_end(_r, record_id, "extract_chunks", _t0)

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

        _r = None
        try:
            _r = get_pipeline_redis()
        except Exception:
            pass
        _t0 = record_step_start(_r, record_id, "compute_minhash")

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

        record_step_end(_r, record_id, "compute_minhash", _t0)

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

        _r = None
        try:
            _r = get_pipeline_redis()
        except Exception:
            pass
        _t0 = record_step_start(_r, record_id, "run_similarity_check")

        chunks = get_similarity_chunks(record_id)
        if chunks is None or not chunks.get("minhash_signatures"):
            current_app.logger.warning(
                f"run_similarity_check: no minhash signatures for SubmissionRecord #{record_id} — skipping"
            )
            record_step_end(_r, record_id, "run_similarity_check", _t0,
                            error="No minhash signatures — skipped")
            return

        current_sections = chunks.get("sections", {})
        current_sigs: dict[str, list[int]] = chunks["minhash_signatures"]

        # ------------------------------------------------------------------
        # Determine this record's tenant so comparisons stay within-tenant
        # ------------------------------------------------------------------
        try:
            current_record = db.session.get(SubmissionRecord, record_id)
        except SQLAlchemyError as exc:
            current_app.logger.warning(
                f"run_similarity_check: SQLAlchemyError loading SubmissionRecord #{record_id}: {exc}"
            )
            return

        if current_record is None:
            current_app.logger.warning(
                f"run_similarity_check: SubmissionRecord #{record_id} not found — skipping"
            )
            return

        try:
            tenant_id: int = current_record.period.config.project_class.tenant_id
        except AttributeError:
            current_app.logger.warning(
                f"run_similarity_check: could not determine tenant for SubmissionRecord #{record_id} — skipping"
            )
            return

        # Collect all other record IDs in the same tenant from SQL
        try:
            same_tenant_rows = (
                db.session.query(SubmissionRecord.id)
                .join(SubmissionRecord.period)
                .join(SubmissionPeriodRecord.config)
                .join(ProjectClassConfig.project_class)
                .filter(ProjectClass.tenant_id == tenant_id)
                .filter(SubmissionRecord.id != record_id)
                .all()
            )
            same_tenant_ids = [row[0] for row in same_tenant_rows]
        except SQLAlchemyError as exc:
            current_app.logger.warning(
                f"run_similarity_check: SQLAlchemyError fetching tenant record IDs for #{record_id}: {exc}"
            )
            return

        if not same_tenant_ids:
            current_app.logger.info(
                f"run_similarity_check: no other records in same tenant — skipping for record #{record_id}"
            )
            return

        # ------------------------------------------------------------------
        # Query other same-tenant records with computed signatures from MongoDB
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
                    "submission_record_id": {"$in": same_tenant_ids},
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
        # Persist concerns: delete stale unreviewed rows first, then upsert
        # new ones.  Reviewed concerns are preserved unconditionally.
        # Both operations are in the same transaction so there is no window
        # where this record has no concerns between the two steps.
        # risk_factors for record_id itself are NOT updated here — finalize_risk_flags
        # at the chain tail handles that after this task returns.
        # ------------------------------------------------------------------
        try:
            db.session.query(SimilarityConcern).filter(
                db.or_(
                    SimilarityConcern.record_a_id == record_id,
                    SimilarityConcern.record_b_id == record_id,
                ),
                SimilarityConcern.reviewed == False,  # noqa: E712
            ).delete(synchronize_session="fetch")

            concerned_other_ids: set[int] = set()

            for concern_data in concerns_to_upsert:
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
                # Collect the OTHER record in each pair for risk-factor refresh
                other_id = concern_data["record_b_id"] if concern_data["record_a_id"] == record_id else concern_data["record_a_id"]
                concerned_other_ids.add(other_id)

            # Refresh risk factors on partner records only; record_id is handled
            # by finalize_risk_flags which runs after this task.
            for rid in concerned_other_ids:
                rec = db.session.get(SubmissionRecord, rid)
                if rec is None:
                    continue
                config = rec.period.config if rec.period else None
                rec.compute_risk_factors(config)

            current_record.similarity_complete = True
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
            record_step_end(_r, record_id, "run_similarity_check", _t0, error=repr(exc))
            raise self.retry(exc=exc)

        record_step_end(_r, record_id, "run_similarity_check", _t0)

    return (
        extract_chunks,
        compute_minhash,
        run_similarity_check,
    )
