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
from wtforms.validators import InputRequired, Optional, Length
from wtforms_alchemy.fields import QuerySelectField, QuerySelectMultipleField

from ..models import Project

from ..shared.forms.mixins import SaveChangesMixin, EditUserNameMixin, FirstLastNameMixin, \
    FacultyDataMixinFactory, FeedbackMixin, EmailSettingsMixin, DefaultLicenseMixin
from ..shared.forms.wtf_validators import globally_unique_project, unique_or_original_project, project_unique_label, \
    project_unique_or_original_label
from ..shared.forms.queries import GetActiveFaculty, BuildActiveFacultyName, CurrentUserResearchGroups, \
    AllResearchGroups, CurrentUserProjectClasses, AllProjectClasses, GetSupervisorRoles, GetSkillGroups, \
    AvailableProjectDescriptionClasses, ProjectDescriptionClasses, GetMaskableRoles, GetDestinationProjects, \
    GetDestinationProjectsPClass

from functools import partial

from ..models import DEFAULT_STRING_LENGTH


def ProjectMixinFactory(convenor_editing, project_classes_qf, group_qf):

    class ProjectMixin():

        if convenor_editing:
            owner = QuerySelectField('Project owner', query_factory=GetActiveFaculty, get_label=BuildActiveFacultyName)

        keywords = StringField('Keywords', validators=[Length(max=DEFAULT_STRING_LENGTH)],
                               description='Optional. Separate with commas or semicolons.')

        group = QuerySelectField('Research group', query_factory=group_qf, get_label='name',
                                 description='Projects are organized by research group when offered to students. '
                                             'Use this to indicate to students the approximate area in which they '
                                             'will be working.')

        # allow the project_class list to be empty (but then the project is not offered)
        project_classes = QuerySelectMultipleField('Select the project classes for which you wish to offer this project',
                                                   query_factory=project_classes_qf, get_label='name',
                                                   description='Set up descriptions for the different "flavours" of '
                                                               'this project in the "Variants" view.')

        # project options

        meeting_options = [(Project.MEETING_REQUIRED, "Meeting required"),
                           (Project.MEETING_OPTIONAL, "Meeting optional"),
                           (Project.MEETING_NONE, "Prefer not to meet")]
        meeting_reqd = SelectField('Meeting required?', choices=meeting_options, coerce=int)

        enforce_capacity = BooleanField('Enforce maximum capacity', default=True,
                                        description='Select if you wish to prevent the automated matching algorithm '
                                                    'allocating more students to your projects than a specified '
                                                    'maximum.')

        dont_clash_presentations = BooleanField("Prevent co-scheduling presentation with multiple students taking "
                                                "the same project", default=True,
                                                description='Select if you wish to prevent multiple students taking '
                                                            'this project from being scheduled to give presentations '
                                                            'in the same session. Students often prefer this '
                                                            'arrangement, so by default it is usually enabled. '
                                                            'However, please consider disabling it '
                                                            'if possible because it makes scheduling presentations '
                                                            'significantly simpler.')

        # popularity display

        show_popularity = BooleanField('Show popularity estimate', default=True,
                                       description='The popularity score is determined by a weighted '
                                                   'combination of the number '
                                                   'of selections, the number of bookmarks, and the number of '
                                                   'page views for a given project. It is intended to give students '
                                                   'a rough sense of the relative popularity of individual '
                                                   'projects.')

        show_bookmarks = BooleanField('Show number of bookmarks', default=True)

        show_selections = BooleanField('Show number of selections', default=True)

    return ProjectMixin


def AddProjectFormFactory(convenor_editing=False):

    Mixin = ProjectMixinFactory(convenor_editing,
                                AllProjectClasses if convenor_editing else CurrentUserProjectClasses,
                                AllResearchGroups if convenor_editing else CurrentUserResearchGroups)

    class AddProjectForm(Form, Mixin):

        name = StringField('Title', validators=[InputRequired(message='Project title is required'),
                                                Length(max=DEFAULT_STRING_LENGTH),
                                                globally_unique_project])

        submit = SubmitField('Next: Project descriptions')

        save_and_exit = SubmitField('Save and exit')

        save_and_preview = SubmitField('Save and preview')

    return AddProjectForm


def EditProjectFormFactory(convenor_editing=False):

    Mixin = ProjectMixinFactory(convenor_editing,
                                AllProjectClasses if convenor_editing else CurrentUserProjectClasses,
                                AllResearchGroups if convenor_editing else CurrentUserResearchGroups)

    class EditProjectForm(Form, Mixin, SaveChangesMixin):

        name = StringField('Title', validators=[InputRequired(message='Project title is required'),
                                                Length(max=DEFAULT_STRING_LENGTH),
                                                unique_or_original_project])

        save_and_preview = SubmitField('Save changes and preview')

    return EditProjectForm


def DescriptionSettingsMixinFactory(query_factory):

    class DescriptionSettingsMixin():

        # allow the project_class list to be empty (but then the project is not offered)
        project_classes = QuerySelectMultipleField('Select the project classes for which this description should be made available',
                                                   query_factory=query_factory, get_label='name')

        capacity = IntegerField('Maximum student capacity',
                                description='Optional. Used only if the option to enforce capacity '
                                            'is selected in your settings. '
                                            'Note this refers to the maximum number of assigned students, '
                                            'not your CATS assignment.',
                                validators=[Optional()])

        # allow team to be empty (but then the project is not offered)
        team = QuerySelectMultipleField('Who will be part of the supervisory team?',
                                        query_factory=GetSupervisorRoles, get_label='name')

        aims = TextAreaField('Aims', render_kw={'rows': 7},
                             description='Optional, but strongly recommended. Enter a concise summary of what should '
                                         'be achieved during the project. This information is not visible to students, '
                                         'but will be provided to the project marker to help them interpret the '
                                         "candidates' report.",
                             validators=[Optional()])

        review_only = BooleanField('This project is a literature review')

    return DescriptionSettingsMixin


