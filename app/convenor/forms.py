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
from wtforms import SubmitField, DateField, IntegerField, StringField, BooleanField
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


def IssueFacultyConfirmRequestFormFactory(submit_label='Issue confirmation requests',
                                          datebox_label='Deadline'):

    class IssueFacultyConfirmRequestForm(Form):

        # deadline for confirmation responses
        request_deadline = DateField(datebox_label, format='%d/%m/%Y', validators=[InputRequired()])

        # submit button: issue requests
        submit_button = SubmitField(submit_label)

    return IssueFacultyConfirmRequestForm


def OpenFeedbackFormFactory(submit_label='Open feedback period',
                            datebox_label='Deadline',
                            include_send_button=False):

    class OpenFeedbackForm(Form):

        # deadline for feedback
        feedback_deadline = DateField(datebox_label, format='%d/%m/%Y', validators=[InputRequired()])

        # CC emails to convenor?
        cc_me = BooleanField('CC myself in notification emails')

        # submit button: open feedback
        submit_button = SubmitField(submit_label)

        # if already open, include a 'send notifications' button
        if include_send_button:
            send_notifications = SubmitField('Send notifications')

    return OpenFeedbackForm


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


class UploadSubmitterAttachmentForm(Form):

    description = StringField('Comment', description='Give a short description of the attachment')

    submit = SubmitField('Upload attachment')


class PeriodAttachmentMixin():

    description = StringField('Comment', description='Give a short description of the attachment. This will be '
                                                     'included as an explanation if the document is published to '
                                                     'end-users.')

    publish_to_students = BooleanField('Publish this document to students')

    include_marking_emails = BooleanField('Attach this document to marking emails')


class UploadPeriodAttachmentForm(Form, PeriodAttachmentMixin):

    submit = SubmitField('Upload attachment')


class EditPeriodAttachmentForm(Form, PeriodAttachmentMixin, SaveChangesMixin):

    pass
