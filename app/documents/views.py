#
# Created by David Seery on 05/01/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from celery import chain, group, chord
from flask import render_template, redirect, url_for, flash, request, current_app, jsonify, abort, session
from flask_security import login_required, roles_accepted, current_user
from sqlalchemy import or_, and_
from sqlalchemy.exc import SQLAlchemyError

import app.ajax as ajax
from . import documents
from .forms import UploadReportForm, UploadSubmitterAttachmentFormFactory, EditReportForm, \
    EditSubmitterAttachmentFormFactory
from .utils import is_editable, is_deletable, is_listable, is_uploadable, is_admin, is_processable
from ..database import db
from ..models import SubmissionRecord, SubmittedAsset, GeneratedAsset, SubmissionAttachment, Role, \
    SubmissionPeriodRecord, ProjectClassConfig, ProjectClass, PeriodAttachment, User, AssetLicense, SubmittingStudent
from ..shared.asset_tools import make_submitted_asset_filename
from ..shared.forms.forms import SelectSubmissionRecordFormFactory
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor, validate_is_admin_or_convenor
from ..uploads import submitted_files

ATTACHMENT_TYPE_PERIOD = 0
ATTACHMENT_TYPE_SUBMISSION = 1
ATTACHMENT_TYPE_UPLOADED_REPORT = 2
ATTACHMENT_TYPE_PROCESSED_REPORT = 3


@documents.route('/submitter_documents', methods=['GET', 'POST'])
@login_required
def submitter_documents():
    sub_id = request.args.get('sub_id', None)
    sid = request.args.get('sid', None)

    # reject request if neither sub_id nor sid is specified
    if sub_id is None and sid is None:
        abort(404)

    submitter: SubmittingStudent = SubmittingStudent.query.get_or_404(sub_id) if sub_id is not None else None
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid) if sid is not None else None

    if submitter is not None:
        config: ProjectClassConfig = submitter.config
    else:
        config: ProjectClassConfig = record.period.config

    # construct selector form
    is_admin = validate_is_convenor(config.project_class, message=False)
    SelectSubmissionRecordForm = SelectSubmissionRecordFormFactory(config, is_admin)
    form: SelectSubmissionRecordForm = SelectSubmissionRecordForm(request.form)

    # if submitter and record are both specified, check that SubmissionRecord belongs to it.
    # otherwise, we select the SubmissionRecord corresponding to the current period
    if submitter is not None:
        if record is not None:
            if record.owner.id != submitter.id:
                flash('Cannot display submitter documents for this combination of student and submission record, '
                      'because the specified submission record does not belong to the student', 'info')
                return redirect(redirect_url())

        else:
            if hasattr(form, 'selector') and form.selector.data is not None:
                record: SubmissionRecord = submitter.get_assignment(period=form.selector.data)
            else:
                record: SubmissionRecord = submitter.get_assignment()

    else:
        # submitter was not specified, so SubmissionRecord must have been.
        # we extract the SubmittingStudent from the record
        assert record is not None
        submitter = record.owner

    # determine if the currently-logged-in user has permissions to view the documents associated with this
    # submission record
    if not is_listable(record, message=True):
        return redirect(redirect_url())

    # ensure form selector reflects the record that is actually being displayed
    period: SubmissionPeriodRecord = record.period
    if hasattr(form, 'selector'):
        form.selector.data = period

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    return render_template('documents/submitter_manager.html', submitter=submitter,
                           record=record, period=period, url=url, text=text, form=form,
                           is_editable=partial(is_editable, record, period=period, config=config, message=False),
                           deletable=is_deletable(record, period=period, config=config, message=False),
                           report_uploadable=is_uploadable(record, message=False, allow_student=False,
                                                           allow_faculty=False),
                           attachment_uploadable=is_uploadable(record, message=False, allow_student=True,
                                                               allow_faculty=True))


