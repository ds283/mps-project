#
# Created by David Seery on 2018-10-16.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from functools import partial

from wtforms import SubmitField, StringField, SelectField, BooleanField, IntegerField, TextAreaField
from wtforms.validators import InputRequired, Optional, Length
from wtforms_alchemy import QuerySelectField

from ...models import theme_choices, academic_titles, email_freq_choices, DEFAULT_STRING_LENGTH, ProjectClassConfig
from .wtf_validators import valid_username, unique_or_original_username, NotOptionalIf

from .queries import GetActiveAssetLicenses, GetSubmissionRecords, BuildSubmissionRecordLabel


class SaveChangesMixin():

    submit = SubmitField('Save changes')


class EditUserNameMixin():

    username = StringField('Username', validators=[InputRequired(message='Username is required'),
                                                   valid_username, unique_or_original_username])


class FirstLastNameMixin():

    first_name = StringField('First name', validators=[InputRequired(message='First name is required')])

    last_name = StringField('Last or family name', validators=[InputRequired(message='Last name is required')])


class ThemeMixin():

    theme = SelectField('Theme', choices=theme_choices, coerce=int)


class DefaultLicenseMixin():

    default_license = QuerySelectField('Default license for content I upload',
                                       query_factory=GetActiveAssetLicenses, get_label='name',
                                       allow_blank=True, blank_text='Unset (no license specified)')


class EmailSettingsMixin():

    group_summaries = BooleanField('Group notifications into summaries')

    summary_frequency = SelectField('Frequency of summaries', choices=email_freq_choices, coerce=int)


def FacultyDataMixinFactory(admin=False):

    class FacultyDataMixin():

        academic_title = SelectField('Academic title', choices=academic_titles, coerce=int)

        use_academic_title = BooleanField('Use academic title', default=True,
                                          description='Prefix your name with Dr, Professor or similar in student-facing web pages.')

        # project defaults

        sign_off_students = BooleanField('Ask to confirm student meetings', default=True,
                                         description='If meetings are required before project selection, '
                                                     'confirmation is needed before allowing students to sign up.')

        enforce_capacity = BooleanField('Enforce maximum capacity', default=True,
                                        description='By default, enforce limits on project capacity during assignment')

        project_capacity = IntegerField('Default project capacity',
                                        description='Default number of students that can be assigned to a project',
                                        validators=[NotOptionalIf('enforce_capacity')])

        show_popularity = BooleanField('Show popularity indicators', default=True,
                                       description='By default, show popularity indicators on project webpages')

        dont_clash_presentations = BooleanField("Don't schedule presentations with other students taking "
                                                "the same project", default=True,
                                                description='Please consider disabling this setting if possible. '
                                                            'This makes scheduling presentations easier.')

        office = StringField('Office', validators=[InputRequired(message='Please enter your office details to help '
                                                                         'students find you')])

        if admin:
            CATS_supervision = IntegerField('Guideline number of CATS available for project supervision',
                                            description='Leave blank for default assignment',
                                            validators=[Optional()])

            CATS_marking = IntegerField('Guideline number of CATS available for marking',
                                        description='Leave blank for default assignment',
                                        validators=[Optional()])

            CATS_presentation = IntegerField('Guideline number of CATS available for presentation assessment',
                                             description='Leave blank for default assignment',
                                             validators=[Optional()])

    return FacultyDataMixin


class FeedbackMixin():

    positive = TextAreaField('Positive aspects', render_kw={"rows": 10},
                             description='Your feedback can be structured using Markdown, or use LaTeX formatting '
                                         'and mathematical markup. The display uses the same rendering pipeline '
                                         'used for project descriptions, so anything that works there will work here. '
                                         'You can preview your feedback before submitting it.')

    negative = TextAreaField('Negative aspects', render_kw={"rows": 10})

    save_feedback = SubmitField('Save changes')


class SubmissionPeriodCommonMixin():

    has_presentation = BooleanField('This submission period includes a presentation assessment')

    number_assessors = IntegerField('Number of assessors per group', default=2,
                                    description='Enter the number of faculty assessors scheduled per group during '
                                                'the presentation assessment',
                                    validators=[NotOptionalIf('has_presentation')])

    lecture_capture = BooleanField('The presentation assessment requires a venue with lecture capture')

    max_group_size = IntegerField('Maximum group size', default=5,
                                  description='Enter the desired maximum group size. Some groups may be smaller '
                                              'if this is required.',
                                  validators=[NotOptionalIf('has_presentation')])

    morning_session = StringField('Times for morning session',
                                  description='e.g. 10am-12pm', validators=[NotOptionalIf('has_presentation'),
                                                                            Length(max=DEFAULT_STRING_LENGTH)])

    afternoon_session = StringField('Times for afternoon session',
                                    description='e.g. 2pm-4pm', validators=[NotOptionalIf('has_presentation'),
                                                                            Length(max=DEFAULT_STRING_LENGTH)])

    talk_format = StringField('Specify talk format',
                              description='e.g. 15 mins + 3 mins for questions',
                              validators=[NotOptionalIf('has_presentation'),
                                          Length(max=DEFAULT_STRING_LENGTH)])

    collect_presentation_feedback = BooleanField('Collect presentation feedback online')

    collect_project_feedback = BooleanField('Collect project feedback online')


def PeriodSelectorMixinFactory(config: ProjectClassConfig, is_admin: bool):

    class PeriodSelectorMixin():

        # only include selector if user has admin privileges
        if is_admin:
            selector = QuerySelectField('Select submission period', query_factory=partial(GetSubmissionRecords, config),
                                        get_label=BuildSubmissionRecordLabel)

    return PeriodSelectorMixin