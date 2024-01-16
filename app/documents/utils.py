#
# Created by David Seery on 06/01/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import flash
from flask_login import current_user

from ..models import SubmissionRecord, SubmissionPeriodRecord, ProjectClassConfig, SubmittedAsset


def is_editable(
    record: SubmissionRecord,
    period: SubmissionPeriodRecord = None,
    config: ProjectClassConfig = None,
    message: bool = False,
    asset: SubmittedAsset = None,
    allow_student: bool = True,
):
    # 'root', 'admin' and 'office' users can always edit SubmissionRecord data
    if current_user.has_role("root") or current_user.has_role("admin") or current_user.has_role("office"):
        return True

    if current_user.has_role("faculty"):
        # a SubmissionRecord is editable if the user is 'convenor' for the project class
        period = period or record.period
        config = config or period.config
        pclass = config.project_class

        if pclass.is_convenor(current_user.id):
            return True

        if message:
            flash("Only the project convenor can edit documents attached to this submission record", "info")

        return False

    # below this point in the privilege hierarchy, editing is not possible if the period is already closed
    if period.closed:
        return False

    if current_user.has_role("student") and allow_student:
        # students can edit assets that they have uploaded, but not a SubmissionRecord as a whole
        if asset is not None and asset.uploaded_by is not None:
            if current_user.id == asset.uploaded_by.id:
                return True

        if message:
            flash("It is not possible to edit this document. You can only edit documents that you have uploaded yourself.", "info")

        return False

    if message:
        flash("You do not have sufficient privileges to edit the documents attached to this submission record", "info")

    return False


def is_deletable(record, period=None, config=None, message=False):
    # 'root' and 'admin' users can always delete documents from a SubmissionRecord
    if current_user.has_role("root") or current_user.has_role("admin"):
        return True

    period = period or record.period
    config = config or period.config
    pclass = config.project_class

    # otherwise, the project covenor can delete documents from a SubmissionRecord if we are not yet marking
    if not pclass.is_convenor(current_user.id):
        if message:
            flash("Only the project convenor can delete documents attached to this submission record", "info")

        return False

    if period.closed:
        if message:
            flash(
                "It is no longer possible to delete documents attached to this submission record, "
                "because the submission period to which it is attached been closed. A user with admin "
                "privileges can still remove attachments if this is necessary.",
                "info",
            )

        return False

    state = config.submitter_lifecycle
    if state >= config.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY:
        if message:
            flash(
                "It is no longer possible to delete documents attached to this submission record, "
                "because the marking and feedback phase is now underway for the submission period "
                "to which it is attached. A user with admin privileges can still remove attachments "
                "if this is necessary.",
                "info",
            )

        return False

    return True


def is_listable(record, message=False):
    """
    Determine whether the currently logged-in user has permissions to view the documents attached to
    a SubmissionRecord
    :param record:
    :param message:
    :return:
    """
    # 'root', 'admin', 'faculty' and 'office' users can always list the documents attached to a SubmissionRecord
    if current_user.has_role("root") or current_user.has_role("admin") or current_user.has_role("faculty") or current_user.has_role("office"):
        return True

    # 'student' users can only list the documents attached if they are the submitter
    if current_user.has_role("student"):
        if current_user.id == record.owner.student.id:
            return True

        if message:
            flash("It is only possible to view the documents attached to this submission record if you are the submitter.", "info")

        return False

    if message:
        flash("You do not have sufficient privileges to view the documents attached to this submission record", "info")

    return False


def is_uploadable(record, message=False, allow_student=True, allow_faculty=True):
    """
    Determine whether the currently logged-in user has permissions to upload a document to a SubmissionRecord
    :param allow_faculty:
    :param record:
    :param message:
    :param allow_student:
    :return:
    """
    # 'root', 'admin', 'faculty' and 'office' users can always upload new documents to a SubmissionRecord
    if current_user.has_role("root") or current_user.has_role("admin") or current_user.has_role("office"):
        return True

    if current_user.has_role("faculty"):
        if allow_faculty:
            return True

        if message:
            flash(
                "You do not have sufficient privileges to attach documents to this submission record. "
                "Please contact the convenor or an administrator to arrange for documents to be uploaded.",
                "info",
            )

        return False

    # 'student' users can only list the documents attached if they are the submitter
    if current_user.has_role("student"):
        if not allow_student:
            if message:
                flash("You do not have sufficient privileges to attach documents to this submission record.", "info")

            return False

        if current_user.id == record.owner.student.id:
            return True

        if message:
            flash("It is only possible to attach documents to this submission record if you are the submitter.", "info")

        return False

    if message:
        flash("You do not have sufficient privileges to attach documents to this submission record.", "info")

    return False


def is_processable(record, period=None, config=None, message=False):
    """
    Determine whether the currently logged-in user has permission to initiate processing of a report
    :param record:
    :param message:
    :param allow_faculty:
    :return:
    """
    # 'root' and 'admin' users can always initiate procssing
    if current_user.has_role("root") or current_user.has_role("admin"):
        return True

    period = period or record.period
    config = config or period.config
    pclass = config.project_class

    # otherwise, the project covenor can initiate processig
    if not pclass.is_convenor(current_user.id):
        if message:
            flash("Only the project convenor can initiate generation of a processed report", "info")

        return False


def is_admin(current_user):
    if current_user.has_role("root") or current_user.has_role("admin"):
        return True

    if current_user.has_role("office"):
        return True

    if current_user.has_role("faculty"):
        return True

    return False
