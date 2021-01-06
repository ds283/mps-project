#
# Created by David Seery on 05/01/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask_security.forms import Form
from wtforms import SubmitField, StringField, BooleanField, SelectField
from wtforms.validators import InputRequired
from wtforms_alchemy import QuerySelectField

from ..shared.forms.mixins import SaveChangesMixin
from ..shared.forms.queries import GetActiveAssetLicenses

from ..models import SubmissionAttachment


class LicenseMixin():

    license = QuerySelectField('License', query_factory=GetActiveAssetLicenses, get_label='name',
                               allow_blank=True, blank_text='Unset (no license specified)')


class DownloadableAttachmentMixin():

    target_name = StringField('Filename', description='The externally-visible filename used for this attachment',
                              validators=[InputRequired()])


class UploadReportForm(Form, LicenseMixin, DownloadableAttachmentMixin):

    submit = SubmitField('Upload report')


class EditReportForm(Form, LicenseMixin, DownloadableAttachmentMixin, SaveChangesMixin):

    pass


def AttachmentMixinFactory(admin=False):

    class AttachmentMixin():

        description = StringField('Comment', description='Give a short description of the attachment')

        if admin:
            _types = [(SubmissionAttachment.ATTACHMENT_TYPE_UNSET, "Unset"),
                      (SubmissionAttachment.ATTACHMENT_MARKING_REPORT, "Marking report"),
                      (SubmissionAttachment.ATTACHMENT_SIMILARITY_REPORT, "Similarity report (such as Turnitin"),
                      (SubmissionAttachment.ATTACHMENT_OTHER, "Other")]
            type = SelectField('Attachment type', choices=_types, coerce=int)

            publish_to_students = BooleanField('Publish this document to students')

            include_marker_emails = BooleanField('Attach this document to marking notifications sent to examiners')

            include_supervisor_emails = BooleanField('Attach this document to marking notifications sent to supervisors')

    return AttachmentMixin


def UploadSubmitterAttachmentFormFactory(admin=False):

    AttachmentMixin = AttachmentMixinFactory(admin=admin)

    class UploadSubmitterAttachmentForm(Form, LicenseMixin, AttachmentMixin, DownloadableAttachmentMixin):

        submit = SubmitField('Upload attachment')

    return UploadSubmitterAttachmentForm


def EditSubmitterAttachmentFormFactory(admin=False):

    AttachmentMixin = AttachmentMixinFactory(admin=admin)

    class EditSubmitterAttachmentForm(Form, LicenseMixin, AttachmentMixin, DownloadableAttachmentMixin, SaveChangesMixin):

        pass

    return EditSubmitterAttachmentForm
