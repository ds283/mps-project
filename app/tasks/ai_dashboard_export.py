#
# Created by David Seery on 07/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery tasks to export AI dashboard data to Excel or CSV.

Each task receives:
  - user_id         : int  — user to notify and attach the download to
  - record_ids      : list[int] — SubmissionRecord PKs to include
  - filename_stem   : str  — base filename without extension
  - description     : str  — human-readable description for the Download Centre item

The task builds a flat table, uploads the file to MinIO, creates a
GeneratedAsset + DownloadCentreItem, and posts an in-app notification.

---------------------------------------------------------------------------
Exported columns
---------------------------------------------------------------------------

Identifiers and context
  Record ID             — SubmissionRecord primary key.
  Academic Year         — Academic year of the submission (e.g. "2025/2026"),
                          derived from the ProjectClassConfig year field.
  Project Class         — Abbreviation of the project class (e.g. "MPhys"),
                          derived from ProjectClass.abbreviation.
  Submission Period     — Human-readable submission period name.
  Analysis Complete     — Boolean: True when the language analysis pipeline
                          has finished for this record.

Lexical diversity metrics
  These are computed from the body text of the submitted PDF/Word document,
  after stripping bibliographies, appendices, equations, and code blocks.

  MATTR               — Moving-Average Type-Token Ratio (window 100 tokens).
                        Measures lexical diversity: lower values may indicate
                        repetitive phrasing characteristic of LLM output.
  MTLD                — Measure of Textual Lexical Diversity (threshold 0.72).
                        Higher values indicate greater vocabulary richness.
  Burstiness R        — Goh-Barabási burstiness parameter for a set of
                        AI-tendency indicator words (e.g. "suggest", "indicate",
                        "significant"). B > 0 means the words cluster; B < 0
                        means they are evenly spaced. Human writing tends to
                        produce moderate clustering; AI output can be unusually
                        uniform (negative B) or unusually clustered.
  CV                  — Coefficient of variation (σ/μ) of sentence lengths.
                        Low CV means unnaturally uniform sentence lengths,
                        which can be a signal of AI-generated text.

LLM-derived statistics
  These require a successful LLM analysis pass and are None when the LLM
  pipeline was skipped or fewer than two text chunks were processed.

  Mean NLL            — Mean negative log-likelihood (NLL) of the document
                        text under the LLM, averaged over processing chunks.
                        Lower NLL means the model finds the text highly
                        probable, which can indicate AI authorship. Currently
                        None in all records because Ollama does not yet expose
                        logprob computation; the column is reserved for when
                        that capability becomes available.
  NLL CV              — Coefficient of variation of per-chunk NLL values.
                        Informational only; not used as a Mahalanobis feature.
                        None when fewer than two chunks were processed.

Document properties
  Pages               — Number of pages in the uploaded PDF (0 for Word docs).
  Words               — Word count of the main body text (captions excluded).
  References          — Number of entries detected in the reference list.

Classification flags
  Individual threshold tests. Each flag value is a string ("low", "medium",
  or "high") indicating the degree of anomaly detected.

  MATTR Flag          — Concern level for the MATTR score.
  MTLD Flag           — Concern level for the MTLD score.
  Burstiness Flag     — Concern level for the burstiness R score.
  CV Flag             — Concern level for the sentence-length CV score.
  AI Concern          — Overall AI concern level: "low", "medium", "high",
                        or "uncalibrated" (when no calibration data exists).
                        Determined by Mahalanobis distance tests; see below.

Mahalanobis distance statistics
  The AI concern level is determined by multivariate Mahalanobis distance
  tests against population calibration data (TenantAICalibration). Two
  feature sets are supported:

    lexical (3-D) — (MATTR, MTLD, sentence CV)
    full    (4-D) — (MATTR, MTLD, sentence CV, mean NLL)

  Each calibration object is tested independently and a Bonferroni correction
  is applied across all K calibrations evaluated. The concern is "high" if any
  single test exceeds its corrected threshold; "medium" if any exceeds the
  medium threshold; "low" otherwise.

  Mahalanobis σ (best)    — Sigma (standard deviations from the calibration
                            centroid) from the most statistically significant
                            calibration test (lowest p-value).
  Mahalanobis p (best)    — Corresponding p-value.
  Mahalanobis σ (lexical) — Sigma from the 3-D lexical calibration, if one
                            was evaluated. Empty when no lexical calibration
                            is configured or applicable metrics are missing.
  Mahalanobis p (lexical) — p-value from the lexical calibration.
  Mahalanobis σ (full)    — Sigma from the 4-D full calibration, if one was
                            evaluated. Requires Mean NLL to be non-None and
                            the LLM model/context window to match the
                            calibration record.
  Mahalanobis p (full)    — p-value from the full calibration.
  Bonferroni K            — Number of calibrations actually evaluated (K).
                            The alpha thresholds below are divided by K to
                            control the family-wise error rate.
  Bonferroni α (medium)   — Corrected significance threshold for the "medium"
                            concern level: 0.05 / K.
  Bonferroni α (high)     — Corrected significance threshold for the "high"
                            concern level: 0.01 / K.