@documents.route('/generate_processed_report/<int:sid>')
def generate_processed_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash('Could not initiate processing of the report for this submitter because no report has been attached.', 'info')
        return redirect(redirect_url())

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    if record.processed_report:
        flash('Could not initiate processing of the report for this submitter because a processed report is already attached', 'info')
        return redirect(redirect_url())

    celery = current_app.extensions['celery']

    process = celery.tasks['app.tasks.process_report.process']
    finalize = celery.tasks['app.tasks.process_report.finalize']
    error = celery.tasks['app.tasks.process_report.error']

    work = chain(process.si(record.id),
                 finalize.si(record.id)).on_error(error.si(record.id, current_user.id))
    work.apply_async()

    record.celery_started = True
    record.celery_finished = None

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        flash('A database error was encountered while initiating processing. Please contact an administrator.', 'error')
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(redirect_url())


@documents.route('/delete_submitter_report/<int:sid>')
@login_required
def delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash('Could not delete report for this submitter because no report has been attached.', 'info')
        return redirect(redirect_url())

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    title = 'Delete project report'
    action_url = url_for('documents.perform_delete_submitter_report', sid=sid, url=url, text=text)

    message = '<p>Please confirm that you wish to remove the project report for ' \
              '<i class="fas fa-user"></i> {student} {period}.</p>' \
              '<p>This action cannot be undone.</p>'.format(student=record.student_identifier,
                                                            period=record.period.display_name)
    submit_label = 'Remove report'

    return render_template('admin/danger_confirm.html', title=title, panel_title=title, action_url=action_url,
                           message=message, submit_label=submit_label)


@documents.route('/perform_delete_submitter_report/<int:sid>')
@login_required
def perform_delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash('Could not delete report for this submitter because no file has been attached.', 'info')
        return redirect(redirect_url())

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    try:
        # set lifetime of uploaded asset to 30 days, after which it will be deleted by the garbage collection.
        # also, unlink asset record from this SubmissionRecord.
        # notice we have to adjust the timestamp, since together with the lifetime this determines the expiry date
        expiry_date = datetime.now() + timedelta(days=30)

        record.report.expiry = expiry_date
        record.report_id = None

        # remove processed report if it has been generated
        if record.processed_report is not None:
            record.processed_report.expiry = expiry_date
            record.processed_report_id = None

        record.celery_started = None
        record.celery_finished = None
        record.timestamp = None

        record.turnitin_outcome = None
        record.turnitin_score = None
        record.turnitin_web_overlap = None
        record.turnitin_publication_overlap = None
        record.turnitin_student_overlap = None

        # remove exemplar flag
        record.report_exemplar = None

        db.session.commit()

    except SQLAlchemyError as e:
        flash('Could not remove report from the submission record because of a database error. '
              'Please contact a system administrator.', 'error')
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))


