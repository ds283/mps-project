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
from wtforms import StringField, IntegerField, SelectField, SubmitField, ValidationError, \
    TextAreaField, DateField, BooleanField
from wtforms.validators import DataRequired, Optional
from wtforms_alchemy.fields import QuerySelectField

from ..models import db, ResearchGroup, ProjectClass, Supervisor, Project, EnrollmentRecord, SkillGroup, \
    ProjectDescription

from ..shared.forms.fields import EditFormMixin, CheckboxQuerySelectMultipleField

from ..shared.forms.queries import GetActiveFaculty, BuildActiveFacultyName


def globally_unique_project(form, field):

    if Project.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project'.format(name=field.data))


def unique_or_original_project(form, field):

    if field.data != form.project.name and Project.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project'.format(name=field.data))


def project_unique_label(form, field):

    if ProjectDescription.query.filter_by(parent_id=form.project_id, label=field.data).first():
        raise ValidationError('{name} is already used as a label for this project'.format(name=field.data))


def project_unique_or_original_label(form, field):

    if field.data != form.desc.label and ProjectDescription.query \
            .filter_by(parent_id=form.project_id, label=field.data).first():
        raise ValidationError('{name} is already used as a label for this project'.format(name=field.data))


def CurrentUserResearchGroups():

    return ResearchGroup.query.filter(ResearchGroup.active, ResearchGroup.faculty.any(id=current_user.id))


def AllResearchGroups():

    return ResearchGroup.query.filter_by(active=True)


def CurrentUserProjectClasses():

    # build list of enrollment records for the current user
    sq = EnrollmentRecord.query.filter_by(owner_id=current_user.id).subquery()

    # join to project class table
    return db.session.query(ProjectClass).join(sq, sq.c.pclass_id == ProjectClass.id)


def AllProjectClasses():

    return ProjectClass.query.filter_by(active=True)


def GetProjectClasses():

    return ProjectClass.query.filter_by(active=True)


def GetSupervisorRoles():

    return Supervisor.query.filter_by(active=True)


def GetSkillGroups():

    return SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc())


class DescriptionMixin():

    # allow the project_class list to be empty (but then the project is not offered)
    project_classes = CheckboxQuerySelectMultipleField('Project classes',
                                                       query_factory=CurrentUserProjectClasses, get_label='name')

    capacity = IntegerField('Maximum capacity', description='Optional. Used only if project-level option to enforce '
                                                            'capacity is selected',
                            validators=[Optional()])

    # allow team to be empty (but then the project is not offered)
    team = CheckboxQuerySelectMultipleField('Supervisory team',
                                            query_factory=GetSupervisorRoles, get_label='name')

    description = TextAreaField('Project description', render_kw={"rows": 20},
                                description=r'Enter a description of your project. '
                                            r'The LaTeX mathematics environments are supported, as are common LaTeX commands. '
                                            r'The amsmath, amsthm, and amssymb packages are included. '
                                            r'You may use displayed or inline mathematics. '
                                            r'You may also use Markdown syntax to format your description. '
                                            r'<strong>Please preview your project to check it renders correctly.</strong>',
                                validators=[DataRequired(message='A project description is required')])

    reading = TextAreaField('Recommended reading', render_kw={"rows": 10},
                            description='Optional. The same styling and LaTeX options are available. '
                                        'To embed internet links, use the Markdown syntax [link text](URL).')


class ProjectMixin():

    owner = QuerySelectField('Project owner', query_factory=GetActiveFaculty, get_label=BuildActiveFacultyName)

    keywords = StringField('Keywords', description='Optional. Separate with commas or semicolons.')

    group = QuerySelectField('Research group', query_factory=CurrentUserResearchGroups, get_label='name')

    # allow the project_class list to be empty (but then the project is not offered)
    project_classes = CheckboxQuerySelectMultipleField('Project classes',
                                                       query_factory=CurrentUserProjectClasses, get_label='name')

    meeting_options = [(Project.MEETING_REQUIRED, "Meeting required"), (Project.MEETING_OPTIONAL, "Meeting optional"),
                       (Project.MEETING_NONE, "Prefer not to meet")]
    meeting_reqd = SelectField('Meeting required?', choices=meeting_options, coerce=int)

    enforce_capacity = BooleanField('Enforce maximum capacity')

    # popularity display

    show_popularity = BooleanField('Show popularity estimate')

    show_bookmarks = BooleanField('Show number of bookmarks')

    show_selections = BooleanField('Show number of selections')


class AddProjectForm(Form, ProjectMixin):

    def __init__(self,  *args, **kwargs):

        convenor_editing = False
        if 'convenor_editing' in kwargs:
            convenor_editing = True
            del kwargs['convenor_editing']

        super().__init__(*args, **kwargs)

        if convenor_editing:
            self.project_classes.query_factory = AllProjectClasses
            self.group.query_factory = AllResearchGroups

    name = StringField('Title', validators=[DataRequired(message='Project title is required'),
                                            globally_unique_project])

    submit = SubmitField('Add new project')

    submit_and_preview = SubmitField('Add new project and preview')


class EditProjectForm(Form, ProjectMixin, EditFormMixin):

    def __init__(self, *args, **kwargs):

        convenor_editing = False
        if 'convenor_editing' in kwargs:
            convenor_editing = True
            del kwargs['convenor_editing']

        super().__init__(*args, **kwargs)

        if convenor_editing:
            self.project_classes.query_factory = AllProjectClasses
            self.group.query_factory = AllResearchGroups

    name = StringField('Title', validators=[DataRequired(message='Project title is required'),
                                            unique_or_original_project])

    submit_and_preview = SubmitField('Save changes and preview')


class AddDescriptionForm(Form, DescriptionMixin):

    label = StringField('Label', validators=[DataRequired(message='Please enter a label to identify this description'),
                                             project_unique_label])

    submit = SubmitField('Add new project')


class EditDescriptionForm(Form, DescriptionMixin, EditFormMixin):

    label = StringField('Label', validators=[DataRequired(message='Please enter a label to identify this description'),
                                             project_unique_or_original_label])


class RolloverForm(Form):

    rollover = SubmitField('Rollover')


class GoLiveForm(Form):

    live = SubmitField('Go live')
    live_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[DataRequired()])


class CloseStudentSelectionsForm(Form):

    close = SubmitField('Close student selections')


class IssueFacultyConfirmRequestForm(Form):

    requests_issued = SubmitField('Issue confirmation requests')
    request_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[DataRequired()])


class ConfirmAllRequestsForm(Form):

    confirm_all = SubmitField('Confirm all outstanding projects')


class SkillSelectorMixin():

    selector = QuerySelectField('Skill group', query_factory=GetSkillGroups, get_label='name')


class SkillSelectorForm(Form, SkillSelectorMixin):

    pass
