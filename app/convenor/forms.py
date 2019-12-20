#
# Created by David Seery on 07/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import SubmitField, DateField, IntegerField, StringField
from wtforms.validators import InputRequired, Optional
from wtforms_alchemy import QuerySelectField

from ..shared.forms.queries import MarkerQuery, BuildMarkerLabel, GetPresentationFeedbackFaculty, \
    GetPresentationAssessorFaculty, BuildActiveFacultyName
from ..shared.forms.mixins import FeedbackMixin, SaveChangesMixin, SubmissionPeriodCommonMixin
from functools import partial


class GoLiveForm(Form):

    # normal Go Live option
    live = SubmitField('Go live')

    # go live and close option
    live_and_close = SubmitField('Go live and immediately close')

    # deadline field
    live_deadline = DateField('Deadline for student submissions', format='%d/%m/%Y', validators=[InputRequired()])


class IssueFacultyConfirmRequestForm(Form):

    # deadline for confirmation responses
    request_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[InputRequired()])

    # submit button: issue requests
    issue_requests = SubmitField('Issue confirmation requests')


class OpenFeedbackForm(Form):

    # deadline for feedback
    feedback_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[InputRequired()])

    # submit button: open feedback
    open_feedback = SubmitField('Open feedback period')


class CustomCATSLimitForm(Form, SaveChangesMixin):

    # custom CATS limit for supervision
    CATS_supervision = IntegerField('Maximum CATS allocated for supervision',
                                    validators=[Optional()])

    # custom CATS limit for marking
    CATS_marking = IntegerField('Maximum CATS allocated for marking',
                                validators=[Optional()])

    # custom CATS limit for presentations
    CATS_presentation = IntegerField('Maximum CATS allocated for presentation assessment',
                                     validators=[Optional()])


class SubmissionRecordMixin():

    start_date = DateField('Period start date', format='%d/%m/%Y', validators=[Optional()])


class EditSubmissionRecordForm(Form, SubmissionRecordMixin, SubmissionPeriodCommonMixin, SaveChangesMixin):

    pass


def AssignMarkerFormFactory(live_project, pclass_id, uses_marker):

    class AssignMarkerForm(Form):

        if uses_marker:
            # 2nd marker
            marker = QuerySelectField('Assign 2nd marker', query_factory=partial(MarkerQuery, live_project),
                                      get_label=BuildMarkerLabel)

    return AssignMarkerForm


def AssignPresentationFeedbackFormFactory(record_id, slot_id):

    if slot_id is None:
        qf = partial(GetPresentationFeedbackFaculty, record_id)
    else:
        qf = partial(GetPresentationAssessorFaculty, record_id, slot_id)

    class AssignPresentationFeedbackForm(Form, FeedbackMixin):


        assessor = QuerySelectField('Assign feedback to assessor',
                                    query_factory=qf,
                                    get_label=BuildActiveFacultyName)

    return AssignPresentationFeedbackForm


class UploadReportForm(Form):

    submit = SubmitField('Upload report')


class UploadAttachmentForm(Form):

    description = StringField('Comment', description='Give a short description of the attachment')

    submit = SubmitField('Upload attachment')
