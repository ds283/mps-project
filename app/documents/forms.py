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
from wtforms import SubmitField, StringField
from wtforms.validators import InputRequired
from wtforms_alchemy import QuerySelectField

from ..shared.forms.mixins import SaveChangesMixin
from ..shared.forms.queries import GetActiveAssetLicenses


class UploadMixin():

    license = QuerySelectField('License', query_factory=GetActiveAssetLicenses, get_label='name',
                               allow_blank=True, blank_text='Unset (no license specified)')


class DownloadableAttachmentMixin():

    target_name = StringField('Filename', description='The externally-visible filename used for this attachment',
                              validators=[InputRequired()])


class UploadReportForm(Form, UploadMixin, DownloadableAttachmentMixin):

    submit = SubmitField('Upload report')


class EditReportForm(Form, UploadMixin, DownloadableAttachmentMixin, SaveChangesMixin):

    pass


class AttachmentMixin(UploadMixin):

    description = StringField('Comment', description='Give a short description of the attachment')


class UploadSubmitterAttachmentForm(Form, AttachmentMixin, DownloadableAttachmentMixin):

    submit = SubmitField('Upload attachment')


class EditSubmitterAttachmentForm(Form, AttachmentMixin, DownloadableAttachmentMixin, SaveChangesMixin):

    pass
