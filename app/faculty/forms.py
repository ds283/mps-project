#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security import current_user
from flask_security.forms import Form
from wtforms import StringField, IntegerField, SelectField, PasswordField, SubmitField, ValidationError, TextAreaField
from wtforms.validators import DataRequired
from wtforms_alchemy.fields import QuerySelectField, QuerySelectMultipleField

from ..models import User, Role, ResearchGroup, DegreeType, DegreeProgramme, TransferableSkill, \
    ProjectClass, Supervisor, Project

from ..fields import EditFormMixin, CheckboxQuerySelectMultipleField


def globally_unique_project(form, field):

    if Project.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project'.format(name=field.data))


def unique_or_original_project(form, field):

    if field.data != form.project.name and Project.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project'.format(name=field.data))


def CurrentUserResearchGroups():

    return ResearchGroup.query.filter(ResearchGroup.active, ResearchGroup.faculty.any(id=current_user.id))


def GetProjectClasses():

    return ProjectClass.query.filter_by(active=True)


def GetSupervisorRoles():

    return Supervisor.query.filter_by(active=True)


class ProjectMixin():

    keywords = StringField('Keywords', description='Optional. Separate with commas or semicolons.')

    group = QuerySelectField('Research group', query_factory=CurrentUserResearchGroups, get_label='name')

    # allow the project_class list to be empty (byt then the project is not offered)
    project_classes = CheckboxQuerySelectMultipleField('Project classes',
                                                       query_factory=GetProjectClasses, get_label='name')

    meeting_options = [(Project.MEETING_REQUIRED, "Meeting required"), (Project.MEETING_OPTIONAL, "Meeting optional"),
                       (Project.MEETING_NONE, "Prefer not to meet")]
    meeting = SelectField('Meeting required?', choices=meeting_options, coerce=int)

    # allow team to be empty (but then the project is not offered)
    team = CheckboxQuerySelectMultipleField('Supervisory team',
                                            query_factory=GetSupervisorRoles, get_label='name')

    description = TextAreaField('Project description', render_kw={"rows": 20},
                                validators=[DataRequired(message='A project description is required')])

    reading = TextAreaField('Recommended reading', render_kw={"rows": 10},)


class AddProjectForm(Form, ProjectMixin):

    name = StringField('Title', validators=[DataRequired(message='Project title is required'),
                                            globally_unique_project])

    submit = SubmitField('Add new project')


class EditProjectForm(Form, ProjectMixin, EditFormMixin):

    name = StringField('Title', validators=[DataRequired(message='Project title is required'),
                                            unique_or_original_project])

    pass