Risk flags
  Risk Flags (active)  — Semicolon-separated list of active (present and not
                         yet resolved) risk factor keys for this submission.
                         Known keys: RISK_TURNITIN, RISK_AI_COMPLIANCE,
                         RISK_AI_USE, RISK_DOCUMENT_LENGTH,
                         RISK_WORD_COUNT_DISCREPANCY. Empty when no active
                         risk factors are present.

Assessment grades
  Supervision Grade (%)  — Numeric supervision mark, as a percentage.
  Report Grade (%)       — Numeric report mark, as a percentage.
  Presentation Grade (%) — Numeric presentation mark, as a percentage.

LLM results and provenance
  Stated Word Count    — Word count stated by the student in the document
                         (e.g. near a "Word count:" label), extracted by the
                         LLM metadata pass. None if not found.
  LLM Grade Band       — Recommended grade band produced by the LLM assessment
                         pass (e.g. "1st class", "2.1 class"). Empty if the
                         LLM analysis failed or was skipped.
  LLM Model            — Identifier of the LLM model used for analysis
                         (e.g. "llama3.1:70b"). Empty if LLM analysis was not
                         run. Mean NLL and Mahalanobis σ (full) values are
                         only comparable between records that used the same
                         model and context window.
  LLM Context Window   — Token context window size used for LLM analysis.
                         Together with LLM Model, identifies which NLL values
                         can be validly compared across submissions.
  LLM Analysis Failed  — Boolean: True when the LLM assessment pass failed
                         (inference error or JSON parse failure after retries).
  LLM Feedback Failed  — Boolean: True when all LLM feedback chunks failed;
                         False when at least one chunk succeeded; None when
                         the feedback pass was not attempted.

Derived quantities
  Report Grade Band    — UK degree classification band derived from the
                         numeric report grade: "1st class" (≥70%), "2.1 class"
                         (≥60%), "2.2 class" (≥50%), "3rd class" (≥40%),
                         "Fail" (<40%). Empty when no report grade is recorded.
