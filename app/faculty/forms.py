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
from wtforms import StringField, IntegerField, SelectField, PasswordField, SubmitField, ValidationError, \
    TextAreaField, DateField
from wtforms.validators import DataRequired
from wtforms_alchemy.fields import QuerySelectField, QuerySelectMultipleField

from ..models import User, Role, ResearchGroup, DegreeType, DegreeProgramme, TransferableSkill, \
    ProjectClass, Supervisor, Project

from ..fields import EditFormMixin, CheckboxQuerySelectMultipleField

from ..admin.forms import GetActiveFaculty, BuildUserRealName

def globally_unique_project(form, field):

    if Project.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project'.format(name=field.data))


def unique_or_original_project(form, field):

    if field.data != form.project.name and Project.query.filter_by(name=field.data).first():
        raise ValidationError('{name} is already associated with a project'.format(name=field.data))


def CurrentUserResearchGroups():

    return ResearchGroup.query.filter(ResearchGroup.active, ResearchGroup.faculty.any(id=current_user.id))


def AllResearchGroups():

    return ResearchGroup.query.filter_by(active=True)


def CurrentUserProjectClasses():

    return ProjectClass.query.filter(ProjectClass.active, ProjectClass.enrolled_faculty.any(id=current_user.id))


def AllProjectClasses():

    return ProjectClass.query.filter_by(active=True)


def GetProjectClasses():

    return ProjectClass.query.filter_by(active=True)


def GetSupervisorRoles():

    return Supervisor.query.filter_by(active=True)


class ProjectMixin():

    owner = QuerySelectField('Project owner', query_factory=GetActiveFaculty, get_label=BuildUserRealName)

    keywords = StringField('Keywords', description='Optional. Separate with commas or semicolons.')

    group = QuerySelectField('Research group', query_factory=CurrentUserResearchGroups, get_label='name')

    # allow the project_class list to be empty (byt then the project is not offered)
    project_classes = CheckboxQuerySelectMultipleField('Project classes',
                                                       query_factory=CurrentUserProjectClasses, get_label='name')

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

    pass


class ConvenorDashboardForm(Form):

    rollover = SubmitField('Rollover')

    live = SubmitField('Go live')
    live_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[DataRequired()])

    close = SubmitField('Close student options')

    requests_issued = SubmitField('Issue confirmation requests')
    request_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[DataRequired()])

    confirm_all = SubmitField('Confirm all outstanding projects')


    def sanitize(self, current_year, config):
        """
        Remove unneeded buttons to avoid security risks
        :param current_year:
        :param config:
        :return:
        """

        # rollover button is not used if config is up-to-date
        if config.year >= current_year:

            del self.rollover

        if config.project_class.require_confirm and not config.requests_issued:

            # form offers to issue confirmation requests
            del self.confirm_all, self.live, self.live_deadline, self.close

        else:

            if config.live and config.closed:

                # form offers no choices at all
                del self.requests_issued, self.request_deadline, self.live, \
                    self.live_deadline, self.confirm_all, self.close

            elif config.open:

                # form offers to close student choices
                del self.requests_issued, self.request_deadline, self.confirm_all, \
                    self.live, self.live_deadline

            elif not config.live:

                if config.project_class.require_confirm:

                    # if we get here then we can assume requests have been issued, because of the outermost if

                    if config.golive_required.count() == 0:

                        # form offers to go live
                        del self.requests_issued, self.request_deadline, self.confirm_all, self.close

                    else:

                        # form offers to force confirm all, and to adjust the request deadline
                        del self.live, self.live_deadline, self.close
                        self.requests_issued.label.text = 'Save changes'
                        self.request_deadline.label.text = 'Adjust current deadline'

                else:

                    # no confirmations required, so form offers to go live
                    del self.requests_issued, self.requests_issued, self.confirm_all, self.close