@documents.route('/upload_submitter_report/<int:sid>', methods=['GET', 'POST'])
@login_required
def upload_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    if record.report is not None:
        flash('Can not upload a report for this submitter because an existing report is already attached.', 'info')
        return redirect(redirect_url())

    # check is convenor for the project's class, or has suitable admin/root privileges
    config: ProjectClassConfig = record.owner.config
    pclass: ProjectClass = config.project_class
    if not is_uploadable(record, message=True, allow_student=False, allow_faculty=False):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    form = UploadReportForm(request.form)

    if form.validate_on_submit():
        if 'report' in request.files:
            report_file = request.files['report']

            # generate unique filename for upload
            incoming_filename = Path(report_file.filename)
            extension = incoming_filename.suffix.lower()

            root_subfolder = current_app.config.get('ASSETS_REPORTS_SUBFOLDER') or 'reports'

            year_string = str(config.year)
            pclass_string = pclass.abbreviation

            subfolder = Path(root_subfolder) / Path(pclass_string) / Path(year_string)

            filename, abs_path = make_submitted_asset_filename(ext=extension, subpath=subfolder)
            submitted_files.save(report_file, folder=str(subfolder), name=str(filename))

            # generate asset record
            asset = SubmittedAsset(timestamp=datetime.now(),
                                   uploaded_id=current_user.id,
                                   expiry=None,
                                   filename=str(subfolder/filename),
                                   target_name=form.target_name.data,
                                   mimetype=str(report_file.content_type),
                                   license=form.license.data)


            # attach this asset as the uploaded report
            record.report_id = asset.id

            # uploading user has access
            asset.grant_user(current_user)

            # project supervisor has access
            if record.project is not None and record.project.owner is not None:
                asset.grant_user(record.project.owner.user)

            # project examiner has access
            if record.marker is not None:
                asset.grant_user(record.marker.user)

            # student can download their own report
            if record.owner is not None and record.owner.student is not None:
                asset.grant_user(record.owner.student.user)

            # set up list of roles that should have access, if they exist
            asset.grant_roles(['office', 'convenor', 'moderator', 'exam_board', 'external_examiner'])

            # remove processed report, if that has not already been done
            if record.processed_report is not None:
                expiry_date = datetime.now() + timedelta(days=30)
                record.processed_report.expiry = expiry_date
                record.processed_report_id = None

            record.celery_started = True
            record.celery_finished = None
            record.timestamp = None
            record.report_exemplar = False

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                flash('Could not upload report due to a database issue. Please contact an administrator.', 'error')
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            else:
                flash('Report "{file}" was successfully uploaded.'.format(file=incoming_filename), 'info')

            # set up asynchronous task to process this report
            celery = current_app.extensions['celery']

            process = celery.tasks['app.tasks.process_report.process']
            finalize = celery.tasks['app.tasks.process_report.finalize']
            error = celery.tasks['app.tasks.process_report.error']

            work = chain(process.si(record.id),
                         finalize.si(record.id)).on_error(error.si(record.id, current_user.id))
            work.apply_async()

            return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))

    else:
        if request.method == 'GET':
            # default to 'Exam' license if one is available
            default_report_license = db.session.query(AssetLicense).filter_by(abbreviation='Exam').first()
            if default_report_license is None:
                default_report_license = current_user.default_license

            form.license.data = default_report_license

    return render_template('documents/upload_report.html', record=record, form=form, url=url, text=text)


@documents.route('/pull_report_from_canvas/<int:rid>')
@login_required
def pull_report_from_canvas(rid):
    # rid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(rid)

    if record.report is not None:
        flash('Can not upload a report for this submitter because an existing report is already attached.', 'info')
        return redirect(redirect_url())

    # check is convenor for the project's class, or has suitable admin/root privileges
    if not is_uploadable(record, message=True, allow_student=False, allow_faculty=False):
        return redirect(redirect_url())

    url = request.args.get('url', None)

    # set up asynchronous task to pull this report
    celery = current_app.extensions['celery']

    process = celery.tasks['app.tasks.canvas.pull_report']
    finalize = celery.tasks['app.tasks.canvas.pull_report_finalize']
    error = celery.tasks['app.tasks.canvas.pull_report_error']

    work = chain(process.s(record.id, current_user.id),
                 finalize.s(record.id, current_user.id)).on_error(error.si(record.id, current_user.id))
    work.apply_async()

    if url:
        return redirect(url)

    return redirect(redirect_url())