"""

from datetime import datetime, timedelta
from io import BytesIO
from typing import List, Optional

from flask import current_app, render_template_string
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    DownloadCentreItem,
    GeneratedAsset,
    SubmissionRecord,
    User,
)
from ..shared.asset_tools import AssetUploadManager
from ..shared.excel import _normalize_excel_sheet_name
from ..shared.scratch import ScratchFileManager
from .thumbnails import dispatch_thumbnail_task

# ---------------------------------------------------------------------------
# Column definitions for the exported table
# ---------------------------------------------------------------------------

_COLUMNS = [
    "Record ID",
    "Academic Year",
    "Project Class",
    "Submission Period",
    "Analysis Complete",
    "MATTR",
    "MTLD",
    "Burstiness R",
    "CV",
    "Mean NLL",
    "NLL CV",
    "Pages",
    "Words",
    "References",
    "MATTR Flag",
    "MTLD Flag",
    "Burstiness Flag",
    "CV Flag",
    "AI Concern",
    "Mahalanobis σ (best)",
    "Mahalanobis p (best)",
    "Mahalanobis σ (lexical)",
    "Mahalanobis p (lexical)",
    "Mahalanobis σ (full)",
    "Mahalanobis p (full)",
    "Bonferroni K",
    "Bonferroni α (medium)",
    "Bonferroni α (high)",
    "Risk Flags (active)",
    "Supervision Grade (%)",
    "Report Grade (%)",
    "Presentation Grade (%)",
    "Stated Word Count",
    "LLM Grade Band",
    "LLM Model",
    "LLM Context Window",
    "LLM Analysis Failed",
    "LLM Feedback Failed",
    "Report Grade Band",
]

# ---------------------------------------------------------------------------
# Notification template
# ---------------------------------------------------------------------------

_EXPORT_READY_TMPL = """
<div><strong>Your AI dashboard export is now available.</strong></div>
<div class="mt-2">You can find it in your
<a href="{{ url_for('home.download_centre') }}">Download Centre</a>.</div>
"""


# ---------------------------------------------------------------------------
# Row builder
# ---------------------------------------------------------------------------


def _grade_band(grade) -> str:
    """Map a numeric report grade to a UK degree classification band."""
    if grade is None:
        return ""
    try:
        g = float(grade)
    except (TypeError, ValueError):
        return ""
    if g >= 70:
        return "1st class"
    if g >= 60:
        return "2.1 class"
    if g >= 50:
        return "2.2 class"
    if g >= 40:
        return "3rd class"
    return "Fail"


def _build_row(record: SubmissionRecord) -> dict:
    """Extract a flat dict of export fields from one SubmissionRecord."""
    period = record.period
    config = period.config if period else None
    pclass = config.project_class if config else None

    year = config.year if config else None
    pclass_name = pclass.abbreviation if pclass else ""
    period_name = period.display_name if period else ""

    la = record.language_analysis_data
    metrics = la.get("metrics", {})
    flags = la.get("flags", {})
    llm_result = la.get("llm_result", {})

    def _float(val):
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    # Active (present and unresolved) risk factor keys
    active_rf = []
    rf_data = record.risk_factors_data
    for key, factor in rf_data.items():
        if factor.get("present", False) and not factor.get("resolved", False):
            active_rf.append(key)

    # Per-calibration Mahalanobis results (lexical = 3-D, full = 4-D)
    cal_results = flags.get("calibration_results", [])
    lexical_cal = next((c for c in cal_results if c.get("feature_set") == "lexical"), None)
    full_cal = next((c for c in cal_results if c.get("feature_set") == "full"), None)

    return {
        "Record ID": record.id,
        "Academic Year": f"{year}/{year + 1}" if year is not None else "",
        "Project Class": pclass_name,
        "Submission Period": period_name,
        "Analysis Complete": record.language_analysis_complete,
        "MATTR": _float(metrics.get("mattr")),
        "MTLD": _float(metrics.get("mtld")),
        "Burstiness R": _float(metrics.get("burstiness")),
        "CV": _float(metrics.get("sentence_cv")),
        "Mean NLL": _float(metrics.get("mean_nll")),
        "NLL CV": _float(metrics.get("nll_cv")),
        "Pages": _float(la.get("_page_count")),
        "Words": _float(metrics.get("word_count")),
        "References": _float(metrics.get("reference_count")),
        "MATTR Flag": flags.get("mattr_flag", ""),
        "MTLD Flag": flags.get("mtld_flag", ""),
        "Burstiness Flag": flags.get("burstiness_flag", ""),
        "CV Flag": flags.get("sentence_cv_flag", ""),
        "AI Concern": flags.get("ai_concern", ""),
        "Mahalanobis σ (best)": _float(flags.get("mahalanobis_sigma")),
        "Mahalanobis p (best)": _float(flags.get("mahalanobis_pvalue")),
        "Mahalanobis σ (lexical)": _float(lexical_cal["sigma"]) if lexical_cal else None,
        "Mahalanobis p (lexical)": _float(lexical_cal["p_value"]) if lexical_cal else None,
        "Mahalanobis σ (full)": _float(full_cal["sigma"]) if full_cal else None,
        "Mahalanobis p (full)": _float(full_cal["p_value"]) if full_cal else None,
        "Bonferroni K": flags.get("bonferroni_k"),
        "Bonferroni α (medium)": _float(flags.get("bonferroni_alpha_medium")),
        "Bonferroni α (high)": _float(flags.get("bonferroni_alpha_high")),
        "Risk Flags (active)": "; ".join(active_rf) if active_rf else "",
        "Supervision Grade (%)": _float(record.supervision_grade),
        "Report Grade (%)": _float(record.report_grade),
        "Presentation Grade (%)": _float(record.presentation_grade),
        "Stated Word Count": llm_result.get("stated_word_count"),
        "LLM Grade Band": llm_result.get("classification", ""),
        "LLM Model": record.llm_model_name or "",
        "LLM Context Window": record.llm_context_size,
        "LLM Analysis Failed": record.llm_analysis_failed,
        "LLM Feedback Failed": record.llm_feedback_failed,
        "Report Grade Band": _grade_band(record.report_grade),
    }


def _load_and_build_rows(record_ids: List[int]) -> List[dict]:
    """Load SubmissionRecords in batches and build the export row list."""
    rows = []
    # Load in chunks to avoid very large IN clauses
    chunk_size = 200
    for start in range(0, len(record_ids), chunk_size):
        chunk = record_ids[start : start + chunk_size]
        records = (
            db.session.query(SubmissionRecord)
            .filter(SubmissionRecord.id.in_(chunk))
            .all()
        )
        # Preserve the order given by record_ids (stable for reproducible exports)
        id_to_rec = {r.id: r for r in records}
        for rid in chunk:
            rec = id_to_rec.get(rid)
            if rec is not None:
                rows.append(_build_row(rec))
    return rows


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def register_ai_dashboard_export_tasks(celery):

    # ------------------------------------------------------------------
    # Excel export
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def export_ai_dashboard_xlsx(
        self,
        user_id: int,
        record_ids: List[int],
        filename_stem: str,
        description: str,
    ):
        """
        Export AI dashboard data for the given SubmissionRecord IDs to an
        Excel workbook, upload it to MinIO, and notify the requesting user.
        """
        self.update_state(state="STARTED", meta={"msg": "Loading records"})

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                raise Exception(f"User #{user_id} not found")
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading user in export_ai_dashboard_xlsx", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Building export data"})

        try:
            rows = _load_and_build_rows(record_ids)
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError building rows in export_ai_dashboard_xlsx", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Writing Excel workbook"})

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        try:
            import pandas as pd

            df = pd.DataFrame(rows, columns=_COLUMNS)
            stem_ts = f"{filename_stem}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".xlsx") as mgr:
                df.to_excel(
                    mgr.path,
                    sheet_name=_normalize_excel_sheet_name("AI Dashboard"),
                    index=False,
                )

                asset = GeneratedAsset(
                    timestamp=now,
                    expiry=expiry,
                    target_name=stem_ts,
                    parent_asset_id=None,
                    license_id=None,
                )
                size = mgr.path.stat().st_size
                with open(mgr.path, "rb") as fh:
                    with AssetUploadManager(
                        asset,
                        data=BytesIO(fh.read()),
                        storage=object_store,
                        audit_data="ai_dashboard_export.export_ai_dashboard_xlsx",
                        length=size,
                        mimetype=(
                            "application/vnd.openxmlformats-officedocument"
                            ".spreadsheetml.sheet"
                        ),
                    ):
                        pass

                asset.grant_user(user)
                db.session.add(asset)
                db.session.flush()

                dispatch_thumbnail_task(asset)

                download_item = DownloadCentreItem._build(
                    asset=asset,
                    user=user,
                    description=description,
                )
                db.session.add(download_item)

            message = render_template_string(_EXPORT_READY_TMPL)
            user.post_message(message, "success", autocommit=False)
            db.session.commit()

        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in export_ai_dashboard_xlsx", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    @celery.task(bind=True, default_retry_delay=30)
    def export_ai_dashboard_csv(
        self,
        user_id: int,
        record_ids: List[int],
        filename_stem: str,
        description: str,
    ):
        """
        Export AI dashboard data for the given SubmissionRecord IDs to a CSV
        file, upload it to MinIO, and notify the requesting user.
        """
        self.update_state(state="STARTED", meta={"msg": "Loading records"})

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                raise Exception(f"User #{user_id} not found")
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading user in export_ai_dashboard_csv", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Building export data"})

        try:
            rows = _load_and_build_rows(record_ids)
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError building rows in export_ai_dashboard_csv", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": "Writing CSV file"})

        now = datetime.now()
        expiry = now + timedelta(weeks=4)
        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

        try:
            import pandas as pd

            df = pd.DataFrame(rows, columns=_COLUMNS)
            stem_ts = f"{filename_stem}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".csv") as mgr:
                df.to_csv(mgr.path, index=False)

                asset = GeneratedAsset(
                    timestamp=now,
                    expiry=expiry,
                    target_name=stem_ts,
                    parent_asset_id=None,
                    license_id=None,
                )
                size = mgr.path.stat().st_size
                with open(mgr.path, "rb") as fh:
                    with AssetUploadManager(
                        asset,
                        data=BytesIO(fh.read()),
                        storage=object_store,
                        audit_data="ai_dashboard_export.export_ai_dashboard_csv",
                        length=size,
                        mimetype="text/csv",
                    ):
                        pass

                asset.grant_user(user)
                db.session.add(asset)
                db.session.flush()

                dispatch_thumbnail_task(asset)

                download_item = DownloadCentreItem._build(
                    asset=asset,
                    user=user,
                    description=description,
                )
                db.session.add(download_item)

            message = render_template_string(_EXPORT_READY_TMPL)
            user.post_message(message, "success", autocommit=False)
            db.session.commit()

        except SQLAlchemyError as exc:
            db.session.rollback()
            current_app.logger.exception(
                "SQLAlchemyError in export_ai_dashboard_csv", exc_info=exc
            )
            raise self.retry()

        self.update_state(state="SUCCESS", meta={"msg": "Export complete"})

    return export_ai_dashboard_xlsx, export_ai_dashboard_csv
