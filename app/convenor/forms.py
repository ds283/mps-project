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
from wtforms import SubmitField, DateField, IntegerField, StringField, BooleanField, TextAreaField, \
    DateTimeField, SelectField
from wtforms.validators import InputRequired, Optional, Email, Length
from wtforms_alchemy import QuerySelectField

from ..models import DEFAULT_STRING_LENGTH, LiveProject, ProjectClassConfig, ConvenorGenericTask
from ..shared.forms.queries import MarkerQuery, BuildMarkerLabel, GetPresentationFeedbackFaculty, \
    GetPresentationAssessorFaculty, BuildActiveFacultyName, GetActiveAssetLicenses, GetAccommodatableMatchings
from ..shared.forms.mixins import FeedbackMixin, SaveChangesMixin, SubmissionPeriodPresentationsMixin, \
    PeriodSelectorMixinFactory
from ..shared.forms.wtf_validators import NotOptionalIf

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

        # CATS limit before a supervisor is regarded as 'full'
        full_CATS = IntegerField('Maximum number of CATS before a supervisor is full',
                                 description='Optional. If an existing matching is being accommodated, this is '
                                             'the maximum number of CATS that a supervisor can carry before they '
                                             'are regarded as full. Leave blank to use the maximum number of '
                                             'supervisor CATS specified in the matching.',
                                 validators=[Optional()])

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
                            include_send_button=False,
                            include_test_button=False):

    class OpenFeedbackForm(Form):

        # deadline for feedback
        feedback_deadline = DateField(datebox_label, format='%d/%m/%Y', validators=[InputRequired()])

        # CC emails to convenor?
        cc_me = BooleanField('CC myself in notification emails')

        # maximum size of attachments
        max_attachment = IntegerField('Maximum total size of attachments, measured in Mb', validators=[InputRequired()])

        # submit button: test
        if include_test_button:
            test_button = SubmitField('Test notifications')

        # submit button: open feedback
        submit_button = SubmitField(submit_label)

        # if already open, include a 'send notifications' button
        if include_send_button:
            send_notifications = SubmitField('Send notifications')

    return OpenFeedbackForm


class TestOpenFeedbackForm(Form):

    # capture destinations for test emails
    target_email = StringField('Target email address', validators=[InputRequired(), Email()],
                               description='Enter an email address to which the test notification emails '
                                           'will be sent.')

    # submit button
    submit_button = SubmitField('Perform test')


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


class SubmissionRecordSettingsMixin():

    start_date = DateField('Period start date', format='%d/%m/%Y', validators=[Optional()],
                           description="Enter an optional start date for this submission period.")

    hand_in_date = DateField('Hand-in date', format='%d/%m/%Y', validators=[Optional()],
                             description="Enter an optional hand-in date for this submission period. If present, "
                                         "this is used to show students how much time remains.")

    collect_project_feedback = BooleanField('Collect project feedback online')


class EditSubmissionRecordSettingsForm(Form, SubmissionRecordSettingsMixin, SaveChangesMixin):

    pass


class EditSubmissionRecordPresentationsForm(Form, SubmissionPeriodPresentationsMixin, SaveChangesMixin):

    pass


class EditProjectConfigForm(Form, SaveChangesMixin):

    skip_matching = BooleanField('Skip matching',
                                 description='Opt out of automated matching for this academic year')

    requests_skipped = BooleanField('Skip confirmation requests',
                                    description='Disable confirmation of project descriptions for '
                                                'this academic year')

    uses_supervisor = BooleanField('Projects are supervised by a named faculty member',
                                   default=True)

    uses_marker = BooleanField('Submissions are second-marked')

    uses_presentations = BooleanField('Includes one or more assessed presentations')

    display_marker = BooleanField('Include second marker information')

    display_presentations = BooleanField('Include presentation assessment information')

    full_CATS = IntegerField('CAT threshold for supervisors to be full',
                             description='Optional. If a partial match is being accommodated, this is the maximum '
                                         'number of CATS a supervisor can carry before they are regarded '
                                         'as full for the purposes of further allocation. If left blank, '
                                         'the maximum number of CATS is taken from the settings for the '
                                         'matching.',
                             validators=[Optional()])

    CATS_supervision = IntegerField('CATS awarded for project supervision',
                                    validators=[InputRequired(message='Please enter an integer value')])

    CATS_marking = IntegerField('CATS awarded for project 2nd marking',
                                validators=[Optional()])

    CATS_presentation = IntegerField('CATS awarded for assessing presentations',
                                     validators=[Optional()])