@documents.route('/pull_all_reports_from_canvas/<int:pid>')
@roles_accepted('root', 'admin', 'faculty', 'office')
def pull_all_reports_from_canvas(pid):
    # pid is a SubmissionPeriodRecord id
    period: SubmissionPeriodRecord = SubmissionPeriodRecord.query.get_or_404(pid)

    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    if not validate_is_convenor(pclass, allow_roles=['office']):
        return redirect(redirect_url())

    # set up asynchronous task to pull this report
    celery = current_app.extensions['celery']

    process = celery.tasks['app.tasks.canvas.pull_report']
    finalize = celery.tasks['app.tasks.canvas.pull_report_finalize']
    error = celery.tasks['app.tasks.canvas.pull_report_error']
    summary = celery.tasks['app.tasks.canvas.pull_all_reports_summary']

    available = period.submissions.join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id) \
            .filter(and_(SubmissionRecord.report_id == None,
                         SubmissionRecord.canvas_submission_available == True,
                         SubmittingStudent.canvas_user_id != None)).all()

    work = chord([chain(process.s(record.id, None),
                        finalize.s(record.id, None).on_error(error.si(record.id, current_user.id))) for record in available],
                 summary.s(current_user.id))
    work.apply_async()

    return redirect(redirect_url())


@documents.route('/edit_submitter_report/<int:sid>', methods=['GET', 'POST'])
@login_required
def edit_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # get report asset; if none, nothing to do
    asset: SubmittedAsset = record.report
    if asset is None:
        flash('Could not edit the report for this submission record because it has not yet been attached.', 'info')
        return redirect(redirect_url())

    # verify current user has privileges to edit the report
    if not is_editable(record, asset=asset, message=True, allow_student=False):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    form = EditReportForm(obj=asset)

    if form.validate_on_submit():
        asset.license = form.license.data
        asset.target_name = form.target_name.data

        # update processed report license to match
        if record.processed_report is not None:
            passet: GeneratedAsset = record.processed_report
            passet.license = form.license.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash('Could not save changes to this asset record due to a database error. '
                  'Please contact a system administrator.', 'error')
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for('documents.submitter_documents', sid=record.id, url=url, text=text))

    action_url = url_for('documents.edit_submitter_report', sid=record.id, url=url, text=text)
    return render_template('documents/edit_attachment.html', form=form, record=record,
                           asset=asset, action_url=action_url)


