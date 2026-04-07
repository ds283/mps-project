#
# Created by David Seery on 08/12/2021.
# Copyright (c) 2021 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

import fitz
from dateutil.tz import tzutc, tzoffset
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    SubmissionRecord,
    SubmittedAsset,
    User,
    ProjectClassConfig,
    GeneratedAsset,
    StudentData,
)
from ..shared.security import validate_nonce
from ..shared.workflow_logging import log_db_commit
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.scratch import ScratchFileManager
from .thumbnails import dispatch_thumbnail_task


def _dispatch_advance_marking_workflow(record_id: int) -> None:
    """Fire-and-forget dispatch of advance_marking_workflow after report processing completes."""
    celery = current_app.extensions["celery"]
    task = celery.tasks["app.tasks.markingevent.advance_marking_workflow"]
    task.apply_async(args=[record_id])

_title_label_size = 24
_subtitle_label_size = 18
_sticker_text_size = 18
_text_label_size = 12
_vertical_margin = 6

_initial_x_position = 25
_initial_y_position = 30

_sticker_margin = 100


_dyslexia_sticker_colour = (248 / 255, 250 / 255, 83 / 255)
_dyspraxia_sticker_colour = (176 / 255, 210 / 255, 120 / 255)

_black = (0, 0, 0)
_light_grey = (0.8, 0.8, 0.8)


_dyslexic_label = "SSU have flagged this student as having a specific learning difference that impacts their literacy skills. Please refer to the marking guidelines."
_dyspraxic_label = "SSU have flagged this student as having a learning support package. Please refer to the marking guidelines."


# PDF date parser borrowed from here: https://stackoverflow.com/questions/16503075/convert-creationtime-of-pdf-to-a-readable-format-in-python
pdf_date_pattern = re.compile(
    "".join(
        [
            r"(D:)?",
            r"(?P<year>\d\d\d\d)",
            r"(?P<month>\d\d)",
            r"(?P<day>\d\d)",
            r"(?P<hour>\d\d)",
            r"(?P<minute>\d\d)",
            r"(?P<second>\d\d)",
            r"(?P<tz_offset>[+-zZ])?",
            r"(?P<tz_hour>\d\d)?",
            r"'?(?P<tz_minute>\d\d)?'?",
        ]
    )
)


def transform_date(date_str):
    """
    Convert a pdf date such as "D:20120321183444+07'00'" into a usable datetime
    http://www.verypdf.com/pdfinfoeditor/pdf-date-format.htm
    (D:YYYYMMDDHHmmSSOHH'mm')
    :param date_str: pdf date string
    :return: datetime object
    """
    global pdf_date_pattern
    match = re.match(pdf_date_pattern, date_str)
    if match:
        date_info = match.groupdict()

        for k, v in date_info.items():  # transform values
            if v is None:
                pass
            elif k == "tz_offset":
                date_info[k] = v.lower()  # so we can treat Z as z
            elif k == "year" and len(v) == 5:
                date_info[k] = int("20" + v[3:])
            else:
                date_info[k] = int(v)

        if date_info["tz_offset"] in ("z", None):  # UTC
            date_info["tzinfo"] = tzutc()
        else:
            multiplier = 1 if date_info["tz_offset"] == "+" else -1
            date_info["tzinfo"] = tzoffset(
                None,
                multiplier
                * (3600 * date_info["tz_hour"] + 60 * date_info["tz_minute"]),
            )

        for k in ("tz_offset", "tz_hour", "tz_minute"):  # no longer needed
            del date_info[k]

        return datetime(**date_info)


