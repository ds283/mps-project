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
    store_embeddings,
    store_minhash_signatures,
    store_similarity_chunks,
)
from ..shared.text_utils import (
    _detect_top_level_sections,
    _split_document,
    _strip_code_blocks,
    _strip_math_lines,
)
from .pipeline_tracking import get_pipeline_redis, record_step_end, record_step_start

# ---------------------------------------------------------------------------
# Pipeline constants
# ---------------------------------------------------------------------------

CHUNK_EXTRACTION_PROMPT_VERSION = 4

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

MINHASH_JACCARD_CONCERN_THRESHOLD = 0.05
MIN_CHUNK_WORDS = 20
MINHASH_NUM_PERM = 128

ST_MODEL_CONFIG_KEY = "SIMILARITY_ST_MODEL"
ST_MODEL_DEFAULT = "all-mpnet-base-v2"

_CHUNK_EXTRACTION_CTX_KEY = "OLLAMA_CHUNK_EXTRACTION_CONTEXT_SIZE"
_CHUNK_EXTRACTION_CTX_DEFAULT = 18432

# ---------------------------------------------------------------------------
# Sentence-transformers model loader — cached per model name
# ---------------------------------------------------------------------------

_st_models: dict = {}


def _get_st_model():
    """Return (model, model_name) for the currently configured ST model."""
    model_name = current_app.config.get(ST_MODEL_CONFIG_KEY, ST_MODEL_DEFAULT)
    if model_name not in _st_models:
        from sentence_transformers import SentenceTransformer

        _st_models[model_name] = SentenceTransformer(model_name)
    return _st_models[model_name], model_name


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
        # Idempotency check — skip if chunks are already present at the
        # current prompt version.  Bumping CHUNK_EXTRACTION_PROMPT_VERSION
        # is the mechanism to force re-extraction across all records.
        # ------------------------------------------------------------------
        if record.chunks_present and record.chunks_prompt_version == CHUNK_EXTRACTION_PROMPT_VERSION:
            current_app.logger.info(
                f"extract_chunks: SubmissionRecord #{record_id} already has current chunk extraction — skipping"
            )
            record_step_end(_r, record_id, "extract_chunks", _t0)
            return

        # Version-bump cascade: when the prompt version has changed and old chunks
        # exist at a different version, delete unreviewed SimilarityConcern rows and
        # reset similarity_complete so the similarity scan re-runs against fresh chunks.
        if record.chunks_present and record.chunks_prompt_version != CHUNK_EXTRACTION_PROMPT_VERSION:
            current_app.logger.info(
                f"extract_chunks: SubmissionRecord #{record_id} chunk version mismatch "
                f"(stored={record.chunks_prompt_version}, current={CHUNK_EXTRACTION_PROMPT_VERSION}) "
                f"— clearing stale similarity data before re-extraction"
            )
            try:
                db.session.query(SimilarityConcern).filter(
                    db.or_(
                        SimilarityConcern.record_a_id == record_id,
                        SimilarityConcern.record_b_id == record_id,
                    ),
                    SimilarityConcern.reviewed == False,  # noqa: E712
                ).delete(synchronize_session=False)
                record.similarity_complete = False
                record.chunks_present = False
                record.chunks_prompt_version = None
                db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.warning(
                    f"extract_chunks: could not clear stale similarity data for "
                    f"record #{record_id}: {exc}"
                )

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
        clean_core = _strip_code_blocks(clean_core)
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
            try:
                record = db.session.get(SubmissionRecord, record_id)
                if record is not None:
                    record.chunks_present = True
                    record.chunks_prompt_version = CHUNK_EXTRACTION_PROMPT_VERSION
                    db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.warning(
                    f"extract_chunks: could not set chunks_present for record #{record_id}: {exc}"
                )
            record_step_end(_r, record_id, "extract_chunks", _t0)
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
            parsed_result, _accumulated, last_exc, _est_tok, _ = _call_llm(
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
                f"extract_chunks: LLM classification failed for SubmissionRecord #{record_id}"
            )
            try:
                rec = db.session.get(SubmissionRecord, record_id)
                if rec is not None:
                    rec.llm_chunking_failed = True
                    rec.llm_chunking_failure_reason = "LLM heading classification returned no result"
                    rec.chunks_present = False
                    rec.chunks_prompt_version = None
                    db.session.commit()
            except SQLAlchemyError as exc:
                db.session.rollback()
                current_app.logger.warning(
                    f"extract_chunks: could not set llm_chunking_failed for record #{record_id}: {exc}"
                )
            record_step_end(_r, record_id, "extract_chunks", _t0, error="LLM heading classification returned no result")
            return

        # ------------------------------------------------------------------
        # Phase 3 — CPU merge
        # ------------------------------------------------------------------
        chunk_texts: dict[str, list[str]] = {ct: [] for ct in CHUNK_TYPES}
        for section in top_level_sections:
            heading = section["heading"]
            assigned_type = parsed_result.get(heading)
            if assigned_type and assigned_type in CHUNK_TYPES:
                if len(section["full_text"].split()) < MIN_CHUNK_WORDS:
                    current_app.logger.debug(
                        f"extract_chunks: section '{heading}' for record #{record_id} "
                        f"has fewer than {MIN_CHUNK_WORDS} words — treating as absent"
                    )
                    continue
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
                record.chunks_present = True
                record.chunks_prompt_version = CHUNK_EXTRACTION_PROMPT_VERSION
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

        Compute datasketch MinHash signatures and sentence-transformer embeddings
        for each present chunk type, storing both in MongoDB.

        MinHash and embedding steps are independently idempotent: each checks its
        own freshness guard so only the stale one is recomputed.
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

        extracted_at = chunks.get("extracted_at")

        # ------------------------------------------------------------------
        # MinHash signatures — skip if already current
        # ------------------------------------------------------------------
        minhash_current = (
            chunks.get("minhash_signatures")
            and chunks.get("minhash_computed_at")
            and extracted_at
            and chunks["minhash_computed_at"] >= extracted_at
        )

        if minhash_current:
            current_app.logger.info(
                f"compute_minhash: signatures already current for SubmissionRecord #{record_id} — skipping"
            )
        else:
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
                    if len(words) < MIN_CHUNK_WORDS:
                        current_app.logger.debug(
                            f"compute_minhash: chunk '{chunk_type}' for record #{record_id} "
                            f"has fewer than {MIN_CHUNK_WORDS} words — skipping MinHash"
                        )
                        continue
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

        # ------------------------------------------------------------------
        # Sentence-transformer embeddings — skip if already current for this model
        # ------------------------------------------------------------------
        st_model, model_name = _get_st_model()

        embedding_current = (
            chunks.get("embedding_vectors")
            and chunks.get("embedding_model") == model_name
            and chunks.get("embedding_computed_at")
            and extracted_at
            and chunks["embedding_computed_at"] >= extracted_at
        )

        if embedding_current:
            current_app.logger.info(
                f"compute_minhash: embeddings already current for SubmissionRecord #{record_id} "
                f"(model={model_name}) — skipping"
            )
        else:
            embedding_vectors: dict[str, list[float]] = {}

            for chunk_type in CHUNK_TYPES:
                section = sections.get(chunk_type, {})
                if not section.get("present", False):
                    continue
                text = section.get("text", "")
                if not text:
                    continue
                if len(text.split()) < MIN_CHUNK_WORDS:
                    current_app.logger.debug(
                        f"compute_minhash: chunk '{chunk_type}' for record #{record_id} "
                        f"has fewer than {MIN_CHUNK_WORDS} words — skipping embedding"
                    )
                    continue
                try:
                    vec = st_model.encode(text, convert_to_numpy=True)
                    embedding_vectors[chunk_type] = vec.tolist()
                except Exception as exc:
                    current_app.logger.warning(
                        f"compute_minhash: embedding failed for chunk '{chunk_type}' "
                        f"of record #{record_id}: {exc}"
                    )

            if embedding_vectors:
                store_embeddings(record_id, embedding_vectors, model_name)
                current_app.logger.info(
                    f"compute_minhash: stored embeddings for {list(embedding_vectors.keys())} "
                    f"of SubmissionRecord #{record_id} (model={model_name})"
                )
            else:
                current_app.logger.warning(
                    f"compute_minhash: no embeddings produced for SubmissionRecord #{record_id}"
                )

        record_step_end(_r, record_id, "compute_minhash", _t0)

    # -----------------------------------------------------------------------
    # Task 3: run_similarity_check  (default queue)
    # -----------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def run_similarity_check(self, record_id: int):
        """
        Phase 3/3 of similarity pipeline.

        Runs Jaccard (MinHash) and cosine (sentence-transformer) similarity
        independently against all same-tenant records.  A SimilarityConcern is
        created whenever either metric exceeds its threshold:
          - Jaccard >= MINHASH_JACCARD_CONCERN_THRESHOLD
          - cosine  >= CHUNK_SIMILARITY_THRESHOLD[chunk_type]
        """
        import numpy as np
        from datasketch import MinHash

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
        current_embeddings: dict[str, list[float]] = chunks.get("embedding_vectors") or {}
        current_embedding_model: str = chunks.get("embedding_model", "")

        # Resolve the active ST model name (used to match cached embeddings)
        _, active_model_name = _get_st_model()

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
        # Load other same-tenant records from MongoDB (signatures + embeddings)
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

        # ------------------------------------------------------------------
        # Build per-pair trigger flags across all chunk types
        # pair_key -> {"record_a_id", "record_b_id", "chunk_type",
        #              "minhash_jaccard", "transformer_cosine",
        #              "jaccard_triggered", "cosine_triggered", "embedding_model"}
        # ------------------------------------------------------------------
        pair_concerns: dict[tuple, dict] = {}

        for chunk_type in CHUNK_TYPES:
            current_section = current_sections.get(chunk_type, {})
            if not current_section.get("present", False):
                continue
            if len(current_section.get("text", "").split()) < MIN_CHUNK_WORDS:
                continue

            # ---- Jaccard phase: exact MinHash Jaccard for all other records ----
            if chunk_type in current_sigs:
                current_mh = MinHash(num_perm=MINHASH_NUM_PERM)
                current_mh.hashvalues[:] = current_sigs[chunk_type]

                for doc in other_docs:
                    other_id = doc["submission_record_id"]
                    other_sigs = doc.get("similarity_chunks", {}).get("minhash_signatures", {})
                    if chunk_type not in other_sigs:
                        continue
                    try:
                        other_mh = MinHash(num_perm=MINHASH_NUM_PERM)
                        other_mh.hashvalues[:] = other_sigs[chunk_type]
                        jaccard = float(current_mh.jaccard(other_mh))
                    except Exception as exc:
                        current_app.logger.debug(
                            f"run_similarity_check: Jaccard failed for records "
                            f"#{record_id}/#{other_id} chunk '{chunk_type}': {exc}"
                        )
                        continue

                    if jaccard < MINHASH_JACCARD_CONCERN_THRESHOLD:
                        continue

                    a_id, b_id = min(record_id, other_id), max(record_id, other_id)
                    key = (a_id, b_id, chunk_type)
                    entry = pair_concerns.setdefault(key, {
                        "record_a_id": a_id,
                        "record_b_id": b_id,
                        "chunk_type": chunk_type,
                        "minhash_jaccard": None,
                        "transformer_cosine": None,
                        "jaccard_triggered": False,
                        "cosine_triggered": False,
                        "embedding_model": None,
                    })
                    entry["minhash_jaccard"] = jaccard
                    entry["jaccard_triggered"] = True

            # ---- Cosine phase: batch similarity using cached embeddings ----
            current_emb_vec = current_embeddings.get(chunk_type)
            if current_emb_vec is None or current_embedding_model != active_model_name:
                if chunk_type in current_sigs:  # only warn when MinHash exists (chunk is present)
                    current_app.logger.debug(
                        f"run_similarity_check: no current-model embedding for chunk '{chunk_type}' "
                        f"of record #{record_id} — skipping cosine phase for this chunk"
                    )
                continue

            current_vec = np.array(current_emb_vec, dtype=np.float32)
            current_norm = np.linalg.norm(current_vec)
            if current_norm == 0:
                continue

            cosine_threshold = CHUNK_SIMILARITY_THRESHOLD.get(chunk_type, 0.80)

            # Collect other records that have a matching-model embedding for this chunk
            other_ids_with_emb: list[int] = []
            other_vecs: list[np.ndarray] = []

            for doc in other_docs:
                other_id = doc["submission_record_id"]
                sc = doc.get("similarity_chunks", {})
                if sc.get("embedding_model") != active_model_name:
                    continue
                other_emb = (sc.get("embedding_vectors") or {}).get(chunk_type)
                if other_emb is None:
                    continue
                other_text = (sc.get("sections") or {}).get(chunk_type, {}).get("text", "")
                if len(other_text.split()) < MIN_CHUNK_WORDS:
                    continue
                other_ids_with_emb.append(other_id)
                other_vecs.append(np.array(other_emb, dtype=np.float32))

            if not other_vecs:
                continue

            other_matrix = np.stack(other_vecs)  # (n, dim)
            other_norms = np.linalg.norm(other_matrix, axis=1)
            nonzero = other_norms != 0
            cosines = np.zeros(len(other_ids_with_emb), dtype=np.float32)
            cosines[nonzero] = (other_matrix[nonzero] @ current_vec) / (
                other_norms[nonzero] * current_norm
            )

            for i, other_id in enumerate(other_ids_with_emb):
                cosine = float(cosines[i])
                if cosine < cosine_threshold:
                    continue

                a_id, b_id = min(record_id, other_id), max(record_id, other_id)
                key = (a_id, b_id, chunk_type)

                # Also retrieve Jaccard if not already computed for this pair
                jaccard = None
                if key in pair_concerns:
                    jaccard = pair_concerns[key].get("minhash_jaccard")
                elif chunk_type in current_sigs:
                    # Compute Jaccard on demand for cosine-only pairs
                    doc_map = {d["submission_record_id"]: d for d in other_docs}
                    other_doc = doc_map.get(other_id)
                    if other_doc is not None:
                        other_sigs = other_doc.get("similarity_chunks", {}).get("minhash_signatures", {})
                        if chunk_type in other_sigs:
                            try:
                                current_mh = MinHash(num_perm=MINHASH_NUM_PERM)
                                current_mh.hashvalues[:] = current_sigs[chunk_type]
                                other_mh = MinHash(num_perm=MINHASH_NUM_PERM)
                                other_mh.hashvalues[:] = other_sigs[chunk_type]
                                jaccard = float(current_mh.jaccard(other_mh))
                            except Exception:
                                pass

                entry = pair_concerns.setdefault(key, {
                    "record_a_id": a_id,
                    "record_b_id": b_id,
                    "chunk_type": chunk_type,
                    "minhash_jaccard": None,
                    "transformer_cosine": None,
                    "jaccard_triggered": False,
                    "cosine_triggered": False,
                    "embedding_model": None,
                })
                if jaccard is not None:
                    entry["minhash_jaccard"] = jaccard
                entry["transformer_cosine"] = cosine
                entry["cosine_triggered"] = True
                entry["embedding_model"] = active_model_name

        concerns_to_upsert = list(pair_concerns.values())

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
                        jaccard_triggered=concern_data["jaccard_triggered"],
                        cosine_triggered=concern_data["cosine_triggered"],
                        embedding_model=concern_data["embedding_model"],
                        created_at=datetime.now(),
                        reviewed=False,
                    )
                    .on_duplicate_key_update(
                        minhash_jaccard=concern_data["minhash_jaccard"],
                        transformer_cosine=concern_data["transformer_cosine"],
                        jaccard_triggered=concern_data["jaccard_triggered"],
                        cosine_triggered=concern_data["cosine_triggered"],
                        embedding_model=concern_data["embedding_model"],
                        created_at=datetime.now(),
                    )
                )
                db.session.execute(stmt)
                other_id = (
                    concern_data["record_b_id"]
                    if concern_data["record_a_id"] == record_id
                    else concern_data["record_a_id"]
                )
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