@documents.route('/edit_submitter_attachment/<int:aid>', methods=['GET', 'POST'])
@login_required
def edit_submitter_attachment(aid):
    # aid is a SubmissionAttachment
    attachment: SubmissionAttachment = SubmissionAttachment.query.get_or_404(aid)

    # get attached asset
    asset: SubmittedAsset = attachment.attachment
    if asset is None:
        flash('Could not edit this attachment because of a database error. '
              'Please contact a system administrator.', 'info')
        return redirect(redirect_url())

    # extract SubmissionRecord and ensure that current user has sufficient privileges to perform edits
    record: SubmissionRecord = attachment.parent
    if not is_editable(record, asset=asset, message=True, allow_student=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    has_admin_rights = is_admin(current_user)
    EditSubmitterAttachmentForm = EditSubmitterAttachmentFormFactory(admin=has_admin_rights)
    form = EditSubmitterAttachmentForm(obj=attachment)

    if form.validate_on_submit():
        attachment.description = form.description.data

        asset.license = form.license.data
        asset.target_name = form.target_name.data

        if has_admin_rights:
            attachment.type = form.type.data
            attachment.publish_to_students = form.publish_to_students.data
            attachment.include_supervisor_emails = form.include_supervisor_emails.data
            attachment.include_marker_emails = form.include_marker_emails.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            flash('Could not save changes to this asset record due to a database error. '
                  'Please contact a system administrator.', 'error')
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

        return redirect(url_for('documents.submitter_documents', sid=record.id, url=url, text=text))

    else:
        if request.method == 'GET':
            form.license.data = asset.license
            form.target_name.data = asset.target_name

    action_url = url_for('documents.edit_submitter_attachment', aid=attachment.id, url=url, text=text)
    return render_template('documents/edit_attachment.html', form=form, record=record, attachment=attachment,
                           asset=asset, action_url=action_url, has_admin_rights=has_admin_rights)


@documents.route('/delete_submitter_attachment/<int:aid>')
@login_required
def delete_submitter_attachment(aid):
    # aid is a SubmissionAttachment id
    attachment: SubmissionAttachment = SubmissionAttachment.query.get_or_404(aid)

    # if asset is missing, nothing to do
    asset = attachment.attachment
    if asset is None:
        flash('Could not delete attachment because of a database error. '
              'Please contact a system administrator.', 'info')
        return redirect(redirect_url())

    record = attachment.parent
    if record is None:
        flash('Can not delete this attachment because it is not attached to a submitter.', 'info')
        return redirect(redirect_url())

    # check user has sufficient privileges to perform the deletion
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    title = 'Delete project attachment'
    action_url = url_for('documents.perform_delete_submitter_attachment', aid=aid, sid=record.id, url=url, text=text)

    name = asset.target_name if asset.target_name is not None else asset.filename
    message = '<p>Please confirm that you wish to remove the attachment <strong>{name}</strong> for ' \
              '<i class="fas fa-user"></i> {student} {period}.</p>' \
              '<p>This action cannot be undone.</p>'.format(name=name, student=record.student_identifier,
                                                            period=record.period.display_name)
    submit_label = 'Remove attachment'

    return render_template('admin/danger_confirm.html', title=title, panel_title=title, action_url=action_url,
                           message=message, submit_label=submit_label)


@documents.route('/perform_delete_submitter_attachment/<int:aid>/<int:sid>')
@login_required
def perform_delete_submitter_attachment(aid, sid):
    # aid is a SubmissionAttachment id
    attachment = SubmissionAttachment.query.get_or_404(aid)

    # if asset is missing, nothing to do
    asset = attachment.attachment
    if asset is None:
        flash('Could not delete attachment because of a database error. '
              'Please contact a system administrator.', 'info')
        return redirect(redirect_url())

    record = attachment.parent
    if record is None:
        flash('Can not delete this attachment because it is not attached to a submitter.', 'info')
        return redirect(redirect_url())

    # check user has sufficient privileges to perform the deletion
    if not is_deletable(record, message=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    try:
        # set to delete in 30 days
        asset.expiry = datetime.now() + timedelta(days=30)
        attachment.attachment_id = None

        db.session.flush()

        db.session.delete(attachment)
        db.session.commit()

    except SQLAlchemyError as e:
        flash('Could not remove attachment from the submission record because of a database error. '
              'Please contact a system administrator.', 'error')
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))