class DescriptionContentMixin():

    description = TextAreaField('Text description of project', render_kw={"rows": 10},
                                description=r'Enter a description of your project. '
                                            r'The LaTeX mathematics environments are supported, as are common LaTeX commands. '
                                            r'The amsmath, amsthm, and amssymb packages are included. '
                                            r'You may use displayed or inline mathematics. '
                                            r'You may also use Markdown syntax to format your description. '
                                            r'<strong>Please preview your project to check it renders correctly.</strong>',
                                validators=[Optional()])

    reading = TextAreaField('Suggested resources', render_kw={"rows": 7},
                            description='Optional. The same styling and LaTeX options are available. '
                                        'To embed internet links, use the Markdown syntax [link text](URL).',
                            validators=[Optional()])


def AddDescriptionFormFactory(project_id):

    Mixin = DescriptionSettingsMixinFactory(partial(AvailableProjectDescriptionClasses, project_id, None))

    class AddDescriptionForm(Form, Mixin):

        label = StringField('Label', validators=[InputRequired(message='Please enter a label to identify this '
                                                                       'description'),
                                                 Length(max=DEFAULT_STRING_LENGTH),
                                                 project_unique_label],
                            description='Enter a short label to identify this description in the list. '
                                        'The label will not be visible to students.')

        submit = SubmitField('Add new description')

    return AddDescriptionForm


def EditDescriptionSettingsFormFactory(project_id, desc_id):

    Mixin = DescriptionSettingsMixinFactory(partial(AvailableProjectDescriptionClasses, project_id, desc_id))

    class EditDescriptionForm(Form, Mixin, SaveChangesMixin):

        label = StringField('Label', validators=[InputRequired(message='Please enter a label to identify this '
                                                                       'description'),
                                                 Length(max=DEFAULT_STRING_LENGTH),
                                                 project_unique_or_original_label],
                            description='Enter a short label to identify this description in the list. '
                                        'The label will not be visible to students.')

    return EditDescriptionForm

class EditDescriptionContentForm(Form, DescriptionContentMixin, SaveChangesMixin):

    pass


def MoveDescriptionFormFactory(user_id, project_id, pclass_id=None):

    if pclass_id is not None:
        qf = partial(GetDestinationProjectsPClass, user_id, project_id, pclass_id)
    else:
        qf = partial(GetDestinationProjects, user_id, project_id)

    class MoveDescriptionForm(Form, SaveChangesMixin):

        # field for destination project
        destination = QuerySelectField('Move this description to project', query_factory=qf, get_label='name')

        # optionally leave a copy of the description attached to this project
        copy = BooleanField('Leave a copy of the description attached to its current project', default=False)

    return MoveDescriptionForm


class SkillSelectorMixin():

    selector = QuerySelectField('Skill group', query_factory=GetSkillGroups, get_label='name')


class SkillSelectorForm(Form, SkillSelectorMixin):

    pass


def DescriptionSelectorMixinFactory(show_selector, query_factory):

    class DescriptionSelectorMixin():

        if show_selector:
            selector = QuerySelectField('Show project preview for', query_factory=query_factory, get_label='name')

    return DescriptionSelectorMixin


class CommentMixin():

    comment = TextAreaField('Post a new comment', render_kw={"rows": 5},
                            validators=[InputRequired(message='You cannot post an empty comment')])

    limit_visibility = BooleanField('Limit visibility to approvals team')

    post_comment = SubmitField('Post new comment')


def FacultyPreviewFormFactory(project_id, show_selector):

    SelectorMixin = DescriptionSelectorMixinFactory(show_selector, partial(ProjectDescriptionClasses, project_id))

    class DescriptionSelectorForm(Form, SelectorMixin, CommentMixin):

        pass

    return DescriptionSelectorForm


class SupervisorFeedbackForm(Form, FeedbackMixin):

    pass


class MarkerFeedbackForm(Form, FeedbackMixin):

    pass


class PresentationFeedbackForm(Form, FeedbackMixin):

    pass


class SupervisorResponseMixin():

    feedback = TextAreaField('Enter your response', render_kw={'rows': 5},
                             description='Your feedback can be structured using Markdown, or use LaTeX formatting '
                                         'and mathematical markup. Preview by looking at the feedback page for this '
                                         'project.')

    save_changes = SubmitField('Save changes')


class SupervisorResponseForm(Form, SupervisorResponseMixin):

    pass


def FacultySettingsFormFactory(user=None):

    class FacultySettingsForm(Form, EditUserNameMixin, FacultyDataMixinFactory(admin=False),
                              FirstLastNameMixin, SaveChangesMixin, EmailSettingsMixin,
                              DefaultLicenseMixin):

        if user is not None and user.has_role('root', skip_mask=True):
            mask_roles = QuerySelectMultipleField('Temporarily mask roles',
                                                  query_factory=partial(GetMaskableRoles, user.id), get_label='name')


    return FacultySettingsForm


def AvailabilityFormFactory(include_confirm=False):

    class AvailabilityForm(Form):

        comment = TextAreaField('Please include any other information you would like the scheduling team to '
                                'take into account:', render_kw={'rows': 5}, validators=[Optional()])

        if include_confirm:
            confirm = SubmitField('Confirm')

        else:
            update = SubmitField('Update')

    return AvailabilityForm
