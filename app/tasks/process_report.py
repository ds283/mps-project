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
from uuid import uuid4

import fitz
from celery.exceptions import Ignore
from dateutil.tz import tzutc, tzoffset
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import SubmissionRecord, SubmittedAsset, User, ProjectClassConfig, GeneratedAsset, StudentData, validate_nonce
from ..shared.asset_tools import AssetCloudAdapter, AssetUploadManager
from ..shared.scratch import ScratchFileManager

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


_dyslexic_label = (
    "SSU have flagged this student as dyslexic. Please refer to the guidelines on marking which can be found in the Handbook for Examiners."
)
_dyspraxic_label = (
    "SSU have flagged this student as dyspraxic. Please refer to the guidelines on marking which can be found in the Handbook for Examiners."
)


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
            date_info["tzinfo"] = tzoffset(None, multiplier * (3600 * date_info["tz_hour"] + 60 * date_info["tz_minute"]))

        for k in ("tz_offset", "tz_hour", "tz_minute"):  # no longer needed
            del date_info[k]

        return datetime(**date_info)


def _process_report(source: Path, dest: Path, record: SubmissionRecord):
    config: ProjectClassConfig = record.owner.config
    data: StudentData = record.owner.student

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

    ytop = _initial_y_position

    ytop = _coverpage_title(coverpage_label, page, w, ytop)
    ytop = _coverpage_candidate_number(candidate_label, page, w, ytop)
    ytop = _coverpage_metadata(creation_date, metadata, modified_date, num_pages, page, w, ytop)

    # embed dyslexia sticker if required
    if data.dyslexia_sticker:
        ytop = _attach_sticker(page, w, ytop, _dyslexia_sticker_colour, _dyslexic_label)

    # embed dyspraxia sticker if required
    if data.dyspraxia_sticker:
        ytop = _attach_sticker(page, w, ytop, _dyspraxia_sticker_colour, _dyspraxic_label)

    doc.save(str(dest))


def _coverpage_metadata(creation_date, metadata, modified_date, num_pages, page, w, ytop):
    x0 = _initial_x_position
    y0 = ytop + _text_label_size + _vertical_margin
    p2 = fitz.Point(x0, y0)
    rc = page.insert_text(p2, "Number of pages: {n}".format(n=num_pages), color=_black, fontname="Helvetica", fontsize=_text_label_size)

    x0 = int(w / 2)
    p3 = fitz.Point(x0, y0)
    rc = page.insert_text(p3, "Producer: {p}".format(p=metadata["producer"]), color=_black, fontname="Helvetica", fontsize=_text_label_size)
    ytop = ytop + _text_label_size + _vertical_margin

    x0 = _initial_x_position
    y0 = ytop + _text_label_size + _vertical_margin
    p4 = fitz.Point(x0, y0)
    rc = page.insert_text(p4, "Format: {p}".format(p=metadata["format"]), color=_black, fontname="Helvetica", fontsize=_text_label_size)
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
        "Last modified: {date}".format(date=modified_date.strftime("%a %d %b %Y %H:%M:%S")),
        color=_black,
        fontname="Helvetica",
        fontsize=_text_label_size,
    )
    ytop = ytop + _text_label_size + _vertical_margin

    return ytop


def _coverpage_candidate_number(candidate_label, page, w, ytop):
    candidate_label_width = fitz.get_text_length(candidate_label, fontname="Helvetica", fontsize=_subtitle_label_size)

    x0 = (w - candidate_label_width) / 2
    y0 = ytop + _subtitle_label_size + _vertical_margin

    p_subtitle = fitz.Point(x0, y0)

    rc = page.insert_text(p_subtitle, candidate_label, color=_black, fontname="Helvetica", fontsize=_subtitle_label_size)

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
        "This page was automatically generated on {now}".format(now=now.strftime("%a %d %b %Y %H:%M:%S")),
        color=_black,
        fontname="Helvetica",
        align=fitz.TEXT_ALIGN_CENTER,
        fontsize=_text_label_size,
    )
    shape.commit()
    ytop = ytop + rheight + _text_label_size

    coverpage_label_width = fitz.get_text_length(coverpage_label, fontname="Helvetica", fontsize=_title_label_size)

    x0 = (w - coverpage_label_width) / 2
    y0 = ytop + _title_label_size + _vertical_margin

    p_title = fitz.Point(x0, y0)

    rc = page.insert_text(p_title, coverpage_label, color=_black, fontname="Helvetica", fontsize=_title_label_size)

    return ytop + _title_label_size + _vertical_margin + _title_label_size


def _attach_sticker(page, w, ytop, colour, text):
    xmargin = _sticker_margin

    rwidth = w - 2 * xmargin
    rheight = _vertical_margin + 3 * _title_label_size + _vertical_margin

    x0 = xmargin
    y0 = ytop + _title_label_size

    r1 = fitz.Rect(x0, y0, x0 + rwidth, y0 + rheight)

    shape = page.new_shape()
    shape.draw_rect(r1)
    shape.finish(color=colour, fill=colour, width=0.3)
    rc = shape.insert_textbox(r1, text, color=_black, fontname="Helvetica", align=fitz.TEXT_ALIGN_CENTER, fontsize=_sticker_text_size)
    shape.commit()

    return ytop + _title_label_size + rheight + _vertical_margin


def register_process_report_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def process(self, record_id):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state("FAILURE", meta={"msg": "Could not load SubmissionRecord instance from database"})
            raise Ignore()

        asset: SubmittedAsset = record.report

        if asset is None:
            self.update_state("FAILURE", meta={"msg": "A report has not been uploaded"})
            raise Ignore()

        object_store = current_app.config.get("OBJECT_STORAGE_ASSETS")
        input_storage = AssetCloudAdapter(asset, object_store, audit_data=f"process_report.process #1 (record id #{record_id})")

        if not input_storage.exists():
            self.update_state("FAILURE", meta={"msg": "Could not find report in object store"})
            raise Ignore()

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
                        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                        raise self.retry()

                    # attach asset to the SubmissionRecord
                    record.processed_report_id = new_asset.id

                    # set ACLs for processed report to match those of uploaded report
                    new_asset.access_control_list = asset.access_control_list
                    new_asset.access_control_roles = asset.access_control_roles

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def finalize(self, record_id):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load SubmissionRecord instance from database"})
            raise Ignore()

        record.celery_finished = True
        record.timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state="SUCCESS")

    @celery.task(bind=True, default_retry_delay=30)
    def error(self, record_id, user_id):
        try:
            record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=record_id).first()
            user: User = db.session.query(User).filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if record is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load SubmissionRecord instance from database"})
            raise Ignore()

        if user is None:
            self.update_state(state="FAILURE", meta={"msg": "Could not load User model from database"})
            raise Ignore()

        user.post_message(
            "Errors occurred when processing uploaded report for submitter {name}".format(name=record.owner.student.user.name),
            "danger",
            autocommit=True,
        )

        # raise exception to flag the error
        raise RuntimeError("Errors occurred when processing uploaded report")
