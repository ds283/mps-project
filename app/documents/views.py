#
# Created by David Seery on 05/01/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from pathlib import Path

from flask import render_template, redirect, url_for, flash, request, current_app
from flask_security import roles_accepted, current_user
from sqlalchemy.exc import SQLAlchemyError

from . import documents
from .forms import UploadReportForm, UploadSubmitterAttachmentForm
from ..database import db
from ..models import SubmissionRecord, SubmittedAsset, SubmissionAttachment, Role

from ..shared.asset_tools import make_submitted_asset_filename
from ..shared.validators import validate_is_convenor
from ..uploads import submitted_files


@documents.route('/submitter_documents/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def submitter_documents(sid):
    # sid is a SubmissionRecord id
    record = SubmissionRecord.query.get_or_404(sid)

    # check is convenor for the project's class
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    return render_template('documents/submitter_manager.html', record=record, url=url, text=text)


@documents.route('/delete_submitter_report/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record = SubmissionRecord.query.get_or_404(sid)

    if record.report is None:
        flash('Could not delete report for this submitter because no file has been attached.', 'info')
        return redirect(request.referrer)

    # check user is convenor for the project's class, or has admin/root privileges
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(request.referrer)

    # check has privileges to handle the asset
    if not record.report.has_access(current_user.id):
        flash('Could not delete report for this submitted because you do not have privileges to access it.', 'info')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    title = 'Delete project report'
    action_url = url_for('documents.perform_delete_submitter_report', sid=sid, url=url, text=text)

    message = '<p>Please confirm that you wish to remove the project report for ' \
              '<i class="fa fa-user"></i> {student} {period}.</p>' \
              '<p>This action cannot be undone.</p>'.format(student=record.owner.student.user.name,
                                                            period=record.period.display_name)
    submit_label = 'Remove report'

    return render_template('admin/danger_confirm.html', title=title, panel_title=title, action_url=action_url,
                           message=message, submit_label=submit_label)


@documents.route('/perform_delete_submitter_report/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def perform_delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record = SubmissionRecord.query.get_or_404(sid)

    if record.report is None:
        flash('Could not delete report for this submitter because no file has been attached.', 'info')
        return redirect(request.referrer)

    # check is convenor for the project's class
    if not validate_is_convenor(record.project.config.project_class):
        return redirect(request.referrer)

    # check has privileges to handle the asset
    if not record.report.has_access(current_user.id):
        flash('Could not delete report for this submitted because you do not have privileges to access it.', 'info')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    try:
        # set lifetime of uploaded asset to 30 days, after which it will be deleted by the garbage collection.
        # also, unlink asset record from this SubmissionRecord.
        # notice we have to adjust the timestamp, since together with the lifetime this determines the expiry date
        record.report.timestamp = datetime.now()
        record.report.lifetime = 30*24*60*60
        record.report_id = None
        db.session.commit()

    except SQLAlchemyError as e:
        flash('Could not remove report from the submission record because of a database error. '
              'Please contact a system administrator.', 'error')
        db.session.rollback()
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))


@documents.route('/upload_submitter_report/<int:sid>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def upload_submitter_report(sid):
    # sid is a SubmissionRecord id
    record = SubmissionRecord.query.get_or_404(sid)

    if record.report is not None:
        flash('Can not upload a report for this submitter because an existing report is already attached.', 'info')
        return redirect(request.referrer)

    # check is convenor for the project's class, or has suitable admin/root privileges
    config = record.owner.config
    pclass = config.project_class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

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
                                   lifetime=None,
                                   filename=str(subfolder/filename),
                                   target_name=str(incoming_filename),
                                   mimetype=str(report_file.content_type))

            try:
                db.session.add(asset)
                db.session.flush()
            except SQLAlchemyError as e:
                flash('Could not upload report due to a database issue. Please contact an administrator.', 'error')
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                return redirect(url_for('documents.submitter_documents', sid=record.sid))

            # attach this asset as the uploaded report
            record.report_id = asset.id

            # uploading user has access
            asset.access_control_list.append(current_user)

            # project convenor has access
            if pclass.convenor is not None and pclass.convenor.user not in asset.access_control_list:
                asset.access_control_list.append(pclass.convenor.user)

            # project supervisor has access
            if record.project is not None and record.project.owner is not None and \
                    record.project.owner.user not in asset.access_control_list:
                asset.access_control_list.append(record.project.owner.user)

            # project examiner has access
            if record.marker is not None and record.marker not in asset.access_control_list:
                asset.access_control_list.append(record.marker.user)

            # student can download their own report
            if record.owner.student.user not in asset.access_control_list:
                asset.access_control_list.append(record.owner.student.user)

            # office staff can download everything
            office_role = db.session.query(Role).filter_by(name='office').first()
            if office_role and office_role not in asset.access_control_roles:
                asset.access_control_roles.append(office_role)

            # TODO: in future, possible add 'moderator', 'exam_board' or 'external_examiner'
            #  roles which should have access to all reports

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                flash('Could not upload report due to a database issue. Please contact an administrator.', 'error')
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            flash('Report "{file}" was successfully uploaded.'.format(file=incoming_filename), 'info')

            return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))

    return render_template('documents/upload_report.html', record=record, form=form, url=url, text=text)


