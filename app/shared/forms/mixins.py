#
# Created by David Seery on 2018-10-16.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from wtforms import SubmitField, StringField, SelectField, BooleanField, IntegerField
from wtforms.validators import InputRequired, Optional

from ...models import theme_choices, academic_titles
from .wtf_validators import valid_username, unique_or_original_username, NotOptionalIf


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


def FacultyDataMixinFactory(admin=False):

    class FacultyDataMixin():

        academic_title = SelectField('Academic title', choices=academic_titles, coerce=int)

        use_academic_title = BooleanField('Use academic title', default=True,
                                          description='Prefix your name with Dr, Professor or similar in student-facing web pages.')

        sign_off_students = BooleanField('Ask to confirm student meetings', default=True,
                                         description='If meetings are required before project selection, '
                                                     'confirmation is needed before allowing students to sign up.')

        enforce_capacity = BooleanField('Enforce maximum capacity', default=True,
                                        description='By default, enforce limits on project capacity during assignment')

        project_capacity = IntegerField('Default project capacity',
                                        description='Default number of students that can be assigned to a project',
                                        validators=[NotOptionalIf(enforce_capacity)])

        show_popularity = BooleanField('Show popularity indicators', default=True,
                                       description='By default, show popularity indicators on project webpages')

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