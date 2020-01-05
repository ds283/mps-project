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
from wtforms import SubmitField, DateField, IntegerField, StringField, BooleanField
from wtforms.validators import InputRequired, Optional
from wtforms_alchemy import QuerySelectField

from ..shared.forms.queries import MarkerQuery, BuildMarkerLabel, GetPresentationFeedbackFaculty, \
    GetPresentationAssessorFaculty, BuildActiveFacultyName, GetActiveAssetLicenses
from ..shared.forms.mixins import FeedbackMixin, SaveChangesMixin, SubmissionPeriodCommonMixin
from functools import partial


class UploadReportForm(Form):

    submit = SubmitField('Upload report')


class UploadSubmitterAttachmentForm(Form):

    description = StringField('Comment', description='Give a short description of the attachment')

    submit = SubmitField('Upload attachment')