def AssignMarkerFormFactory(live_project: LiveProject, uses_marker: bool,
                            config: ProjectClassConfig, is_admin: bool):

    class AssignMarkerForm(Form, PeriodSelectorMixinFactory(config, is_admin)):

        if uses_marker:
            # 2nd marker
            marker = QuerySelectField('Assign 2nd marker', query_factory=partial(MarkerQuery, live_project),
                                      get_label=BuildMarkerLabel, allow_blank=True)

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

    include_marker_emails = BooleanField('Attach this document to marking notifications sent to examiners')

    include_supervisor_emails = BooleanField('Attach this document to marking notifications sent to supervisors')

    license = QuerySelectField('License', query_factory=GetActiveAssetLicenses, get_label='name',
                               allow_blank=True, blank_text='Unset (no license specified)')


class UploadPeriodAttachmentForm(Form, PeriodAttachmentMixin):

    submit = SubmitField('Upload attachment')


class EditPeriodAttachmentForm(Form, PeriodAttachmentMixin, SaveChangesMixin):

    pass


class ConvenorTaskMixin():

    description = StringField('Description', description='Briefly summarize the task',
                              validators=[InputRequired(), Length(max=DEFAULT_STRING_LENGTH)])

    notes = TextAreaField('Notes', description='Add any notes or commentary that you wish to '
                                               'associate with this task',
                          render_kw={"rows": 8}, validators=[Optional()])

    blocking = BooleanField('Task blocks progress to next lifecycle stage',
                            description='Select if the task should block progress, eg. to Go Live or '
                                        'rollover to the next academic year', default=False)

    complete = BooleanField('Task has been completed', default=False,
                            description='Select if the task has been finished.')

    dropped = BooleanField('Task is dropped', default=False,
                           description='Select if the task is no longer required, but should be '
                                       'kept in the database rather than simply deleted.')

    defer_date = DateTimeField('Defer date', format='%d/%m/%Y %H:%M',
                               description='If the task is deferred (that is, is not available to be '
                                           'completed) before some date, enter this here.',
                               validators=[Optional()])

    due_date = DateTimeField('Due date', format='%d/%m/%Y %H:%M',
                             description='If the task is due by a certain date, enter it here.',
                             validators=[Optional()])


class ConvenorGenericTaskMixin():

    repeat = BooleanField('Repeat task')

    repeat_interval = SelectField('Repeat interval', choices=ConvenorGenericTask.repeat_options, coerce=int)

    repeat_frequency = IntegerField('Repeat frequency', validators=[NotOptionalIf('repeat')])

    repeat_from_due_date = BooleanField('Repeat from due date',
                                        description='Select if the due and defer dates of a repeating task '
                                                    'should be calculated from the due date of the '
                                                    'predecessor task, or from its actual completion date.')

    rollover = BooleanField('Rollover with academic year',
                            description='Select if this task should be retained (if not yet complete) when '
                                        'rolling over between academic years.')


class AddConvenorStudentTask(Form, ConvenorTaskMixin):

    submit = SubmitField('Create new task')


class EditConvenorStudentTask(Form, ConvenorTaskMixin, SaveChangesMixin):

    pass


class AddConvenorGenericTask(Form, ConvenorTaskMixin, ConvenorGenericTaskMixin):

    submit = SubmitField('Create new task')


class EditConvenorGenericTask(Form, ConvenorTaskMixin, ConvenorGenericTaskMixin, SaveChangesMixin):

    pass