def _process_report(source: Path, dest: Path, record: SubmissionRecord):
    config: ProjectClassConfig = record.owner.config
    data: StudentData = record.owner.student
    full_name = f"{data.user.first_name} {data.user.last_name}"

    doc = fitz.open(str(source))
    if not doc.is_pdf:
        raise ValueError("Report document is not a PDF file")

    num_pages = doc.page_count
    metadata = doc.metadata

    creation_date = transform_date(metadata["creationDate"])
    modified_date = transform_date(metadata["modDate"])

    coverpage_label = "{name} Cover Sheet".format(name=config.name)
    candidate_label = "Candidate No. {num}".format(num=data.exam_number)

    w, h = fitz.paper_size("A4")
    page = doc.new_page(pno=0, width=w, height=h)

    # Redact student name from all original pages (now at indices 1+)
    redaction_count = _redact_student_name(doc, full_name)

    ytop = _initial_y_position

    ytop = _coverpage_title(coverpage_label, page, w, ytop)
    ytop = _coverpage_candidate_number(candidate_label, page, w, ytop)
    ytop = _coverpage_metadata(
        creation_date, metadata, modified_date, num_pages, page, w, ytop
    )

    # embed dyslexia sticker if required
    if data.dyslexia_sticker:
        ytop = _attach_sticker(page, w, ytop, _dyslexia_sticker_colour, _dyslexic_label)

    # embed dyspraxia sticker if required
    if data.dyspraxia_sticker:
        ytop = _attach_sticker(
            page, w, ytop, _dyspraxia_sticker_colour, _dyspraxic_label
        )

    # embed redaction notice if the student's name was found and redacted
    if redaction_count > 0:
        ytop = _coverpage_redaction_notice(page, w, ytop, redaction_count)

    # embed LLM analysis metrics section (only when analysis has completed)
    if record.language_analysis_complete:
        ytop = _coverpage_llm_metrics(page, record, w, ytop)

    doc.save(str(dest))


def _coverpage_metadata(
        creation_date, metadata, modified_date, num_pages, page, w, ytop
):
    x0 = _initial_x_position
    y0 = ytop + _text_label_size + _vertical_margin
    p2 = fitz.Point(x0, y0)
    rc = page.insert_text(
        p2,
        "Number of pages: {n}".format(n=num_pages),
        color=_black,
        fontname="Helvetica",
        fontsize=_text_label_size,
    )

    x0 = int(w / 2)
    p3 = fitz.Point(x0, y0)
    rc = page.insert_text(
        p3,
        "Producer: {p}".format(p=metadata["producer"]),
        color=_black,
        fontname="Helvetica",
        fontsize=_text_label_size,
    )
    ytop = ytop + _text_label_size + _vertical_margin

    x0 = _initial_x_position
    y0 = ytop + _text_label_size + _vertical_margin
    p4 = fitz.Point(x0, y0)
    rc = page.insert_text(
        p4,
        "Format: {p}".format(p=metadata["format"]),
        color=_black,
        fontname="Helvetica",
        fontsize=_text_label_size,
    )
    ytop = ytop + _text_label_size + _vertical_margin

    x0 = _initial_x_position
    y0 = ytop + _text_label_size + _vertical_margin
    p6 = fitz.Point(x0, y0)
    rc = page.insert_text(
        p6,
        "Created at {date}".format(date=creation_date.strftime("%a %d %b %Y %H:%M:%S")),
        color=_black,
        fontname="Helvetica",
        fontsize=_text_label_size,
    )

    x0 = int(w / 2)
    p7 = fitz.Point(x0, y0)
    rc = page.insert_text(
        p7,
        "Last modified: {date}".format(
            date=modified_date.strftime("%a %d %b %Y %H:%M:%S")
        ),
        color=_black,
        fontname="Helvetica",
        fontsize=_text_label_size,
    )
    ytop = ytop + _text_label_size + _vertical_margin

    return ytop


def _coverpage_candidate_number(candidate_label, page, w, ytop):
    candidate_label_width = fitz.get_text_length(
        candidate_label, fontname="Helvetica", fontsize=_subtitle_label_size
    )

    x0 = (w - candidate_label_width) / 2
    y0 = ytop + _subtitle_label_size + _vertical_margin

    p_subtitle = fitz.Point(x0, y0)

    rc = page.insert_text(
        p_subtitle,
        candidate_label,
        color=_black,
        fontname="Helvetica",
        fontsize=_subtitle_label_size,
    )

    return ytop + _subtitle_label_size + _vertical_margin + _subtitle_label_size


