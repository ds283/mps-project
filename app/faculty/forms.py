#
# Created by David Seery on 15/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import StringField, IntegerField, SelectField, SubmitField, TextAreaField, BooleanField
from wtforms.validators import InputRequired, Optional
from wtforms_alchemy.fields import QuerySelectField

from ..models import Project

from ..shared.forms.fields import EditFormMixin, CheckboxQuerySelectMultipleField
from ..shared.forms.wtf_validators import globally_unique_project, unique_or_original_project, project_unique_label, \
    project_unique_or_original_label
from ..shared.forms.queries import GetActiveFaculty, BuildActiveFacultyName, CurrentUserResearchGroups, \
    AllResearchGroups, CurrentUserProjectClasses, AllProjectClasses, GetSupervisorRoles, GetSkillGroups, \
    AvailableProjectDescriptionClasses, ProjectDescriptionClasses

from functools import partial


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

    name = StringField('Title', validators=[InputRequired(message='Project title is required'),
                                            globally_unique_project])

    submit = SubmitField('Next: Project descriptions')

    save_and_exit = SubmitField('Save and exit')

    save_and_preview = SubmitField('Save and preview')


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

    name = StringField('Title', validators=[InputRequired(message='Project title is required'),
                                            unique_or_original_project])

    save_and_preview = SubmitField('Save changes and preview')


class DescriptionMixin():

    # allow the project_class list to be empty (but then the project is not offered)
    project_classes = CheckboxQuerySelectMultipleField('Project classes',
                                                       query_factory=CurrentUserProjectClasses, get_label='name')

    capacity = IntegerField('Maximum student capacity',
                            description='Optional. Used only if project-level option to enforce capacity is selected. '
                                        'Note this refers to the number of assigned students, not your CATS assignment.',
                            validators=[Optional()])

    # allow team to be empty (but then the project is not offered)
    team = CheckboxQuerySelectMultipleField('Supervisory team',
                                            query_factory=GetSupervisorRoles, get_label='name')

    description = TextAreaField('Project description', render_kw={"rows": 15},
                                description=r'Enter a description of your project. '
                                            r'The LaTeX mathematics environments are supported, as are common LaTeX commands. '
                                            r'The amsmath, amsthm, and amssymb packages are included. '
                                            r'You may use displayed or inline mathematics. '
                                            r'You may also use Markdown syntax to format your description. '
                                            r'<strong>Please preview your project to check it renders correctly.</strong>',
                                validators=[InputRequired(message='A project description is required')])

    reading = TextAreaField('Recommended reading', render_kw={"rows": 7},
                            description='Optional. The same styling and LaTeX options are available. '
                                        'To embed internet links, use the Markdown syntax [link text](URL).')


class AddDescriptionForm(Form, DescriptionMixin):

    def __init__(self, project_id, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.project_classes.query_factory = partial(AvailableProjectDescriptionClasses, project_id, None)


    label = StringField('Label', validators=[InputRequired(message='Please enter a label to identify this description'),
                                             project_unique_label],
                        description='Enter a short label to identify this description in the list. '
                                    'The label will not be visible to students.')

    submit = SubmitField('Add new description')


class EditDescriptionForm(Form, DescriptionMixin, EditFormMixin):

    def __init__(self, project_id, desc_id, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.project_classes.query_factory = partial(AvailableProjectDescriptionClasses, project_id, desc_id)

    label = StringField('Label', validators=[InputRequired(message='Please enter a label to identify this description'),
                                             project_unique_or_original_label],
                        description='Enter a short label to identify this description in the list. '
                                    'The label will not be visible to students.')


class SkillSelectorMixin():

    selector = QuerySelectField('Skill group', query_factory=GetSkillGroups, get_label='name')


class SkillSelectorForm(Form, SkillSelectorMixin):

    pass


class DescriptionSelectorMixin():

    selector = QuerySelectField('Show project preview for', query_factory=ProjectDescriptionClasses, get_label='name')


class DescriptionSelectorForm(Form, DescriptionSelectorMixin):

    def __init__(self, project_id, *args, **kwargs):

        super().__init__(*args, **kwargs)

        self.selector.query_factory = partial(ProjectDescriptionClasses, project_id)


class FeedbackMixin():

    positive = TextAreaField('Positive aspects', render_kw={"rows": 10},
                             description='Your feedback can be structured using Markdown, or use LaTeX formatting '
                                         'and mathematical markup. The display uses the same rendering pipeline '
                                         'used for project descriptions, so anything that works there will work here. '
                                         'You can preview your feedback before submitting it.')

    negative = TextAreaField('Negative aspects', render_kw={"rows": 10})

    save_feedback = SubmitField('Save changes')


class SupervisorFeedbackForm(Form, FeedbackMixin):

    pass


class MarkerFeedbackForm(Form, FeedbackMixin):

    pass
