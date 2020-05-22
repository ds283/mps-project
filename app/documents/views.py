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
from pathlib import Path
from functools import partial

from flask import render_template, redirect, url_for, flash, request, current_app
from flask_security import login_required, current_user
from sqlalchemy.exc import SQLAlchemyError

from . import documents
from .forms import UploadReportForm, UploadSubmitterAttachmentForm, EditReportForm, EditSubmitterAttachmentForm
from .utils import is_editable, is_deletable, is_listable, is_uploadable

from ..database import db
from ..models import SubmissionRecord, SubmittedAsset, SubmissionAttachment, Role, SubmissionPeriodRecord, \
    ProjectClassConfig, ProjectClass

from ..shared.asset_tools import make_submitted_asset_filename
from ..uploads import submitted_files


@documents.route('/submitter_documents/<int:sid>')
@login_required
def submitter_documents(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    period: SubmissionPeriodRecord = record.period
    config: ProjectClassConfig = period.config
    pclass: ProjectClass = config.project_class

    # editable if marking has not yet commenced (otherwise we are changing the asset after it has already
    # been sent to markers)
    if not is_listable(record, message=True):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    is_admin = current_user.has_role('admin') or current_user.has_role('root') \
        or pclass.is_convenor(current_user.id)

    return render_template('documents/submitter_manager.html', record=record, period=period, url=url, text=text,
                           is_editable=partial(is_editable, record, period=period, config=config, message=False),
                           deletable=is_deletable(record, period, config, message=False), is_admin=is_admin,
                           report_uploadable=is_uploadable(record, message=False, allow_student=False,
                                                           allow_faculty=False),
                           attachment_uploadable=is_uploadable(record, message=False, allow_student=True,
                                                               allow_faculty=True))


@documents.route('/delete_submitter_report/<int:sid>')
@login_required
def delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash('Could not delete report for this submitter because no file has been attached.', 'info')
        return redirect(request.referrer)

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
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
@login_required
def perform_delete_submitter_report(sid):
    # sid is a SubmissionRecord id
    record = SubmissionRecord.query.get_or_404(sid)

    # nothing to do if no report attached
    if record.report is None:
        flash('Could not delete report for this submitter because no file has been attached.', 'info')
        return redirect(request.referrer)

    # validate user has permission to carry out deletions
    if not is_deletable(record, message=True):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    try:
        # set lifetime of uploaded asset to 30 days, after which it will be deleted by the garbage collection.
        # also, unlink asset record from this SubmissionRecord.
        # notice we have to adjust the timestamp, since together with the lifetime this determines the expiry date
        record.report.expiry = datetime.now() + timedelta(days=30)
        record.report_id = None
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
    record = SubmissionRecord.query.get_or_404(sid)

    if record.report is not None:
        flash('Can not upload a report for this submitter because an existing report is already attached.', 'info')
        return redirect(request.referrer)

    # check is convenor for the project's class, or has suitable admin/root privileges
    config = record.owner.config
    pclass = config.project_class
    if not is_uploadable(record, message=True, allow_student=False, allow_faculty=False):
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
                                   expiry=None,
                                   filename=str(subfolder/filename),
                                   target_name=str(incoming_filename),
                                   mimetype=str(report_file.content_type),
                                   license=form.license.data)

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
            else:
                flash('Report "{file}" was successfully uploaded.'.format(file=incoming_filename), 'info')

            return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))

    else:
        if request.method == 'GET':
            form.license.data = current_user.default_license

    return render_template('documents/upload_report.html', record=record, form=form, url=url, text=text)


@documents.route('/edit_submitter_report/<int:sid>', methods=['GET', 'POST'])
@login_required
def edit_submitter_report(sid):
    # sid is a SubmissionRecord id
    record: SubmissionRecord = SubmissionRecord.query.get_or_404(sid)

    # get report asset; if none, nothing to do
    asset: SubmittedAsset = record.report
    if asset is None:
        flash('Could not edit the report for this submission record because it has not yet been attached.', 'info')
        return redirect(request.referrer)

    # verify current user has privileges to edit the report
    if not is_editable(record, asset=asset, message=True, allow_student=False):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    form = EditReportForm(obj=asset)

    if form.validate_on_submit():
        asset.license = form.license.data

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
        return redirect(request.referrer)

    # extract SubmissionRecord and ensure that current user has sufficient privileges to perform edits
    record: SubmissionRecord = attachment.parent
    if not is_editable(record, asset=asset, message=True, allow_student=True):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    form = EditSubmitterAttachmentForm(obj=attachment)

    if form.validate_on_submit():
        attachment.description = form.description.data
        asset.license = form.license.data

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

    action_url = url_for('documents.edit_submitter_attachment', aid=attachment.id, url=url, text=text)
    return render_template('documents/edit_attachment.html', form=form, record=record, attachment=attachment,
                           asset=asset, action_url=action_url)


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
        return redirect(request.referrer)

    record = attachment.parent
    if record is None:
        flash('Can not delete this attachment because it is not attached to a submitter.', 'info')
        return redirect(request.referrer)

    # check user has sufficient privileges to perform the deletion
    if not is_deletable(record, message=True):
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    title = 'Delete project attachment'
    action_url = url_for('documents.perform_delete_submitter_attachment', aid=aid, sid=record.id, url=url, text=text)

    name = asset.target_name if asset.target_name is not None else asset.filename
    message = '<p>Please confirm that you wish to remove the attachment <strong>{name}</strong> for ' \
              '<i class="fa fa-user"></i> {student} {period}.</p>' \
              '<p>This action cannot be undone.</p>'.format(name=name, student=record.owner.student.user.name,
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
        return redirect(request.referrer)

    record = attachment.parent
    if record is None:
        flash('Can not delete this attachment because it is not attached to a submitter.', 'info')
        return redirect(request.referrer)

    # check user has sufficient privileges to perform the deletion
    if not is_deletable(record, message=True):
        return redirect(request.referrer)

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
                                   expiry=None,
                                   filename=str(subfolder/filename),
                                   target_name=str(incoming_filename),
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
            else:
                flash('Attachment "{file}" was successfully uploaded.'.format(file=incoming_filename), 'info')

            return redirect(url_for('documents.submitter_documents', sid=sid, url=url, text=text))

    else:
        if request.method == 'GET':
            form.license.data = current_user.default_license

    return render_template('documents/upload_attachment.html', record=record, form=form, url=url, text=text)