def _coverpage_title(coverpage_label, page, w, ytop):
    rwidth = w - 2 * _sticker_margin
    rheight = _vertical_margin + _text_label_size

    x0 = _sticker_margin
    y0 = ytop + _vertical_margin

    r1 = fitz.Rect(x0, y0, x0 + rwidth, y0 + rheight)

    shape = page.new_shape()
    shape.draw_rect(r1)
    shape.finish(color=_light_grey, fill=_light_grey, width=0.3)

    now = datetime.now()
    rc = shape.insert_textbox(
        r1,
        "This page was automatically generated on {now}".format(
            now=now.strftime("%a %d %b %Y %H:%M:%S")
        ),
        color=_black,
        fontname="Helvetica",
        align=fitz.TEXT_ALIGN_CENTER,
        fontsize=_text_label_size,
    )
    shape.commit()
    ytop = ytop + rheight + _text_label_size

    coverpage_label_width = fitz.get_text_length(
        coverpage_label, fontname="Helvetica", fontsize=_title_label_size
    )

    x0 = (w - coverpage_label_width) / 2
    y0 = ytop + _title_label_size + _vertical_margin

    p_title = fitz.Point(x0, y0)

    rc = page.insert_text(
        p_title,
        coverpage_label,
        color=_black,
        fontname="Helvetica",
        fontsize=_title_label_size,
    )

    return ytop + _title_label_size + _vertical_margin + _title_label_size


def _redact_student_name(doc: fitz.Document, full_name: str) -> int:
    """
    Search pages 1+ of doc for full_name and permanently redact every hit.
    Page 0 is the generated cover sheet and is skipped.
    Returns the total number of redacted instances.
    """
    total = 0
    for page_idx in range(1, doc.page_count):
        page = doc[page_idx]
        hits = page.search_for(full_name)
        if hits:
            for rect in hits:
                page.add_redact_annot(rect, fill=(0, 0, 0))
            page.apply_redactions(graphics=0)
            total += len(hits)
    return total


def _coverpage_redaction_notice(page, w, ytop, count):
    """Add a notice to the cover page that the student's name has been redacted."""
    xmargin = _initial_x_position
    rwidth = w - 2 * xmargin
    notice_colour = (0.95, 0.92, 0.80)  # pale amber

    notice_text = (
        f"Name redacted: {count} instance(s) of the student's name were automatically "
        "redacted from the submitted document. Redacted text appears as solid black rectangles."
    )
    box_height = _vertical_margin + 2 * (_text_label_size + 2) + _vertical_margin
    ytop += _vertical_margin
    r = fitz.Rect(xmargin, ytop, xmargin + rwidth, ytop + box_height)
    shape = page.new_shape()
    shape.draw_rect(r)
    shape.finish(color=(0.6, 0.5, 0.0), fill=notice_colour, width=0.8)
    shape.insert_textbox(
        r,
        notice_text,
        color=_black,
        fontname="Helvetica-Oblique",
        fontsize=_text_label_size,
        align=fitz.TEXT_ALIGN_LEFT,
    )
    shape.commit()
    return ytop + box_height + _vertical_margin


def _attach_sticker(page, w, ytop, colour, text):
    xmargin = _sticker_margin

    rwidth = w - 2 * xmargin
    rheight = _vertical_margin + 4 * _title_label_size + _vertical_margin

    x0 = xmargin
    y0 = ytop + _title_label_size

    r1 = fitz.Rect(x0, y0, x0 + rwidth, y0 + rheight)

    shape = page.new_shape()
    shape.draw_rect(r1)
    shape.finish(color=colour, fill=colour, width=0.3)
    rc = shape.insert_textbox(
        r1,
        text,
        color=_black,
        fontname="Helvetica",
        align=fitz.TEXT_ALIGN_CENTER,
        fontsize=_sticker_text_size,
    )
    shape.commit()

    return ytop + _title_label_size + rheight + _vertical_margin


_ai_statement_highlight_colour = (0.95, 0.85, 0.85)  # pale red for AI compliance statement box
_section_header_colour = (0.88, 0.88, 0.95)  # pale blue-grey for section header


