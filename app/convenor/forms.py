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
    GetPresentationAssessorFaculty, BuildActiveFacultyName, GetActiveAssetLicenses, GetAccommodatableMatchings
from ..shared.forms.mixins import FeedbackMixin, SaveChangesMixin, SubmissionPeriodCommonMixin
from functools import partial


def GoLiveFormFactory(submit_label='Go live', live_and_close_label='Go live and immediately close',
                      datebox_label='Deadline'):

    class GoLiveForm(Form):
        # Go Live
        live = SubmitField(submit_label)

        # go live and close option
        if live_and_close_label is not None:
            live_and_close = SubmitField(live_and_close_label)

        # deadline field
        live_deadline = DateField(datebox_label, format='%d/%m/%Y', validators=[InputRequired()])

        # notify faculty checkbox
        notify_faculty = BooleanField('Send e-mail notifications to faculty')

        # notify selectors checkbox
        notify_selectors = BooleanField('Send e-mail notifications to selectors')

        # accommodate a matching
        accommodate_matching = QuerySelectField('Accommodate existing matching',
                                                query_factory=GetAccommodatableMatchings, get_label='name',
                                                allow_blank=True, blank_text='None')

    return GoLiveForm


def ChangeDeadlineFormFactory(submit_label='Close selections', change_label='Change deadline',
                              datebox_label='The current deadline is'):

    class ChangeDeadlineForm(Form):
        # Close selections
        close = SubmitField(submit_label)

        # Change deadline
        change = SubmitField(change_label)

        # deadline field
        live_deadline = DateField(datebox_label, format='%d/%m/%Y', validators=[InputRequired()])

        # send email notifications to convenor and office contacts?
        notify_convenor = BooleanField('On closure, send e-mail notification to convenor and office staff')

    return ChangeDeadlineForm


def IssueFacultyConfirmRequestFormFactory(submit_label='Issue confirmation requests',
                                          skip_label='Skip confirmation step',
                                          datebox_label='Deadline'):

    class IssueFacultyConfirmRequestForm(Form):

        # deadline for confirmation responses
        request_deadline = DateField(datebox_label, format='%d/%m/%Y', validators=[InputRequired()])

        # skip button, if used
        if skip_label is not None:
            skip_button = SubmitField(skip_label)

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


class PeriodAttachmentMixin():

    description = StringField('Comment', description='Give a short description of the attachment. This will be '
                                                     'included as an explanation if the document is published to '
                                                     'end-users.')

    publish_to_students = BooleanField('Publish this document to students')

    include_marking_emails = BooleanField('Attach this document to marking emails')

    license = QuerySelectField('License', query_factory=GetActiveAssetLicenses, get_label='name',
                               allow_blank=True, blank_text='Unset (no license specified)')


class UploadPeriodAttachmentForm(Form, PeriodAttachmentMixin):

    submit = SubmitField('Upload attachment')


class EditPeriodAttachmentForm(Form, PeriodAttachmentMixin, SaveChangesMixin):

    pass