@documents.route('/upload_submitter_attachment/<int:sid>', methods=['GET', 'POST'])
@login_required
def upload_submitter_attachment(sid):
    # sid is a SubmissionRecord id
    record = SubmissionRecord.query.get_or_404(sid)

    # check is convenor for the project's class, or has suitable admin/root privileges
    config = record.owner.config
    pclass = config.project_class
    if not is_uploadable(record, message=True, allow_student=True, allow_faculty=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    has_admin_rights = is_admin(current_user)
    UploadSubmitterAttachmentForm = UploadSubmitterAttachmentFormFactory(admin=has_admin_rights)
    form = UploadSubmitterAttachmentForm(request.form)

    if form.validate_on_submit():
        if 'attachment' in request.files:
            attachment_file = request.files['attachment']

            # generate unique filename for upload
            incoming_filename = Path(attachment_file.filename)
            extension = incoming_filename.suffix.lower()

            root_subfolder = current_app.config.get('ASSETS_ATTACHMENTS_SUBFOLDER') or 'attachments'

            year_string = str(config.year)
            pclass_string = pclass.abbreviation

            subfolder = Path(root_subfolder) / Path(pclass_string) / Path(year_string)

            filename, abs_path = make_submitted_asset_filename(ext=extension, subpath=subfolder)
            submitted_files.save(attachment_file, folder=str(subfolder), name=str(filename))

            # generate asset record
            asset = SubmittedAsset(timestamp=datetime.now(),
                                   uploaded_id=current_user.id,
                                   expiry=None,
                                   filename=str(subfolder/filename),
                                   target_name=form.target_name.data,
                                   mimetype=str(attachment_file.content_type),
                                   license=form.license.data)

            try:
                db.session.add(asset)
                db.session.flush()
            except SQLAlchemyError as e:
                flash('Could not upload attachment due to a database issue. Please contact an administrator.', 'error')
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))

            # generate attachment record
            attachment = SubmissionAttachment(parent_id=record.id,
                                              attachment_id=asset.id,
                                              description=form.description.data)

            if has_admin_rights:
                attachment.type = form.type.data
                attachment.publish_to_students = form.publish_to_students.data
                attachment.include_supervisor_emails = form.include_supervisor_emails.data
                attachment.include_marker_emails = form.include_marker_emails.data

            else:
                attachment.include_marker_emails = False
                attachment.include_supervisor_emails = False
                attachment.type = SubmissionAttachment.ATTACHMENT_OTHER

                if current_user.has_role('student'):
                    attachment.publish_to_students = True

                else:
                    attachment.publish_to_students = False

            # uploading user has access
            asset.grant_user(current_user)

            # project supervisor has access
            if record.project is not None and record.project.owner is not None:
                asset.grant_user(record.project.owner.user)

            # project examiner has access
            if record.marker is not None:
                asset.grant_user(record.marker.user)

            # students can't ordinarily download attachments unless permission is given

            # set up list of roles that should have access, if they exist
            asset.grant_roles(['office', 'convenor', 'moderator', 'exam_board', 'external_examiner'])

            try:
                db.session.add(attachment)
                db.session.commit()
            except SQLAlchemyError as e:
                flash('Could not upload attachment due to a database issue. '
                      'Please contact an administrator.', 'error')
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            else:
                flash('Attachment "{file}" was successfully uploaded.'.format(file=incoming_filename), 'info')

            return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))

    else:
        if request.method == 'GET':
            form.license.data = current_user.default_license

    return render_template('documents/upload_attachment.html', record=record, form=form, url=url, text=text,
                           has_admin_rights=has_admin_rights)


def _get_attachment_asset(attach_type, attach_id):
    if attach_type == ATTACHMENT_TYPE_SUBMISSION:
        attachment: SubmissionAttachment = db.session.query(SubmissionAttachment).filter_by(id=attach_id).first()
        if attachment is None:
            raise KeyError

        asset: SubmittedAsset = attachment.attachment
        pclass: ProjectClass = attachment.parent.period.config.project_class

        return attachment, asset, pclass

    if attach_type == ATTACHMENT_TYPE_PERIOD:
        attachment: PeriodAttachment = PeriodAttachment.query.get_or_404(attach_id)
        if attachment is None:
            raise KeyError

        asset: SubmittedAsset = attachment.attachment
        pclass: ProjectClass = attachment.parent.config.project_class

        return attachment, asset, pclass

    if attach_type == ATTACHMENT_TYPE_UPLOADED_REPORT:
        record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=attach_id).first()
        if record is None:
            raise KeyError

        asset: SubmittedAsset = record.report
        pclass: ProjectClass = record.period.config.project_class

        return record, asset, pclass

    if attach_type == ATTACHMENT_TYPE_PROCESSED_REPORT:
        record: SubmissionRecord = db.session.query(SubmissionRecord).filter_by(id=attach_id).first()
        if record is None:
            return KeyError

        asset: GeneratedAsset = record.processed_report
        pclass: ProjectClass = record.period.config.project_class

        return record, asset, pclass

    raise KeyError

@documents.route('/attachment_acl/<int:attach_type>/<int:attach_id>')
@login_required
def attachment_acl(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)
    pane = request.args.get('pane', None)
    state_filter = request.args.get('state_filter', None)

    if pane not in ['users', 'roles']:
        pane = 'users'

    if state_filter is None and session.get('documents_acl_state_filter'):
        state_filter = session['documents_acl_state_filter']

    if state_filter not in ['all', 'access', 'no-access']:
        state_filter = 'all'

    if state_filter is not None:
        session['documents_acl_state_filter'] = state_filter

    return render_template('documents/edit_acl.html', asset=asset, pclass_id=pclass.id, url=url, text=text,
                           type=attach_type, attachment=attachment, pane=pane, state_filter=state_filter)


