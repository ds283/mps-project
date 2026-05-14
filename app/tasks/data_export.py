#
# Created by David Seery on 14/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Celery task to export anonymised tenant marking data to an Excel workbook.

The task export_tenant_marking_data_xlsx produces a two-sheet workbook:

  Sheet "submissions"         — one row per SubmissionRecord per MarkingEvent,
                                restricted to events that have been through
                                conflation (workflow_state >= READY_TO_GENERATE_FEEDBACK).
  Sheet "similarity_concerns" — one row per SimilarityConcern involving at
                                least one submission in the export.

All user-identity values use User.uuid (the stable anonymous UUID), never
integer PKs.  Submission identity uses a fresh per-run token (uuid4 hex) that
is stable within one export run but intentionally not stable across runs.
"""

import uuid
from datetime import datetime, timedelta
from io import BytesIO

from flask import current_app, render_template_string
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    DownloadCentreItem,
    GeneratedAsset,
    SimilarityConcern,
    TaskRecord,
    User,
)
from ..models.markingevent import (
    ConflationReport,
    MarkingEvent,
    MarkingEventWorkflowStates,
    MarkingWorkflow,
    SubmitterReport,
)
from ..models.project_class import ProjectClass, ProjectClassConfig, SubmissionPeriodRecord
from ..models.submissions import SubmissionRecord, SubmissionRoleTypesMixin
from ..shared.asset_tools import AssetUploadManager
from ..shared.scratch import ScratchFileManager
from ..task_queue import progress_update
from .thumbnails import dispatch_thumbnail_task

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

_SUBMISSIONS_COLUMNS = [
    "submission_token",
    "academic_year",
    "marking_event_name",
    "pclass_abbreviation",
    "has_report",
    "has_supervisor",
    "has_presentation",
    "grade_report",
    "grade_supervisor",
    "grade_presentation",
    "marker_a_uuid",
    "marker_a_grade",
    "marker_b_uuid",
    "marker_b_grade",
    "supervisor_marker_uuid",
    "supervisor_marker_grade",
    "report_moderation_triggered",
    "report_moderator_uuid",
    "report_moderator_grade",
    "presentation_assessor_a_uuid",
    "presentation_assessor_a_grade",
    "presentation_assessor_b_uuid",
    "presentation_assessor_b_grade",
    "presentation_moderation_triggered",
    "presentation_moderator_uuid",
    "presentation_moderator_grade",
    "convenor_intervention",
    "flag_turnitin",
    "flag_ai_compliance",
    "flag_ai_use",
    "flag_document_length",
    "flag_word_count_discrepancy",
    "turnitin_score",
    "turnitin_web_overlap",
    "turnitin_publication_overlap",
    "turnitin_student_overlap",
    "measured_word_count",
    "appendix_word_count",
    "reference_count",
    "mattr",
    "mtld",
    "burstiness",
    "sentence_cv",
    "mean_nll",
    "nll_cv",
    "stated_word_count",
    "genai_statement_found",
    "ai_concern",
    "mahalanobis_sigma",
    "mahalanobis_pvalue",
    "bonferroni_k",
    "bonferroni_alpha_medium",
    "bonferroni_alpha_high",
    "has_language_analysis",
    "has_turnitin",
]

_SIMILARITY_COLUMNS = [
    "concern_token",
    "submission_token_a",
    "submission_token_b",
    "academic_year_a",
    "academic_year_b",
    "year_gap",
    "pclass_abbreviation_a",
    "pclass_abbreviation_b",
    "chunk_type",
    "minhash_jaccard",
    "transformer_cosine",
    "jaccard_triggered",
    "cosine_triggered",
    "reviewed",
    "resolution",
]

# ---------------------------------------------------------------------------
# Notification template
# ---------------------------------------------------------------------------

_EXPORT_READY_TMPL = """
<div><strong>Your analytical marking data export is now available.</strong></div>
<div class="mt-2">You can find it in your
<a href="{{ url_for('home.download_centre') }}">Download Centre</a>.</div>
"""


# ---------------------------------------------------------------------------
# Helper: build per-event lookup tables
# ---------------------------------------------------------------------------


def _build_event_lookups(event: MarkingEvent) -> tuple[dict, dict, list, object, list]:
    """Build sr_lookup, mr_lookup, and classified workflow lists for one event.

    Returns:
        sr_lookup:          (workflow_id, record_id) -> SubmitterReport
        mr_lookup:          submitter_report_id -> [MarkingReport] sorted by id
        marker_wfs:         workflows with ROLE_MARKER
        supervisor_wf:      single workflow with ROLE_SUPERVISOR (or None)
        presentation_wfs:   workflows with ROLE_PRESENTATION_ASSESSOR
    """
    sr_lookup: dict[tuple[int, int], SubmitterReport] = {}
    mr_lookup: dict[int, list] = {}

    event_wfs = list(event.workflows)
    for wf in event_wfs:
        for sr in wf.submitter_reports:
            sr_lookup[(wf.id, sr.record_id)] = sr
            mr_lookup[sr.id] = sorted(sr.marking_reports.all(), key=lambda m: m.id)

    marker_wfs = [wf for wf in event_wfs if wf.role == SubmissionRoleTypesMixin.ROLE_MARKER]
    supervisor_wf = next(
        (wf for wf in event_wfs if wf.role == SubmissionRoleTypesMixin.ROLE_SUPERVISOR), None
    )
    presentation_wfs = [
        wf for wf in event_wfs if wf.role == SubmissionRoleTypesMixin.ROLE_PRESENTATION_ASSESSOR
    ]

    return sr_lookup, mr_lookup, marker_wfs, supervisor_wf, presentation_wfs


def _get_assessor_ab(wfs, record_id, sr_lookup, mr_lookup):
    """Collect all MarkingReports for a record across a list of same-role workflows.

    Returns (primary_sr, mr_a, mr_b) where primary_sr is the SubmitterReport from
    the first workflow that has one, and mr_a/mr_b are the first two MarkingReports
    sorted globally by id.
    """
    srs = [sr_lookup[(wf.id, record_id)] for wf in wfs if (wf.id, record_id) in sr_lookup]
    primary_sr = srs[0] if srs else None
    all_mrs = sorted([mr for sr in srs for mr in mr_lookup.get(sr.id, [])], key=lambda m: m.id)
    mr_a = all_mrs[0] if len(all_mrs) > 0 else None
    mr_b = all_mrs[1] if len(all_mrs) > 1 else None
    return primary_sr, mr_a, mr_b


# ---------------------------------------------------------------------------
# Row builders
# ---------------------------------------------------------------------------


def _build_submission_row(
    event: MarkingEvent,
    cr: ConflationReport,
    token_map: dict[int, str],
    sr_lookup: dict,
    mr_lookup: dict,
    marker_wfs: list,
    supervisor_wf,
    presentation_wfs: list,
) -> dict:
    record: SubmissionRecord = cr.submission_record
    rid = record.id

    targets = event.targets_as_dict
    conflation = cr.conflation_report_as_dict

    # --- ROLE_MARKER grades and moderation ---
    primary_marker_sr, mr_a, mr_b = _get_assessor_ab(marker_wfs, rid, sr_lookup, mr_lookup)

    marker_a_uuid = mr_a.role.user.uuid if mr_a else None
    marker_a_grade = mr_a.grade if mr_a else None
    marker_b_uuid = mr_b.role.user.uuid if mr_b else None
    marker_b_grade = mr_b.grade if mr_b else None

    report_moderation_triggered = primary_marker_sr.out_of_tolerance if primary_marker_sr else None
    report_moderator_uuid = (
        primary_marker_sr.moderator_accepted_by.user.uuid
        if primary_marker_sr and primary_marker_sr.moderator_accepted_by
        else None
    )
    report_moderator_grade = (
        primary_marker_sr.accepted_moderator_report.grade
        if primary_marker_sr and primary_marker_sr.accepted_moderator_report
        else None
    )

    # --- ROLE_SUPERVISOR grade and identity ---
    supervisor_sr = sr_lookup.get((supervisor_wf.id, rid)) if supervisor_wf else None
    supervisor_grade = supervisor_sr.grade if supervisor_sr else None

    sup_role = record.roles.filter_by(role=SubmissionRoleTypesMixin.ROLE_SUPERVISOR).first()
    supervisor_uuid = sup_role.user.uuid if sup_role else None

    # --- ROLE_PRESENTATION_ASSESSOR grades and moderation ---
    primary_presentation_sr, pa, pb = _get_assessor_ab(
        presentation_wfs, rid, sr_lookup, mr_lookup
    )

    pres_a_uuid = pa.role.user.uuid if pa else None
    pres_a_grade = pa.grade if pa else None
    pres_b_uuid = pb.role.user.uuid if pb else None
    pres_b_grade = pb.grade if pb else None

    pres_moderation_triggered = (
        primary_presentation_sr.out_of_tolerance if primary_presentation_sr else None
    )
    pres_moderator_uuid = (
        primary_presentation_sr.moderator_accepted_by.user.uuid
        if primary_presentation_sr and primary_presentation_sr.moderator_accepted_by
        else None
    )
    pres_moderator_grade = (
        primary_presentation_sr.accepted_moderator_report.grade
        if primary_presentation_sr and primary_presentation_sr.accepted_moderator_report
        else None
    )

    # --- convenor_intervention: True if any SubmitterReport for this record has it set ---
    all_srs = [v for (wf_id, rec_id), v in sr_lookup.items() if rec_id == rid]
    convenor_intervention = any(sr.convenor_intervention for sr in all_srs)

    # --- Risk flags ---
    rf = record.risk_factors_data
    flag_turnitin = rf.get("turnitin", {}).get("present", False)
    flag_ai_compliance = rf.get("ai_compliance", {}).get("present", False)
    flag_ai_use = rf.get("ai_use", {}).get("present", False)
    flag_document_length = rf.get("document_length", {}).get("present", False)
    flag_word_count_discrepancy = rf.get("word_count_discrepancy", {}).get("present", False)

    # --- Language analysis ---
    la = record.language_analysis_data
    metrics = la.get("metrics", {})
    flags = la.get("flags", {})
    llm_result = la.get("llm_result")

    stated_word_count = llm_result.get("stated_word_count") if llm_result is not None else None
    genai_statement_found = (
        llm_result.get("genai_statement_found") if llm_result is not None else None
    )

    # AI concern — lexical calibration only
    cal_results = flags.get("calibration_results", [])
    lexical_entry = next((e for e in cal_results if e.get("feature_set") == "lexical"), None)
    ai_concern = lexical_entry["concern"] if lexical_entry else None
    mahalanobis_sigma = lexical_entry["sigma"] if lexical_entry else None
    mahalanobis_pvalue = lexical_entry["p_value"] if lexical_entry else None

    return {
        "submission_token": token_map[rid],
        "academic_year": event.period.config.year,
        "marking_event_name": event.name,
        "pclass_abbreviation": event.pclass.abbreviation,
        "has_report": "report" in targets,
        "has_supervisor": "supervisor" in targets,
        "has_presentation": "presentation" in targets,
        "grade_report": conflation.get("report"),
        "grade_supervisor": conflation.get("supervisor"),
        "grade_presentation": conflation.get("presentation"),
        "marker_a_uuid": marker_a_uuid,
        "marker_a_grade": marker_a_grade,
        "marker_b_uuid": marker_b_uuid,
        "marker_b_grade": marker_b_grade,
        "supervisor_marker_uuid": supervisor_uuid,
        "supervisor_marker_grade": supervisor_grade,
        "report_moderation_triggered": report_moderation_triggered,
        "report_moderator_uuid": report_moderator_uuid,
        "report_moderator_grade": report_moderator_grade,
        "presentation_assessor_a_uuid": pres_a_uuid,
        "presentation_assessor_a_grade": pres_a_grade,
        "presentation_assessor_b_uuid": pres_b_uuid,
        "presentation_assessor_b_grade": pres_b_grade,
        "presentation_moderation_triggered": pres_moderation_triggered,
        "presentation_moderator_uuid": pres_moderator_uuid,
        "presentation_moderator_grade": pres_moderator_grade,
        "convenor_intervention": convenor_intervention,
        "flag_turnitin": flag_turnitin,
        "flag_ai_compliance": flag_ai_compliance,
        "flag_ai_use": flag_ai_use,
        "flag_document_length": flag_document_length,
        "flag_word_count_discrepancy": flag_word_count_discrepancy,
        "turnitin_score": record.turnitin_score,
        "turnitin_web_overlap": record.turnitin_web_overlap,
        "turnitin_publication_overlap": record.turnitin_publication_overlap,
        "turnitin_student_overlap": record.turnitin_student_overlap,
        "measured_word_count": metrics.get("word_count"),
        "appendix_word_count": metrics.get("appendix_word_count"),
        "reference_count": metrics.get("reference_count"),
        "mattr": metrics.get("mattr"),
        "mtld": metrics.get("mtld"),
        "burstiness": metrics.get("burstiness"),
        "sentence_cv": metrics.get("sentence_cv"),
        "mean_nll": metrics.get("mean_nll"),
        "nll_cv": metrics.get("nll_cv"),
        "stated_word_count": stated_word_count,
        "genai_statement_found": genai_statement_found,
        "ai_concern": ai_concern,
        "mahalanobis_sigma": mahalanobis_sigma,
        "mahalanobis_pvalue": mahalanobis_pvalue,
        "bonferroni_k": flags.get("bonferroni_k"),
        "bonferroni_alpha_medium": flags.get("bonferroni_alpha_medium"),
        "bonferroni_alpha_high": flags.get("bonferroni_alpha_high"),
        "has_language_analysis": record.language_analysis_complete,
        "has_turnitin": record.turnitin_score is not None,
    }


# ---------------------------------------------------------------------------
# Task registration
# ---------------------------------------------------------------------------


def register_data_export_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def export_tenant_marking_data_xlsx(self, task_id: str, tenant_id: int, user_id: int):
        """
        Export anonymised marking data for all MarkingEvents belonging to a tenant to
        an Excel workbook, upload it to MinIO, and notify the requesting user.

        Only MarkingEvents with workflow_state >= READY_TO_GENERATE_FEEDBACK are included,
        guaranteeing that ConflationReports exist for every included event.
        """
        progress_update(task_id, TaskRecord.RUNNING, 5, "Loading records...", autocommit=True)

        try:
            user: User = db.session.query(User).filter_by(id=user_id).first()
            if user is None:
                raise ValueError(f"User #{user_id} not found")

            events = (
                db.session.query(MarkingEvent)
                .join(SubmissionPeriodRecord, MarkingEvent.period_id == SubmissionPeriodRecord.id)
                .join(
                    ProjectClassConfig,
                    SubmissionPeriodRecord.config_id == ProjectClassConfig.id,
                )
                .join(ProjectClass, ProjectClassConfig.pclass_id == ProjectClass.id)
                .filter(
                    ProjectClass.tenant_id == tenant_id,
                    MarkingEvent.workflow_state
                    >= MarkingEventWorkflowStates.READY_TO_GENERATE_FEEDBACK,
                )
                .all()
            )
        except SQLAlchemyError as exc:
            current_app.logger.exception(
                "SQLAlchemyError loading records in export_tenant_marking_data_xlsx",
                exc_info=exc,
            )
            progress_update(
                task_id,
                TaskRecord.FAILURE,
                100,
                "Database error loading records.",
                autocommit=True,
            )
            raise self.retry()

        if user is None:
            progress_update(
                task_id, TaskRecord.FAILURE, 100, "User not found.", autocommit=True
            )
            return

        progress_update(
            task_id, TaskRecord.RUNNING, 15, "Building export data...", autocommit=True
        )

        try:
            import openpyxl

            n_events = len(events)

            # ----------------------------------------------------------------
            # Pass 1: build token map and collect submission rows
            # ----------------------------------------------------------------
            token_map: dict[int, str] = {}
            record_map: dict[int, SubmissionRecord] = {}
            submission_rows: list[dict] = []
            min_year: int | None = None
            max_year: int | None = None

            for i, event in enumerate(events):
                sr_lookup, mr_lookup, marker_wfs, supervisor_wf, presentation_wfs = (
                    _build_event_lookups(event)
                )

                year = event.period.config.year
                if year is not None:
                    if min_year is None or year < min_year:
                        min_year = year
                    if max_year is None or year > max_year:
                        max_year = year

                for cr in event.conflation_reports:
                    record = cr.submission_record
                    rid = record.id

                    if rid not in token_map:
                        token_map[rid] = uuid.uuid4().hex
                        record_map[rid] = record

                    row = _build_submission_row(
                        event,
                        cr,
                        token_map,
                        sr_lookup,
                        mr_lookup,
                        marker_wfs,
                        supervisor_wf,
                        presentation_wfs,
                    )
                    submission_rows.append(row)

                pct = 15 + 65 * (i + 1) / max(n_events, 1)
                progress_update(
                    task_id,
                    TaskRecord.RUNNING,
                    int(pct),
                    f"Processed event {i + 1} of {n_events}...",
                    autocommit=True,
                )

            # ----------------------------------------------------------------
            # Pass 2: collect similarity concerns touching any in-scope record
            # ----------------------------------------------------------------
            similarity_rows: list[dict] = []
            if token_map:
                record_ids = list(token_map.keys())
                all_concerns = (
                    db.session.query(SimilarityConcern)
                    .filter(
                        db.or_(
                            SimilarityConcern.record_a_id.in_(record_ids),
                            SimilarityConcern.record_b_id.in_(record_ids),
                        )
                    )
                    .all()
                )

                seen_ids: set[int] = set()
                for concern in all_concerns:
                    if concern.id in seen_ids:
                        continue
                    seen_ids.add(concern.id)

                    try:
                        year_a = concern.record_a.period.config.year
                        year_b = concern.record_b.period.config.year
                        pclass_a = concern.record_a.period.config.project_class.abbreviation
                        pclass_b = concern.record_b.period.config.project_class.abbreviation
                    except Exception:
                        year_a = year_b = pclass_a = pclass_b = None

                    year_gap = (
                        abs(year_a - year_b)
                        if year_a is not None and year_b is not None
                        else None
                    )

                    similarity_rows.append(
                        {
                            "concern_token": uuid.uuid4().hex,
                            "submission_token_a": token_map.get(concern.record_a_id),
                            "submission_token_b": token_map.get(concern.record_b_id),
                            "academic_year_a": year_a,
                            "academic_year_b": year_b,
                            "year_gap": year_gap,
                            "pclass_abbreviation_a": pclass_a,
                            "pclass_abbreviation_b": pclass_b,
                            "chunk_type": concern.chunk_type,
                            "minhash_jaccard": concern.minhash_jaccard,
                            "transformer_cosine": concern.transformer_cosine,
                            "jaccard_triggered": concern.jaccard_triggered,
                            "cosine_triggered": concern.cosine_triggered,
                            "reviewed": concern.reviewed,
                            "resolution": concern.resolution,
                        }
                    )

            # ----------------------------------------------------------------
            # Build workbook
            # ----------------------------------------------------------------
            progress_update(
                task_id, TaskRecord.RUNNING, 85, "Writing Excel workbook...", autocommit=True
            )

            wb = openpyxl.Workbook()
            ws1 = wb.active
            ws1.title = "submissions"
            ws1.append(_SUBMISSIONS_COLUMNS)
            for row in submission_rows:
                ws1.append([row.get(col) for col in _SUBMISSIONS_COLUMNS])

            ws2 = wb.create_sheet("similarity_concerns")
            ws2.append(_SIMILARITY_COLUMNS)
            for row in similarity_rows:
                ws2.append([row.get(col) for col in _SIMILARITY_COLUMNS])

            # ----------------------------------------------------------------
            # Upload and link to Download Centre
            # ----------------------------------------------------------------
            now = datetime.now()
            expiry = now + timedelta(weeks=4)
            object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")

            if min_year is not None and max_year is not None:
                filename_stem = f"analytical_export_{min_year}_{max_year}"
            else:
                filename_stem = "analytical_export_unknown"
            stem_ts = f"{filename_stem}_{now.strftime('%Y-%m-%d_%H-%M-%S')}"

            with ScratchFileManager(suffix=".xlsx") as mgr:
                wb.save(mgr.path)

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
                        audit_data="data_export.export_tenant_marking_data_xlsx",
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
                    description="Analytical marking data export",
                )
                db.session.add(download_item)

            message = render_template_string(_EXPORT_READY_TMPL)
            user.post_message(message, "success", autocommit=False)
            db.session.commit()

        except Exception as exc:
            db.session.rollback()
            current_app.logger.exception(
                "Unhandled error in export_tenant_marking_data_xlsx", exc_info=exc
            )
            progress_update(
                task_id, TaskRecord.FAILURE, 100, "Export failed.", autocommit=True
            )
            raise self.retry()

        progress_update(
            task_id, TaskRecord.SUCCESS, 100, "Export complete.", autocommit=True
        )

    return export_tenant_marking_data_xlsx