def _coverpage_llm_metrics(page, record: "SubmissionRecord", w, ytop):
    """
    Insert a section on the cover page summarising the automated language-analysis metrics.
    Called only when record.language_analysis_complete is True.

    Inserts:
      • A section header
      • A disclaimer (AI-generated, for guidance only)
      • Word count (measured) and student-stated word count if available
      • Reference, figure and table counts with brief detail on uncited items
      • AI compliance statement block (red-highlighted if detected; grey note if absent)

    Returns the updated ytop after all content has been inserted.
    """
    la = record.language_analysis_data
    metrics = la.get("metrics", {})
    llm_result = la.get("llm_result", {})

    xmargin = _initial_x_position
    rwidth = w - 2 * xmargin

    # ── Section header ────────────────────────────────────────────────────────
    ytop += _vertical_margin
    header_height = _vertical_margin + _text_label_size + _vertical_margin
    r_header = fitz.Rect(xmargin, ytop, xmargin + rwidth, ytop + header_height)
    shape = page.new_shape()
    shape.draw_rect(r_header)
    shape.finish(color=_section_header_colour, fill=_section_header_colour, width=0.3)
    shape.insert_textbox(
        r_header,
        "Automated Analysis Summary",
        color=_black,
        fontname="Helvetica-Bold",
        fontsize=_text_label_size,
        align=fitz.TEXT_ALIGN_CENTER,
    )
    shape.commit()
    ytop += header_height + _vertical_margin

    # ── Disclaimer ───────────────────────────────────────────────────────────
    disclaimer = (
        "The metrics below are automatically generated for guidance only. "
        "They do not constitute recommendations and should not replace the marker's own judgement."
    )
    disclaimer_rect = fitz.Rect(xmargin, ytop, xmargin + rwidth, ytop + 3 * _text_label_size + _vertical_margin)
    shape = page.new_shape()
    shape.insert_textbox(
        disclaimer_rect,
        disclaimer,
        color=(0.4, 0.4, 0.4),
        fontname="Helvetica-Oblique",
        fontsize=_text_label_size - 1,
        align=fitz.TEXT_ALIGN_LEFT,
    )
    shape.commit()
    ytop += 3 * _text_label_size + _vertical_margin

    # ── Word count ───────────────────────────────────────────────────────────
    word_count = metrics.get("word_count")
    stated_word_count = llm_result.get("stated_word_count") if llm_result else None
    if word_count is not None:
        if stated_word_count is not None:
            wc_text = "Word count: {measured:,} (measured)   |   {stated:,} (student-stated)".format(
                measured=int(word_count), stated=int(stated_word_count)
            )
        else:
            wc_text = "Word count: {measured:,} (measured)".format(measured=int(word_count))
        ytop += _text_label_size
        page.insert_text(
            fitz.Point(xmargin, ytop),
            wc_text,
            color=_black,
            fontname="Helvetica",
            fontsize=_text_label_size,
        )
        ytop += _vertical_margin

    # ── Page count ───────────────────────────────────────────────────────────
    page_count = metrics.get("page_count")
    if page_count is not None:
        ytop += _text_label_size
        page.insert_text(
            fitz.Point(xmargin, ytop),
            "Page count: {n}".format(n=int(page_count)),
            color=_black,
            fontname="Helvetica",
            fontsize=_text_label_size,
        )
        ytop += _vertical_margin

    # ── References ───────────────────────────────────────────────────────────
    ref_count = metrics.get("reference_count")
    uncited_refs = metrics.get("uncited_references") or []
    if ref_count is not None:
        uncited_count = len(uncited_refs) if isinstance(uncited_refs, list) else 0
        if uncited_count > 0:
            if uncited_count <= 4:
                uncited_detail = "; ".join(str(r) for r in uncited_refs[:4])
                ref_text = "References: {n}   |   Uncited: {uc} ({detail})".format(
                    n=int(ref_count), uc=uncited_count, detail=uncited_detail
                )
            else:
                ref_text = "References: {n}   |   Uncited: {uc}".format(
                    n=int(ref_count), uc=uncited_count
                )
        else:
            ref_text = "References: {n}   |   Uncited: none".format(n=int(ref_count))
        ytop += _text_label_size
        page.insert_text(
            fitz.Point(xmargin, ytop),
            ref_text,
            color=_black,
            fontname="Helvetica",
            fontsize=_text_label_size,
        )
        ytop += _vertical_margin

    # ── Figures ──────────────────────────────────────────────────────────────
    fig_count = metrics.get("figure_count")
    unreferenced_figs = metrics.get("unreferenced_figures") or []
    if fig_count is not None:
        unref_fig_count = len(unreferenced_figs) if isinstance(unreferenced_figs, list) else 0
        if unref_fig_count > 0:
            if unref_fig_count <= 4:
                fig_detail = "; ".join(str(f) for f in unreferenced_figs[:4])
                fig_text = "Figures: {n}   |   Unreferenced: {u} ({detail})".format(
                    n=int(fig_count), u=unref_fig_count, detail=fig_detail
                )
            else:
                fig_text = "Figures: {n}   |   Unreferenced: {u}".format(
                    n=int(fig_count), u=unref_fig_count
                )
        else:
            fig_text = "Figures: {n}   |   Unreferenced: none".format(n=int(fig_count))
        ytop += _text_label_size
        page.insert_text(
            fitz.Point(xmargin, ytop),
            fig_text,
            color=_black,
            fontname="Helvetica",
            fontsize=_text_label_size,
        )
        ytop += _vertical_margin

    # ── Tables ───────────────────────────────────────────────────────────────
    table_count = metrics.get("table_count")
    unreferenced_tables = metrics.get("unreferenced_tables") or []
    if table_count is not None:
        unref_table_count = len(unreferenced_tables) if isinstance(unreferenced_tables, list) else 0
        if unref_table_count > 0:
            if unref_table_count <= 4:
                tbl_detail = "; ".join(str(t) for t in unreferenced_tables[:4])
                tbl_text = "Tables: {n}   |   Unreferenced: {u} ({detail})".format(
                    n=int(table_count), u=unref_table_count, detail=tbl_detail
                )
            else:
                tbl_text = "Tables: {n}   |   Unreferenced: {u}".format(
                    n=int(table_count), u=unref_table_count
                )
        else:
            tbl_text = "Tables: {n}   |   Unreferenced: none".format(n=int(table_count))
        ytop += _text_label_size
        page.insert_text(
            fitz.Point(xmargin, ytop),
            tbl_text,
            color=_black,
            fontname="Helvetica",
            fontsize=_text_label_size,
        )
        ytop += _vertical_margin

    # ── AI compliance statement ───────────────────────────────────────────────
    ytop += _vertical_margin
    genai_found = llm_result.get("genai_statement_found", False) if llm_result else False
    genai_precis = llm_result.get("genai_statement_precis") if llm_result else None

    if genai_found:
        if genai_precis:
            ai_box_text = (
                "AI COMPLIANCE STATEMENT DETECTED\n\n"
                "The following AI compliance statement was identified in this submission. "
                "Please review it carefully.\n\n"
                '"{precis}"'.format(precis=genai_precis)
            )
        else:
            ai_box_text = (
                "AI COMPLIANCE STATEMENT DETECTED\n\n"
                "An AI compliance statement was identified in this submission. "
                "Please review it carefully."
            )
        box_colour = _ai_statement_highlight_colour
        border_colour = (0.7, 0.2, 0.2)
    else:
        ai_box_text = "AI compliance statement: none detected."
        box_colour = _light_grey
        border_colour = (0.5, 0.5, 0.5)

    # Estimate height: 4 lines for detected case, 1 for not-detected
    ai_box_lines = 5 if genai_found else 1
    ai_box_height = _vertical_margin + ai_box_lines * (_text_label_size + 2) + _vertical_margin
    r_ai = fitz.Rect(xmargin, ytop, xmargin + rwidth, ytop + ai_box_height)
    shape = page.new_shape()
    shape.draw_rect(r_ai)
    shape.finish(color=border_colour, fill=box_colour, width=1.0)
    shape.insert_textbox(
        r_ai,
        ai_box_text,
        color=_black,
        fontname="Helvetica-Bold" if genai_found else "Helvetica",
        fontsize=_text_label_size,
        align=fitz.TEXT_ALIGN_LEFT,
    )
    shape.commit()
    ytop += ai_box_height + _vertical_margin

    return ytop