@documents.route('/acl_user_ajax/<int:attach_type>/<int:attach_id>')
@login_required
def acl_user_ajax(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return jsonify({})

    state_filter = request.args.get('state_filter', None)

    if state_filter not in ['all', 'access', 'no-access']:
        state_filter = 'all'

    user_list = db.session.query(User).filter_by(active=True).all()
    role_list = db.session.query(Role).filter(or_(Role.name == 'faculty',
                                                  or_(Role.name == 'student', Role.name == 'office'))).all()

    if state_filter == 'access':
        user_list = [u for u in user_list if asset.has_access(u)]
    elif state_filter == 'no-access':
        user_list = [u for u in user_list if not asset.has_access(u)]

    return ajax.documents.acl_user(user_list, role_list, asset, attachment, attach_type)


@documents.route('/acl_role_ajax/<int:attach_type>/<int:attach_id>')
@login_required
def acl_role_ajax(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return jsonify({})

    state_filter = request.args.get('state_filter', None)

    if state_filter not in ['all', 'access', 'no-access']:
        state_filter = 'all'

    role_list = db.session.query(Role).all()

    if state_filter == 'access':
        role_list = [r for r in role_list if asset.in_role_acl(r)]
    elif state_filter == 'no-access':
        role_list = [r for r in role_list if not asset.in_role_acl(r)]

    return ajax.documents.acl_role(role_list, asset, attachment, attach_type)


@documents.route('/add_user_acl/<int:user_id>/<int:attach_type>/<int:attach_id>')
@login_required
def add_user_acl(user_id, attach_type, attach_id):
    # user_id identifies a user
    user = User.query.get_or_404(user_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.grant_user(user)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not grant access to this asset due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@documents.route('/remove_user_acl/<int:user_id>/<int:attach_type>/<int:attach_id>')
@login_required
def remove_user_acl(user_id, attach_type, attach_id):
    # user_id identifies a user
    user = User.query.get_or_404(user_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.revoke_user(user)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not remove access to this asset due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@documents.route('/add_role_acl/<int:role_id>/<int:attach_type>/<int:attach_id>')
@login_required
def add_role_acl(role_id, attach_type, attach_id):
    # role_id identifies a Role
    role = Role.query.get_or_404(role_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.grant_role(role)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not grant role-based access to this asset due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@documents.route('/remove_role_acl/<int:role_id>/<int:attach_type>/<int:attach_id>')
@login_required
def remove_role_acl(role_id, attach_type, attach_id):
    # role_id identifies a Role
    role = Role.query.get_or_404(role_id)

    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for this project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    try:
        asset.revoke_role(role)
        db.session.commit()
    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        flash('Could not remove role-based access to this asset due to a database error. '
              'Please contact a system administrator', 'error')

    return redirect(redirect_url())


@documents.route('/attachment_download_log/<int:attach_type>/<int:attach_id>')
@login_required
def attachment_download_log(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for ths project class
    if not validate_is_convenor(pclass, message=True):
        return redirect(redirect_url())

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    return render_template('documents/download_log.html', asset=asset, pclass_id=pclass.id, url=url, text=text,
                           type=attach_type, attachment=attachment)


@documents.route('/download_log_ajax/<int:attach_type>/<int:attach_id>')
@login_required
def download_log_ajax(attach_type, attach_id):
    try:
        attachment, asset, pclass = _get_attachment_asset(attach_type, attach_id)
    except KeyError as e:
        abort(404)

    # ensure user is administrator or convenor for ths project class
    if not validate_is_convenor(pclass, message=True):
        return jsonify({})

    return ajax.documents.download_log(asset.downloads.all())