@documents.route('/delete_submitter_attachment/<int:aid>')
@roles_accepted('faculty', 'admin', 'root')
def delete_submitter_attachment(aid):
    # aid is a SubmissionAttachment id
    attachment = SubmissionAttachment.query.get_or_404(aid)

    if attachment.attachment is None:
        flash('Could not delete attachment because of a database error. '
              'Please contact a system administrator.', 'info')
        return redirect(request.referrer)

    # check user is convenor the project class this attachment belongs to, or has admin/root privileges
    record = attachment.parent
    if record is None:
        flash('Can not delete this attachment because it is not attached to a submitter.', 'info')
        return redirect(request.referrer)

    if not validate_is_convenor(record.project.config.project_class):
        return redirect(request.referrer)

    # check has privileges to handle the asset
    if not attachment.attachment.has_access(current_user.id):
        flash('Could not delete attachment because you do not have privileges to access it.', 'info')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    title = 'Delete project attachment'
    action_url = url_for('documents.perform_delete_submitter_attachment', aid=aid, sid=record.id, url=url, text=text)

    name = attachment.attachment.target_name if attachment.attachment.target_name is not None else \
        attachment.attachment.filename
    message = '<p>Please confirm that you wish to remove the attachment <strong>{name}</strong> for ' \
              '<i class="fa fa-user"></i> {student} {period}.</p>' \
              '<p>This action cannot be undone.</p>'.format(name=name, student=record.owner.student.user.name,
                                                            period=record.period.display_name)
    submit_label = 'Remove attachment'

    return render_template('admin/danger_confirm.html', title=title, panel_title=title, action_url=action_url,
                           message=message, submit_label=submit_label)


@documents.route('/perform_delete_submitter_attachment/<int:aid>/<int:sid>')
@roles_accepted('faculty', 'admin', 'root')
def perform_delete_submitter_attachment(aid, sid):
    # aid is a SubmissionAttachment id
    attachment = SubmissionAttachment.query.get_or_404(aid)

    if attachment.attachment is None:
        flash('Could not delete attachment because of a database error. '
              'Please contact a system administrator.', 'info')
        return redirect(request.referrer)

    # check user is convenor the project class this attachment belongs to, or has admin/root privileges
    record = attachment.parent
    if record is None:
        flash('Can not delete this attachment because it is not attached to a submitter.', 'info')
        return redirect(request.referrer)

    if not validate_is_convenor(record.project.config.project_class):
        return redirect(request.referrer)

    # check has privileges to handle the asset
    if not attachment.attachment.has_access(current_user.id):
        flash('Could not delete attachment because you do not have privileges to access it.', 'info')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    try:
        attachment.attachment.timestamp = datetime.now()
        attachment.attachment.lifetime = 30*24*60*60
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
@roles_accepted('faculty', 'admin', 'root')
def upload_submitter_attachment(sid):
    # sid is a SubmissionRecord id
    record = SubmissionRecord.query.get_or_404(sid)

    # check is convenor for the project's class, or has suitable admin/root privileges
    config = record.owner.config
    pclass = config.project_class
    if not validate_is_convenor(pclass):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

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
                                   lifetime=None,
                                   filename=str(subfolder/filename),
                                   target_name=str(incoming_filename),
                                   mimetype=str(attachment_file.content_type))

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

            # uploading user has access
            asset.access_control_list.append(current_user)

            # project convenor has access
            if pclass.convenor is not None and pclass.convenor.user not in asset.access_control_list:
                asset.access_control_list.append(pclass.convenor.user)

            # project supervisor has access
            if record.project is not None and record.project.owner is not None and \
                    record.project.owner.user not in asset.access_control_list:
                asset.access_control_list.append(record.project.owner.user)

            # project examiner has access
            if record.marker is not None and record.marker not in asset.access_control_list:
                asset.access_control_list.append(record.marker.user)

            # students can't ordinarily download unless explicit permission is given

            # office staff can download everything
            office_role = db.session.query(Role).filter_by(name='office').first()
            if office_role and office_role not in asset.access_control_roles:
                asset.access_control_roles.append(office_role)

            # TODO: in future, possible add 'moderator', 'exam_board' or 'external_examiner'
            #  roles which should have access to all attachments (eg. marking reports)

            try:
                db.session.add(attachment)
                db.session.commit()
            except SQLAlchemyError as e:
                flash('Could not upload attachment due to a database issue. '
                      'Please contact an administrator.', 'error')
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

            flash('Attachment "{file}" was successfully uploaded.'.format(file=incoming_filename), 'info')

            return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))

    return render_template('documents/upload_attachment.html', record=record, form=form, url=url, text=text)