def register_process_report_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def process(self, record_id):
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = "Could not load SubmissionRecord instance from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        # Report processing requires the LLM analysis to have completed successfully,
        # because LLM outputs (word counts, AI statement, metrics) are embedded in the cover page.
        # If analysis has not yet run, skip silently — language_analysis.finalize() will
        # dispatch this task again once analysis completes.
        if not record.language_analysis_complete:
            current_app.logger.info(
                f"process_report.process: LLM analysis not yet complete for record "
                f"id={record_id}; deferring until analysis finishes."
            )
            return

        asset: SubmittedAsset = record.report

        if asset is None:
            msg = "A report has not been uploaded"
            current_app.logger.error(msg)
            raise Exception(msg)

        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
        input_storage = AssetCloudAdapter(
            asset,
            object_store,
            audit_data=f"process_report.process #1 (record id #{record_id})",
        )

        if not input_storage.exists():
            msg = "Could not find report in object store"
            current_app.logger.error(msg)
            raise Exception(msg)

        # generate scratch names
        with ScratchFileManager() as output_path:
            with input_storage.download_to_scratch() as input_path:
                try:
                    _process_report(input_path.path, output_path.path, record)
                except ValueError as e:
                    # document was not a PDF
                    record.processed_report = None
                else:
                    # generate asset record and upload to object store;
                    # AssetUploadManager will populate most fields later
                    new_asset = GeneratedAsset(
                        timestamp=datetime.now(),
                        expiry=None,
                        parent_asset_id=asset.id,
                        target_name="processed-" + asset.target_name,
                        license=asset.license,
                    )

                    object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
                    with open(output_path.path, "rb") as f:
                        with AssetUploadManager(
                            new_asset,
                            data=BytesIO(f.read()),
                            storage=object_store,
                            audit_data=f"process_report.process #2 (record id #{record_id})",
                            length=output_path.path.stat().st_size,
                            mimetype=asset.mimetype,
                            validate_nonce=validate_nonce,
                        ) as upload_mgr:
                            pass

                    try:
                        db.session.add(new_asset)
                        db.session.flush()
                    except SQLAlchemyError as e:
                        db.session.rollback()
                        current_app.logger.exception(
                            "SQLAlchemyError exception", exc_info=e
                        )
                        raise self.retry()

                    dispatch_thumbnail_task(new_asset)

                    # attach asset to the SubmissionRecord
                    record.processed_report_id = new_asset.id

                    # set ACLs for processed report to match those of uploaded report
                    new_asset.access_control_list = asset.access_control_list
                    new_asset.access_control_roles = asset.access_control_roles

        try:
            log_db_commit(
                f"Processed submitted report for submission record id={record_id}",
                student=record.owner.student,
                project_classes=record.owner.config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def finalize(self, record_id):
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = "Could not load SubmissionRecord instance from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        record.celery_finished = True
        record.timestamp = datetime.now()

        try:
            log_db_commit(
                f"Finalized report processing for submission record id={record_id}",
                student=record.owner.student,
                project_classes=record.owner.config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state="SUCCESS")

        # Advance any SubmitterReport instances that are now unblocked
        _dispatch_advance_marking_workflow(record_id)

    @celery.task(bind=True, default_retry_delay=30)
    def error(self, record_id, user_id):
        try:
            record: SubmissionRecord = (
                db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            )
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            msg = "Could not load SubmissionRecord instance from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        if user is None:
            msg = "Could not load User model from database"
            current_app.logger.error(msg)
            raise Exception(msg)

        user.post_message(
            "Errors occurred when processing uploaded report for submitter {name}".format(
                name=record.owner.student.user.name
            ),
            "danger",
            autocommit=True,
        )

        # Mark the record so that report_processing_failed is detectable downstream
        record.celery_failed = True
        try:
            log_db_commit(
                f"Marked report processing failure for submission record id={record_id}",
                student=record.owner.student,
                project_classes=record.owner.config.project_class,
                endpoint=self.name,
            )
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        # raise exception to flag the error
        raise RuntimeError("Errors occurred when processing uploaded report")
