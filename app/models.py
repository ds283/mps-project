#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import flash, current_app
from flask_security import current_user, UserMixin, RoleMixin

from sqlalchemy import orm, or_
from sqlalchemy.event import listens_for

from celery import schedules

from .database import db
from .cache import cache

from .shared.formatters import format_size, format_time, format_readable_time
from .shared.colours import get_text_colour
from .shared.sqlalchemy import get_count

from datetime import date, datetime, timedelta
import json
from os import path
from time import time
from uuid import uuid4


# make db available as a static variable, so we can import into other parts of the code


# length of database string for typical fields, if used
DEFAULT_STRING_LENGTH = 255

# length of database string used for IP addresses
IP_LENGTH = 60

# length of database string for a "year" column
YEAR_LENGTH = 4

# length of database string for password hash field, if used
PASSWORD_HASH_LENGTH = 255

# length of project description fields
DESCRIPTION_STRING_LENGTH = 8000


# labels and keys for 'year' field; it's not possible to join in Y1; treat students as
# joining in Y2
year_choices = [(2, 'Year 2'), (3, 'Year 3'), (4, 'Year 4')]

# labels and keys for 'extent' field
extent_choices = [(1, '1 year'), (2, '2 years')]

# labels and keys for 'academic titles' field
academic_titles = [(1, 'Dr'), (2, 'Professor'), (3, 'Mr'), (4, 'Ms'), (5, 'Mrs'), (6, 'Miss')]

# labels and keys for years_history
matching_history_choices = [(1, '1 year'), (2, '2 years'), (3, '3 years'), (4, '4 years'), (5, '5 years')]

# PuLP solver choices
solver_choices = [(0, 'PuLP-packaged CBC'), (1, 'CBC external command'), (2, 'GLPK external command')]

# session types
session_choices = [(0, 'Morning'), (1, 'Afternoon')]

# theme types
theme_choices = [(0, 'Default'), (1, 'Flat'), (2, 'Dark')]


class ColouredLabelMixin():

    colour = db.Column(db.String(DEFAULT_STRING_LENGTH))

    def make_CSS_style(self):
        if self.colour is None:
            return None

        return "background-color:{bg}; color:{fg};".format(bg=self.colour, fg=get_text_colour(self.colour))


    def _make_label(self, text, user_classes=None):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """
        if user_classes is None:
            classes = 'label label-default'
        else:
            classes = 'label label-default {cls}'.format(cls=user_classes)

        style = self.make_CSS_style()
        if style is None:
                return '<span class="{cls}">{msg}</span>'.format(msg=text, cls=classes)

        return '<span class="{cls}" style="{sty}">{msg}</span>'.format(msg=text, cls=classes, sty=style)


# roll our own get_main_config() and get_current_year(), which we cannot import because it creates a dependency cycle
def _get_main_config():
    return db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()


def _get_current_year():
    return _get_main_config().year


####################
# ASSOCIATION TABLES
####################

# association table holding mapping from roles to users
roles_to_users = db.Table('roles_users',
                          db.Column('user_id', db.Integer(), db.ForeignKey('users.id'), primary_key=True),
                          db.Column('role_id', db.Integer(), db.ForeignKey('roles.id'), primary_key=True))

# association table giving faculty research group affiliations
faculty_affiliations = db.Table('faculty_affiliations',
                                db.Column('user_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                                db.Column('group_id', db.Integer(), db.ForeignKey('research_groups.id'), primary_key=True))


# PROJECT CLASS ASSOCIATIONS


# association table giving association between project classes and degree programmes
pclass_programme_associations = db.Table('project_class_to_programmes',
                                         db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True),
                                         db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True))

# association table giving co-convenors for a project class
pclass_coconvenors = db.Table('project_class_coconvenors',
                              db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True),
                              db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))


# SYSTEM MESSAGES


# association between project classes and messages
pclass_message_associations = db.Table('project_class_to_messages',
                                       db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True),
                                       db.Column('message_id', db.Integer(), db.ForeignKey('messages.id'), primary_key=True))

# associate dismissals with messages
message_dismissals = db.Table('message_dismissals',
                              db.Column('message_id', db.Integer(), db.ForeignKey('messages.id'), primary_key=True),
                              db.Column('user_id', db.Integer(), db.ForeignKey('users.id'), primary_key=True))


# GO-LIVE CONFIRMATIONS FROM FACULTY

golive_confirmation = db.Table('go_live_confirmation',
                               db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                               db.Column('pclass_config_id', db.Integer(), db.ForeignKey('project_class_config.id'), primary_key=True))


# PROJECT ASSOCIATIONS (NOT LIVE)


# association table giving association between projects and project classes
project_classes = db.Table('project_to_classes',
                           db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                           db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True))

# association table giving association between projects and transferable skills
project_skills = db.Table('project_to_skills',
                          db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                          db.Column('skill_id', db.Integer(), db.ForeignKey('transferable_skills.id'), primary_key=True))

# association table giving association between projects and degree programmes
project_programmes = db.Table('project_to_programmes',
                              db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                              db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True))

# association table giving assessors
assessors = db.Table('project_to_assessors',
                     db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                     db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))

# association table matching project descriptions to supervision team
description_supervisors = db.Table('description_to_supervisors',
                                   db.Column('description_id', db.Integer(), db.ForeignKey('descriptions.id'), primary_key=True),
                                   db.Column('supervisor_id', db.Integer(), db.ForeignKey('supervision_team.id'), primary_key=True))

# association table matching project descriptions to project classes
description_pclasses = db.Table('description_to_pclasses',
                                db.Column('description_id', db.Integer(), db.ForeignKey('descriptions.id'), primary_key=True),
                                db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True))


# PROJECT ASSOCIATIONS (LIVE)


# association table giving association between projects and project classes
live_project_classes = db.Table('live_project_to_classes',
                                db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True))

# association table giving association between projects and transferable skills
live_project_skills = db.Table('live_project_to_skills',
                               db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                               db.Column('skill_id', db.Integer(), db.ForeignKey('transferable_skills.id'), primary_key=True))

# association table giving association between projects and degree programmes
live_project_programmes = db.Table('live_project_to_programmes',
                                   db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                   db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True))

# association table giving association between projects and supervision tram
live_project_supervision = db.Table('live_project_to_supervision',
                                    db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                    db.Column('supervisor.id', db.Integer(), db.ForeignKey('supervision_team.id'), primary_key=True))

# association table giving assessors
live_assessors = db.Table('live_project_to_assessors',
                          db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                          db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))


# LIVE STUDENT ASSOCIATIONS

# association table: faculty confirmation requests
confirmation_requests = db.Table('confirmation_requests',
                                 db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                 db.Column('student_id', db.Integer(), db.ForeignKey('selecting_students.id'), primary_key=True)
                                 )

# association table: faculty confirmed meetings
faculty_confirmations = db.Table('faculty_confirmations',
                                 db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                 db.Column('student_id', db.Integer(), db.ForeignKey('selecting_students.id'), primary_key=True))


# CONVENOR FILTERS

# association table : active research group filters
convenor_group_filter_table = db.Table('convenor_group_filters',
                                       db.Column('owner_id', db.Integer(), db.ForeignKey('filters.id'), primary_key=True),
                                       db.Column('research_group_id', db.Integer(), db.ForeignKey('research_groups.id'), primary_key=True))

# assocation table: active skill group filters
convenor_skill_filter_table = db.Table('convenor_skill_filters',
                                       db.Column('owner_id', db.Integer(), db.ForeignKey('filters.id'), primary_key=True),
                                       db.Column('skill_group_id', db.Integer(), db.ForeignKey('skill_groups.id'), primary_key=True))


# STUDENT FILTERS

# association table: active research group filters for selectors
sel_group_filter_table = db.Table('sel_group_filters',
                                  db.Column('selector_id', db.Integer(), db.ForeignKey('selecting_students.id'), primary_key=True),
                                  db.Column('research_group_id', db.Integer(), db.ForeignKey('research_groups.id'), primary_key=True))

# association table: active skill group filters for selectors
sel_skill_filter_table = db.Table('sel_skill_filters',
                                  db.Column('selector_id', db.Integer(), db.ForeignKey('selecting_students.id'), primary_key=True),
                                  db.Column('skill_group_id', db.Integer(), db.ForeignKey('skill_groups.id'), primary_key=True))


# MATCHING

# project classes participating in a match
match_configs = db.Table('match_configs',
                         db.Column('match_id', db.Integer(), db.ForeignKey('matching_attempts.id'), primary_key=True),
                         db.Column('config_id', db.Integer(), db.ForeignKey('project_class_config.id'), primary_key=True))

# workload balancing: include CATS from other MatchingAttempts
match_balancing = db.Table('match_balancing',
                           db.Column('child_id', db.Integer(), db.ForeignKey('matching_attempts.id'), primary_key=True),
                           db.Column('parent_id', db.Integer(), db.ForeignKey('matching_attempts.id'), primary_key=True))

# configuration association: supervisors
supervisors_matching_table = db.Table('match_config_supervisors',
                                      db.Column('match_id', db.Integer(), db.ForeignKey('matching_attempts.id'), primary_key=True),
                                      db.Column('supervisor_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))

# configuration association: markers
marker_matching_table = db.Table('match_config_markers',
                                 db.Column('match_id', db.Integer(), db.ForeignKey('matching_attempts.id'), primary_key=True),
                                 db.Column('marker_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))

# configuration association: projects
project_matching_table = db.Table('match_config_projects',
                                  db.Column('match_id', db.Integer(), db.ForeignKey('matching_attempts.id'), primary_key=True),
                                  db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True))


# PRESENTATIONS

# link presentation assessments to submission periods
assessment_to_periods = db.Table('assessment_to_periods',
                                 db.Column('assessment_id', db.Integer(), db.ForeignKey('presentation_assessments.id'), primary_key=True),
                                 db.Column('period_id', db.Integer(), db.ForeignKey('submission_periods.id'), primary_key=True))

# link sessions to rooms
session_to_rooms = db.Table('session_to_rooms',
                            db.Column('session_id', db.Integer(), db.ForeignKey('presentation_sessions.id'), primary_key=True),
                            db.Column('room_id', db.Integer(), db.ForeignKey('rooms.id'), primary_key=True))

# capture faculty availability for each session
faculty_availability = db.Table('faculty_availability',
                                db.Column('session_id', db.Integer(), db.ForeignKey('presentation_sessions.id'), primary_key=True),
                                db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))

# capture list of faculty who are attached to an assessment as possible assessors
assessment_to_assessors = db.Table('assessment_to_assessors',
                                   db.Column('assessment_id', db.Integer(), db.ForeignKey('presentation_assessments.id'), primary_key=True),
                                   db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))

# capture list of students who can't attend the scheduled sessions of an assessment
assessment_not_attend = db.Table('assessment_not_attend',
                                 db.Column('assessment_id', db.Integer(), db.ForeignKey('presentation_assessments.id'), primary_key=True),
                                 db.Column('submitted_id', db.Integer(), db.ForeignKey('submission_records.id'), primary_key=True))

# capture list of faculty who are still to return availability data for an assessment
faculty_availability_waiting = db.Table('faculty_availability_waiting',
                                        db.Column('assessment_id', db.Integer(), db.ForeignKey('presentation_assessments.id'), primary_key=True),
                                        db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))

# faculty to slots map
faculty_to_slots = db.Table('faculty_to_slots',
                            db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                            db.Column('slot_id', db.Integer(), db.ForeignKey('schedule_slots.id'), primary_key=True))

# submitter to slots map
submitter_to_slots = db.Table('submitter_to_slots',
                              db.Column('submitter_id', db.Integer(), db.ForeignKey('submission_records.id'), primary_key=True),
                              db.Column('slot_id', db.Integer(), db.ForeignKey('schedule_slots.id'), primary_key=True))

class MainConfig(db.Model):
    """
    Main application configuration table; generally, there should only
    be one row giving the current configuration
    """

    # year is the main configuration variable
    year = db.Column(db.Integer(), primary_key=True)


class Role(db.Model, RoleMixin):
    """
    Model a row from the roles table in the application database
    """

    # make table name plural
    __tablename__ = 'roles'

    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True)
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))


class User(db.Model, UserMixin):
    """
    Model a row from the user table in the application database
    """

    # make table name plural
    __tablename__ = 'users'

    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True, unique=True)

    username = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True, unique=True)
    password = db.Column(db.String(PASSWORD_HASH_LENGTH, collation='utf8_bin'))

    first_name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)
    last_name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)

    active = db.Column(db.Boolean())

    confirmed_at = db.Column(db.DateTime())
    last_login_at = db.Column(db.DateTime())
    current_login_at = db.Column(db.DateTime())
    last_login_ip = db.Column(db.String(IP_LENGTH))
    current_login_ip = db.Column(db.String(IP_LENGTH))
    login_count = db.Column(db.Integer())

    roles = db.relationship('Role', secondary=roles_to_users,
                            backref=db.backref('users', lazy='dynamic'))


    THEME_DEFAULT = 0
    THEME_FLAT = 1
    THEME_DARK = 2

    # theme options
    theme = db.Column(db.Integer(), default=THEME_DEFAULT, nullable=False)


    # allow user objects to get all project classes so that we can render
    # a 'Convenor' menu in the navbar for all admin users
    @property
    def all_project_classes(self):
        """
        Get available project classes
        :return:
        """
        return ProjectClass.query.filter_by(active=True)


    # build a name for this user
    @property
    def name(self):
        prefix = ''

        if self.faculty_data is not None and self.faculty_data.use_academic_title:

            for key, value in academic_titles:

                if key == self.faculty_data.academic_title:

                    prefix = value + ' '
                    break

        return prefix + self.first_name + ' ' + self.last_name


    @property
    def name_and_username(self):
        return self.name + ' (' + self.username + ')'


    @property
    def active_label(self):
        if self.active:
            return '<span class="label label-success">Active</a>'

        return '<span class="label label-default">Inactive</a>'


    def post_task_update(self, uuid, payload, remove_on_load=False, autocommit=False):
        """
        Add a notification to this user
        :param user_id:
        :param payload:
        :return:
        """

        # remove any previous notifications intended for this user with this uuid
        self.notifications.filter_by(uuid=uuid).delete()

        data = Notification(user_id=self.id,
                            type=Notification.TASK_PROGRESS,
                            uuid=uuid,
                            payload=payload,
                            remove_on_pageload=remove_on_load)
        db.session.add(data)

        if autocommit:
            db.session.commit()


    CLASSES = {'success': 'alert-success',
               'info': 'alert-info',
               'warning': 'alert-warning',
               'danger': 'alert-danger',
               'error': 'alert-danger'}


    def post_message(self, message, cls, remove_on_load=False, autocommit=False):
        """
        Add a notification to this user
        :param user_id:
        :param payload:
        :return:
        """

        if cls in self.CLASSES:
            cls = self.CLASSES[cls]
        else:
            cls = None

        data = Notification(user_id=self.id,
                            type=Notification.USER_MESSAGE,
                            uuid=str(uuid4()),
                            payload={'message': message, 'type': cls},
                            remove_on_pageload=remove_on_load)
        db.session.add(data)

        if autocommit:
            db.session.commit()


    def send_showhide(self, html_id, action, autocommit=False):
        """
        Send a show/hide request for a specific HTML node
        :param html_id:
        :param action:
        :param autocommit:
        :return:
        """

        data = Notification(user_id=self.id,
                            type=Notification.SHOW_HIDE_REQUEST,
                            uuid=str(uuid4()),
                            payload={'html_id': html_id, 'action': action},
                            remove_on_pageload=False)
        db.session.add(data)

        if autocommit:
            db.session.commit()


    def send_replacetext(self, html_id, new_text, autocommit=False):
        """
        Send an instruction to replace the text in a specific HTML node
        :param html_id:
        :param new_text:
        :param autocommit:
        :return:
        """

        data = Notification(user_id=self.id,
                            type=Notification.REPLACE_TEXT_REQUEST,
                            uuid=str(uuid4()),
                            payload={'html_id': html_id, 'text': new_text},
                            remove_on_pageload=False)
        db.session.add(data)

        if autocommit:
            db.session.commit()


class ResearchGroup(db.Model, ColouredLabelMixin):
    """
    Model a row from the research group table
    """

    # make table name plural
    __tablename__ = 'research_groups'

    id = db.Column(db.Integer(), primary_key=True)

    # abbreviation for use in space-limited contexts
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True, unique=True)

    # long-form name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # optional website
    website = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # active flag
    active = db.Column(db.Boolean())

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def disable(self):
        """
        Disable this research group
        :return:
        """

        self.active = False

        # remove this group from any faculty that have become affiliated with it
        for member in self.faculty:
            member.remove_affiliation(self)


    def enable(self):
        """
        Enable this research group
        :return:
        """

        self.active = True


    def make_label(self, text=None, user_classes=None):
        """
        Make approriately coloured label
        :param text:
        :return:
        """
        if text is None:
            text = self.abbreviation

        return self._make_label(text, user_classes)


class FacultyData(db.Model):
    """
    Models extra data held on faculty members
    """

    __tablename__ = 'faculty_data'

    # primary key is same as users.id for this faculty member
    id = db.Column(db.Integer(), db.ForeignKey('users.id'), primary_key=True)
    user = db.relationship('User', foreign_keys=[id], backref=db.backref('faculty_data', uselist=False))

    # research group affiliations for this faculty member
    affiliations = db.relationship('ResearchGroup', secondary=faculty_affiliations, lazy='dynamic',
                                   backref=db.backref('faculty', lazy='dynamic'))

    # academic title (Prof, Dr, etc.)
    academic_title = db.Column(db.Integer())

    # use academic title?
    use_academic_title = db.Column(db.Boolean())

    # office location
    office = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))


    # PROJECT SETTINGS

    # does this faculty want to sign off on students before they can apply?
    sign_off_students = db.Column(db.Boolean())

    # default capacity
    project_capacity = db.Column(db.Integer())

    # enforce capacity limits by default?
    enforce_capacity = db.Column(db.Boolean())

    # enable popularity display by default?
    show_popularity = db.Column(db.Boolean())


    # CAPACITY

    # supervision CATS capacity
    CATS_supervision = db.Column(db.Integer())

    # 2nd-marking CATS capacity
    CATS_marking = db.Column(db.Integer())

    # presentation assessment CATS capacity
    CATS_presentation = db.Column(db.Integer())


    # METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def projects_offered(self, pclass):
        return Project.query.filter(Project.active,
                                    Project.owner_id == self.id,
                                    Project.project_classes.any(id=pclass.id)).count()


    def projects_offered_label(self, pclass):
        n = self.projects_offered(pclass)

        if n == 0:
            return '<span class="label label-danger"><i class="fa fa-times"></i> 0 available</span>'

        return '<span class="label label-primary"><i class="fa fa-check"></i> {n} available</span>'.format(n=n)


    @property
    def projects_unofferable(self):
        unofferable = 0
        for proj in self.projects:
            if proj.active and not proj.is_offerable:
                unofferable += 1

        return unofferable


    @property
    def projects_unofferable_label(self):
        n = self.projects_unofferable

        if n == 0:
            return '<span class="label label-default"><i class="fa fa-check"></i> 0 unofferable</span>'

        return '<span class="label label-warning"><i class="fa fa-times"></i> {n} unofferable</span>'.format(n=n)


    def remove_affiliation(self, group, autocommit=False):
        """
        Remove an affiliation from a faculty member
        :param group:
        :return:
        """

        self.affiliations.remove(group)

        # remove this group affiliation label from any projects owned by this faculty member
        ps = Project.query.filter_by(owner_id=self.id, group_id=group.id)

        for proj in ps.all():
            proj.group = None

        if autocommit:
            db.session.commit()


    def add_affiliation(self, group, autocommit=False):
        """
        Add an affiliation to this faculty member
        :param group:
        :return:
        """

        self.affiliations.append(group)

        if autocommit:
            db.session.commit()


    def is_enrolled(self, pclass):
        """
        Check whether this FacultyData record has an enrollment for a given project class
        :param pclass:
        :return:
        """

        # test whether an EnrollmentRecord exists for this project class
        record = self.get_enrollment_record(pclass)

        if record is None:
            return False

        return True


    def remove_enrollment(self, pclass):
        """
        Remove an enrollment from a faculty member
        :param pclass:
        :return:
        """

        # find enrollment record for this project class
        record = self.get_enrollment_record(pclass)
        if record is not None:
            db.session.delete(record)

        # remove this project class from any projects owned by this faculty member
        ps = Project.query.filter(Project.owner_id == self.id, Project.project_classes.any(id=pclass.id))

        for proj in ps.all():
            proj.remove_project_class(pclass)

        db.session.commit()

        celery = current_app.extensions['celery']
        adjust_task = celery.tasks['app.tasks.availability.adjust']

        adjust_task.apply_async(args=(record.id, _get_current_year()))


    def add_enrollment(self, pclass):
        """
        Add an enrollment to this faculty member
        :param pclass:
        :return:
        """

        record = EnrollmentRecord(pclass_id=pclass.id,
                                  owner_id=self.id,
                                  supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED,
                                  supervisor_comment=None,
                                  supervisor_reenroll=None,
                                  marker_state=EnrollmentRecord.MARKER_ENROLLED,
                                  marker_comment=None,
                                  marker_reenroll=None,
                                  presentations_state=EnrollmentRecord.PRESENTATIONS_ENROLLED,
                                  presentations_comment=None,
                                  presentations_reenroll=None,
                                  creator_id=current_user.id,
                                  creation_timestamp=datetime.now(),
                                  last_edit_id=None,
                                  last_edit_timestamp=None)

        db.session.add(record)
        db.session.commit()

        celery = current_app.extensions['celery']
        adjust_task = celery.tasks['app.tasks.availability.adjust']

        adjust_task.apply_async(args=(record.id, _get_current_year()))


    def enrolled_labels(self, pclass):
        record = self.get_enrollment_record(pclass)

        if record is None:
            return '<span class="label label-warning">Not enrolled</span>'

        return record.enrolled_labels


    def get_enrollment_record(self, pclass):
        return self.enrollments.filter_by(pclass_id=pclass.id).first()


    @property
    def ordered_enrollments(self):
        return self.enrollments \
            .join(ProjectClass, ProjectClass.id == EnrollmentRecord.pclass_id) \
            .order_by(ProjectClass.name)


    @property
    def is_convenor(self):
        """
        Determine whether this faculty member is convenor for any projects
        :return:
        """

        if self.convenor_for is not None and get_count(self.convenor_for) > 0 is not None:
            return True

        if self.coconvenor_for is not None and get_count(self.coconvenor_for) is not None:
            return True

        return False


    @property
    def convenor_list(self):
        """
        Return list of projects for which this faculty member is a convenor
        :return:
        """
        pcls = self.convenor_for.all() + self.coconvenor_for.all()
        pcl_set = set(pcls)
        return pcl_set


    def add_convenorship(self, pclass):
        """
        Set up this user faculty member for the convenorship of the given project class. Currently empty.
        :param pclass:
        :return:
        """

        flash('Installed {name} as convenor of {title}'.format(name=self.user.name, title=pclass.name))


    def remove_convenorship(self, pclass):
        """
        Remove the convenorship of the given project class from this user
        :param pclass:
        :return:
        """

        # currently our only task is to remove system messages emplaced by this user in their role as convenor
        for item in MessageOfTheDay.query.filter_by(user_id=self.id).all():

            # if no assigned classes then this is a broadcast message; move on
            # (we can assume the user is still an administrator)
            if item.project_classes.first() is None:

                break

            # otherwise, remove this project class from the classes associated with this
            if pclass in item.project_classes:

                item.project_classes.remove(pclass)

                # if assigned project classes are now empty then delete the parent message
                if item.project_classes.first() is None:

                    db.session.delete(item)

        db.session.commit()

        flash('Removed {name} as convenor of {title}'.format(name=self.user.name, title=pclass.name))


    @property
    def number_assessor(self):
        """
        Determine the number of projects to which we are attached as an assessor
        :return:
        """
        return get_count(self.assessor_for)


    @property
    def marker_label(self):
        """
        Generate a label for the number of projects to which we are attached as a second marker
        :param pclass:
        :return:
        """

        num = self.number_assessor

        if num == 0:
            return '<span class="label label-default"><i class="fa fa-times"></i> Assessor for 0</span>'

        return '<span class="label label-success"><i class="fa fa-check"></i> Assessor for {n}</span>'.format(n=num)


    def supervisor_assignments(self, pclass_id):
        """
        Return a list of current SubmissionRecord instances for which we are supervisor
        :return:
        """
        lp_query = self.live_projects.subquery()

        return db.session.query(SubmissionRecord) \
            .join(lp_query, lp_query.c.id == SubmissionRecord.project_id) \
            .filter(SubmissionRecord.retired == False) \
            .join(SubmittingStudent, SubmissionRecord.owner_id == SubmittingStudent.id) \
            .join(ProjectClassConfig, SubmittingStudent.config_id == ProjectClassConfig.id) \
            .filter(ProjectClassConfig.pclass_id == pclass_id) \
            .order_by(SubmissionRecord.submission_period.asc())


    def marker_assignments(self, pclass_id):
        """
        Return a list of current SubmissionRecord instances for which we are 2nd marker
        :return:
        """
        return self.marking_records \
            .filter_by(retired=False) \
            .join(SubmittingStudent, SubmissionRecord.owner_id == SubmittingStudent.id) \
            .join(ProjectClassConfig, SubmittingStudent.config_id == ProjectClassConfig.id) \
            .filter(ProjectClassConfig.pclass_id == pclass_id) \
            .order_by(SubmissionRecord.submission_period.asc())


    def CATS_assignment(self, pclass_id):
        """
        Return (supervising CATS, marking CATS) for the current year
        :return:
        """

        supv = self.supervisor_assignments(pclass_id)
        mark = self.marker_assignments(pclass_id)

        supv_CATS = [x.supervising_CATS for x in supv]
        supv_CATS_clean = [x for x in supv_CATS if x is not None]

        mark_CATS = [x.marking_CATS for x in mark]
        mark_CATS_clean = [x for x in mark_CATS if x is not None]

        return sum(supv_CATS_clean), sum(mark_CATS_clean)


    def has_late_feedback(self, pclass_id):
        supervisor_late = [x.supervisor_feedback_state == SubmissionRecord.FEEDBACK_LATE
                           for x in self.supervisor_assignments(pclass_id)]

        marker_late = [x.supervisor_response_state == SubmissionRecord.FEEDBACK_LATE
                       for x in self.supervisor_assignments(pclass_id)]

        response_late = [x.marker_feedback_state == SubmissionRecord.FEEDBACK_LATE
                         for x in self.marker_assignments(pclass_id)]

        return any(supervisor_late) or any(marker_late) or any(response_late)


    def has_not_started_flags(self, pclass_id):
        not_started = [not x.student_engaged and x.submission_period <= x.owner.config.submission_period
                       for x in self.supervisor_assignments(pclass_id)]

        return any(not_started)


    @property
    def outstanding_availability_requests(self):
        return self.availability_waiting \
            .filter_by(year=_get_current_year(), availability_closed=False) \
            .order_by(PresentationAssessment.name.asc())


    @property
    def editable_availability_requests(self):
        return self.presentation_assessments \
            .filter_by(year=_get_current_year(), availability_closed=False) \
            .order_by(PresentationAssessment.name.asc())


    @property
    def has_outstanding_availability_requests(self):
        return get_count(self.outstanding_availability_requests) > 0


    @property
    def has_editable_availability_requests(self):
        return get_count(self.editable_availability_requests) > 0


class StudentData(db.Model):
    """
    Models extra data held on students
    """

    __tablename__ = 'student_data'

    # primary key is same as users.id for this student member
    id = db.Column(db.Integer(), db.ForeignKey('users.id'), primary_key=True)
    user = db.relationship('User', foreign_keys=[id], backref=db.backref('student_data', uselist=False))

    # exam number is needed for marking
    exam_number = db.Column(db.Integer(), index=True, unique=True)

    # cohort identifies which project classes this student will be enrolled for
    cohort = db.Column(db.Integer(), index=True)

    # degree programme
    programme_id = db.Column(db.Integer, db.ForeignKey('degree_programmes.id'))
    programme = db.relationship('DegreeProgramme', backref=db.backref('students', lazy='dynamic'))

    # did this student do a foundation year? if so, their admission cohort
    # needs to be treated differently when calculating academic years
    foundation_year = db.Column(db.Boolean())

    # has this student had repeat years? If so, they also upset the academic year calculation
    repeated_years = db.Column(db.Integer())

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    @property
    def cohort_label(self):
        return '<span class="label label-primary">{c} cohort</span>'.format(c=self.cohort)


    def academic_year(self, current_year):
        """
        Computes the academic year of a student, relative to a given year
        :param current_year:
        :return:
        """

        base_year = current_year - self.cohort + 1 - self.repeated_years

        if self.foundation_year:
            base_year -= 1

        return base_year


    def academic_year_label(self, current_year):

        academic_year = self.academic_year(current_year)

        if academic_year < 0:
            text = 'Error(<0)'
            type = 'danger'
        elif academic_year > 4:
            text = 'Graduated'
            type = 'primary'
        else:
            text = 'Y{y}'.format(y=self.academic_year(current_year))
            type = 'info'

        if not current_user.has_role('student'):
            if self.foundation_year:
                text += ' +F'

            if self.repeated_years > 0:
                text += ' +{n}'.format(n=self.repeated_years)

        return '<span class="label label-{type}">{label}</span>'.format(label=text, type=type)



class DegreeType(db.Model, ColouredLabelMixin):
    """
    Model a degree type
    """

    # make table name plural
    __tablename__ = 'degree_types'

    id = db.Column(db.Integer(), primary_key=True)

    # degree type label (MSc, MPhys, BSc, etc.)
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True, index=True)

    # degree type abbreviation
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True, unique=True)

    # active flag
    active = db.Column(db.Boolean())

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def disable(self):
        """
        Disable this degree type
        :return:
        """
        self.active = False

        # disable any degree programmes that depend on this degree type
        for prog in self.degree_programmes:
            prog.disable()


    def enable(self):
        """
        Enable this degree type
        :return:
        """
        self.active = True


    def make_label(self, text=None, user_classes=None):
        if text is None:
            text = self.abbreviation

        return self._make_label(text, user_classes)


class DegreeProgramme(db.Model):
    """
    Model a row from the degree programme table
    """

    # make table name plural
    __tablename__ = 'degree_programmes'

    id = db.Column(db.Integer(), primary_key=True)

    # programme name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)

    # programme abbreviation
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)

    # show degree type in name
    show_type = db.Column(db.Boolean())

    # active flag
    active = db.Column(db.Boolean())

    # degree type
    type_id = db.Column(db.Integer(), db.ForeignKey('degree_types.id'), index=True)
    degree_type = db.relationship('DegreeType', backref=db.backref('degree_programmes', lazy='dynamic'))

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def disable(self):
        """
        Disable this degree programme
        :return:
        """
        self.active = False

        # disable any project classes that depend on this programme
        for pclass in self.project_classes:
            pclass.disable()


    def enable(self):
        """
        Enable this degree programme
        :return:
        """
        if self.available:
            self.active = True


    @property
    def available(self):
        """
        Determine whether this degree programme is available for use (or activation)
        :return:
        """
        # ensure degree type is active
        return self.degree_type.active


    @property
    def full_name(self):
        if self.show_type:
            return '{p} {t}'.format(p=self.name, t=self.degree_type.name)

        return self.name


    @property
    def short_name(self):
        if self.show_type:
            return '{p} {t}'.format(p=self.abbreviation, t=self.degree_type.abbreviation)

        return self.abbreviation


    def make_label(self, text=None, user_classes=None):
        if text is None:
            text = self.full_name

        return self.degree_type.make_label(text=text, user_classes=user_classes)


    @property
    def label(self):
        return self.degree_type.make_label(self.full_name)


    @property
    def short_label(self):
        return self.degree_type.make_label(self.short_name)


class SkillGroup(db.Model, ColouredLabelMixin):
    """
    Model a group of transferable skills
    """

    # make table name plural
    __tablename__ = "skill_groups"

    id = db.Column(db.Integer(), primary_key=True)

    # name of skill group
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True, index=True)

    # active?
    active = db.Column(db.Boolean())

    # add group name to labels
    add_group = db.Column(db.Boolean())

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def enable(self):
        """
        Enable this skill group and cascade, ie. enable any transferable skills associated with this group
        :return:
        """
        self.active = True

        for skill in self.skills:
            skill.enable()


    def disable(self):
        """
        Disable this skill group and cascade, ie. disable any transferable skills associated with this group
        :return:
        """
        self.active = False

        for skill in self.skills:
            skill.disable()


    def make_label(self, text=None, user_classes=None):
        if text is None:
            text = self.name

        return self._make_label(text, user_classes)


    def make_skill_label(self, skill, user_classes=None):
        """
        Make an appropriately formatted, coloured label for a transferable skill
        :param skill:
        :return:
        """
        if self.add_group:
            label = self.name + ': '
        else:
            label = ''

        label += skill

        return self._make_label(text=label, user_classes=user_classes)


class TransferableSkill(db.Model):
    """
    Model a transferable skill
    """

    # make table name plural
    __tablename__ = "transferable_skills"

    id = db.Column(db.Integer(), primary_key=True)

    # name of skill
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)

    # skill group
    group_id = db.Column(db.Integer(), db.ForeignKey('skill_groups.id'))
    group = db.relationship('SkillGroup', foreign_keys=[group_id], uselist=False,
                            backref=db.backref('skills', lazy='dynamic'))

    # active?
    active = db.Column(db.Boolean())

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    @property
    def is_active(self):

        if self.group is None:
            return self.active

        return self.active and self.group.active


    def disable(self):
        """
        Disable this transferable skill and cascade, ie. remove from any projects that have been labelled with it
        :return:
        """

        self.active = False

        # remove this skill from any projects that have been labelled with it
        for proj in self.projects:
            proj.skills.remove(self)


    def enable(self):
        """
        Enable this transferable skill
        :return:
        """

        self.active = True


    def make_label(self, user_classes=None):
        """
        Make a label
        :return:
        """
        if self.group is None:
            if user_classes is None:
                classes = 'label label-default'
            else:
                classes = 'label label-default {cls}'.format(cls=user_classes)

            return '<span class="{cls}">{name}</span>'.format(name=self.name, cls=classes)

        return self.group.make_skill_label(self.name, user_classes=user_classes)


    @property
    def short_label(self):
        return self.group.make_label(self.name)


class ProjectClass(db.Model, ColouredLabelMixin):
    """
    Model a single project class
    """

    # make table name plural
    __tablename__ = "project_classes"

    id = db.Column(db.Integer(), primary_key=True)

    # project class name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True, index=True)

    # user-facing abbreviatiaon
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True, index=True)

    # active?
    active = db.Column(db.Boolean())


    # PRACTICAL DATA

    # which year does this project class run for?
    year = db.Column(db.Integer(), index=True)

    # how many years does the project extend? usually 1, but RP is more
    extent = db.Column(db.Integer())

    # are the submissions second marked?
    uses_marker = db.Column(db.Boolean())

    # are there presentations?
    uses_presentations = db.Column(db.Boolean())

    # how many initial_choices should students make?
    initial_choices = db.Column(db.Integer())

    # how many switch choices should students be allowed?
    switch_choices = db.Column(db.Integer())

    # is project selection open to all students?
    selection_open_to_all = db.Column(db.Boolean())


    # OPTIONS

    # explicitly ask supervisors to confirm projects each year?
    require_confirm = db.Column(db.Boolean())

    # carry over supervisor in subsequent years?
    supervisor_carryover = db.Column(db.Boolean())


    # POPULARITY DISPLAY

    # how many days to keep hourly popularity data for
    keep_hourly_popularity = db.Column(db.Integer())

    # how many weeks to keep daily popularity data for
    keep_daily_popularity = db.Column(db.Integer())


    # WORKLOAD MODEL

    # CATS awarded for supervising
    CATS_supervision = db.Column(db.Integer())

    # CATS awarded for 2nd marking
    CATS_marking = db.Column(db.Integer())

    # CATS awarded for presentation assessment
    CATS_presentation = db.Column(db.Integer())


    # AUTOMATED MATCHING

    # what level of automated student/project/2nd-marker matching does this project class use?
    # does it participate in the global automated matching, or is matching manual?
    do_matching = db.Column(db.Boolean())

    # number of assessors that should be specified per project
    number_assessors = db.Column(db.Integer())


    # PERSONNEL

    # principal project convenor. Must be a faculty member, so we link to faculty_data table
    convenor_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'), index=True)
    convenor = db.relationship('FacultyData', foreign_keys=[convenor_id],
                               backref=db.backref('convenor_for', lazy='dynamic'))

    # project co-convenors
    # co-convenors are similar to convenors, except that the principal convenor is always the
    # displayed contact point.
    # co-convenors could eg. be old convenors who are able to help out during a transition period
    # between convenors
    coconvenors = db.relationship('FacultyData', secondary=pclass_coconvenors, lazy='dynamic',
                                  backref=db.backref('coconvenor_for', lazy='dynamic'))

    # associate this project class with a set of degree programmes
    programmes = db.relationship('DegreeProgramme', secondary=pclass_programme_associations, lazy='dynamic',
                                 backref=db.backref('project_classes', lazy='dynamic'))


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    @orm.reconstructor
    def reconstruct(self):
        with db.session.no_autoflush:
            self.validate_presentations()


    @property
    def submissions(self):
        return get_count(self.periods)


    def disable(self):
        """
        Disable this project class
        :return:
        """

        self.active = False

        # remove this project class from any projects that have been attached with it
        for proj in self.projects:
            proj.project_classes.remove(self)


    def enable(self):
        """
        Enable this project class
        :return:
        """

        if self.available:
            self.active = True


    @property
    def available(self):
        """
        Determine whether this project class is available for use (or activation)
        :return:
        """

        # ensure that at least one active programme is available
        if not self.programmes.filter(DegreeProgramme.active).first():
            return False

        if self.uses_presentations:
            if get_count(self.periods.filter_by(has_presentation=True)) == 0:
                return False

        return True


    @property
    def convenor_email(self):
        return self.convenor.user.email


    @property
    def convenor_name(self):
        return self.convenor.user.name


    def is_convenor(self, id):
        """
        Determine whether a given user 'id' is a convenor for this project class
        :param id:
        :return:
        """
        if self.convenor_id == id:
            return True

        if any([item.id == id for item in self.coconvenors]):
            return True

        return False


    @property
    def ordered_programmes(self):
        return self.programmes \
            .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
            .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())


    def make_label(self, text=None, user_classes=None):
        if text is None:
            text = self.name

        return self._make_label(text, user_classes)


    def validate_periods(self, minimum_expected=0):
        if (self.periods is None or get_count(self.periods) == 0) and minimum_expected > 0:
            if current_user is not None:
                data = SubmissionPeriodDefinition(owner_id=self.id,
                                                  period=1,
                                                  name=None,
                                                  has_presentation=self.uses_presentations,
                                                  creator_id=current_user.id,
                                                  creation_timestamp=datetime.now())
                self.periods = [data]
                db.session.commit()
            else:
                raise RuntimeError('Cannot insert missing SubmissionPeriodDefinition')

        expected = 1
        modified = False
        for item in self.periods.order_by(SubmissionPeriodDefinition.period.asc()).all():
            if item.period != expected:
                item.period = expected
                modified = True

            expected += 1

        if modified:
            db.session.commit()


    def validate_presentations(self):
        if not self.uses_presentations:
            return

        self.validate_periods(minimum_expected=1)
        number_with_presentations = get_count(self.periods.filter_by(has_presentation=True))

        if number_with_presentations > 0:
            return

        data = self.periods.first()
        data.has_presentation = True
        db.session.commit()


@listens_for(ProjectClass, 'before_update')
def _ProjectClass_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)


@listens_for(ProjectClass, 'before_insert')
def _ProjectClass_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)


@listens_for(ProjectClass, 'before_delete')
def _ProjectClass_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)


class SubmissionPeriodDefinition(db.Model):
    """
    Record the configuration of an individual submission period
    """

    __tablename__ = 'period_definitions'


    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # link to parent ProjectClass
    owner_id = db.Column(db.Integer(), db.ForeignKey('project_classes.id'))
    owner = db.relationship('ProjectClass', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('periods', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # numerical submission period
    period = db.Column(db.Integer())

    # alternative textual name; can be left null if not used
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # does this period have a presentation submission?
    has_presentation = db.Column(db.Boolean())


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    @property
    def display_name(self):
        if self.name is not None and len(self.name) > 0:
            return self.name

        return 'Submission Period #{n}'.format(n=self.submission_period)


class ProjectClassConfig(db.Model):
    """
    Model current configuration options for each project class
    """

    # make table name plural
    __tablename__ = 'project_class_config'

    # id is really a surrogate key for (year, pclass_id) - need to ensure these remain unique
    id = db.Column(db.Integer(), primary_key=True)

    # year should match an available year in MainConfig
    year = db.Column(db.Integer(), db.ForeignKey('main_config.year'))
    main_config = db.relationship('MainConfig', uselist=False, backref=db.backref('project_classes', lazy='dynamic'))

    # id should be an available project class
    pclass_id = db.Column(db.Integer(), db.ForeignKey('project_classes.id'))
    project_class = db.relationship('ProjectClass', uselist=False, backref=db.backref('configs', lazy='dynamic'))

    # who was convenor in this year?
    convenor_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'))
    convenor = db.relationship('FacultyData', uselist=False, backref=db.backref('past_convenorships', lazy='dynamic'))

    # who created this record, ie. initiated the rollover of the academic year?
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', uselist=False, foreign_keys=[creator_id])

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())


    # SELECTOR LIFECYCLE MANAGEMENT

    # are faculty requests to confirm projects open?
    requests_issued = db.Column(db.Boolean())

    # deadline for confirmation requests
    request_deadline = db.Column(db.Date())

    # have we gone 'live' this year, ie. frozen a definitive 'live table' of projects and
    # made these available to students?
    live = db.Column(db.Boolean())

    # who signed-off on go live event?
    golive_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    golive_by = db.relationship('User', uselist=False, foreign_keys=[golive_id])

    # golive timestamp
    golive_timestamp = db.Column(db.DateTime())

    # deadline for students to make their choices on the live system
    live_deadline = db.Column(db.Date())

    # is project selection closed?
    selection_closed = db.Column(db.Boolean())

    # who signed-off on close event?
    closed_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    closed_by = db.relationship('User', uselist=False, foreign_keys=[closed_id])

    # closed timestamp
    closed_timestamp = db.Column(db.DateTime())

    # capture which faculty have still to sign-off on this configuration
    golive_required = db.relationship('FacultyData', secondary=golive_confirmation, lazy='dynamic',
                                      backref=db.backref('live', lazy='dynamic'))


    # SUBMISSION LIFECYCLE MANAGEMENT

    # current submission period
    submission_period = db.Column(db.Integer())

    # 'periods' member constructed by backreference from SubmissionPeriodRecord below


    # WORKLOAD MODEL

    # CATS awarded for supervising in this year
    CATS_supervision = db.Column(db.Integer())

    # CATS awarded for 2nd marking in this year
    CATS_marking = db.Column(db.Integer())

    # CATS awarded for presentation assssment in this year
    CATS_presentation = db.Column(db.Integer())


    @property
    def name(self):
        return self.project_class.name


    @property
    def abbreviation(self):
        return self.project_class.abbreviation


    @property
    def uses_marker(self):
        return self.project_class.uses_marker


    @property
    def do_matching(self):
        return self.project_class.do_matching


    @property
    def require_confirm(self):
        return self.project_class.require_confirm


    @property
    def initial_choices(self):
        return self.project_class.initial_choices


    @property
    def switch_choices(self):
        return self.project_class.switch_choices


    @property
    def start_year(self):
        return self.project_class.year


    @property
    def extent(self):
        return self.project_class.extent


    @property
    def submissions(self):
        return self.project_class.submissions


    @property
    def selection_open_to_all(self):
        return self.project_class.selection_open_to_all


    @property
    def supervisor_carryover(self):
        return self.project_class.supervisor_carryover


    @property
    def programmes(self):
        return self.project_class.programmes


    @property
    def ordered_programmes(self):
        return self.project_class.ordered_programmes


    @property
    def template_periods(self):
        return self.project_class.periods


    @property
    def _selection_open(self):
        return self.live and not self.selection_closed


    SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED = 1
    SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS = 2
    SELECTOR_LIFECYCLE_READY_GOLIVE = 3
    SELECTOR_LIFECYCLE_SELECTIONS_OPEN = 4
    SELECTOR_LIFECYCLE_READY_MATCHING = 5
    SELECTOR_LIFECYCLE_READY_ROLLOVER = 6


    @property
    def selector_lifecycle(self):
        # if gone live and closed, then either we are ready to match or we are read to rollover
        if self.live and self.selection_closed:
            if self.do_matching:

                # check whether a matching configuration has been assigned for the current year
                match = self.allocated_match

                if match is not None:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER
                else:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING

            else:
                return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER

        # open case is simple
        if self._selection_open:
            return ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN

        # if we get here, project is not open

        if self.require_confirm:
            if self.requests_issued:

                if self.golive_required.count() > 0:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS
                else:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE

            else:

                return ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED

        return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE


    SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY = 0
    SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY = 1
    SUBMITTER_LIFECYCLE_READY_ROLLOVER = 2


    @property
    def submitter_lifecycle(self):
        if self.submission_period > self.submissions:
            return ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER

        # get submission period data for current period
        period = self.current_period

        if period is None:
            template = self.template_periods.filter_by(period=self.submission_period).one()

            # allow period record to be auto-generated
            period = SubmissionPeriodRecord(config_id=self.id,
                                            name=template.name,
                                            has_presentation=template.has_presentation,
                                            retired=False,
                                            submission_period=self.submission_period,
                                            feedback_open=False,
                                            feedback_id=None,
                                            feedback_timestamp=None,
                                            feedback_deadline=None,
                                            closed=False,
                                            closed_id=None,
                                            closed_timestamp=None)
            db.session.add(period)
            db.session.commit()

        if not period.feedback_open:
            return self.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY

        if period.feedback_open and not period.closed:
            return self.SUBMITTER_LIFECYCLE_FEEDBACK_MARKING_ACTIVITY

        # can assume period.closed at this point
        if self.submission_period >= self.submissions:
            return ProjectClassConfig.SUBMITTER_LIFECYCLE_READY_ROLLOVER

        # we don't want to be in this position; we may as well advance the submission period
        # and return PROJECT_ACTIVITY
        self.submission_period += 1
        db.session.commit()

        return ProjectClassConfig.SUBMITTER_LIFECYCLE_PROJECT_ACTIVITY


    @property
    def allocated_match(self):
        return self.matching_attempts.filter_by(selected=True).first()


    @property
    def time_to_request_deadline(self):
        if self.request_deadline is None:
            return '<invalid>'

        delta = self.request_deadline - date.today()
        return format_readable_time(delta)


    @property
    def time_to_live_deadline(self):
        if self.live_deadline is None:
            return '<invalid>'

        delta = self.live_deadline - date.today()
        return format_readable_time(delta)


    @property
    def number_selectors(self):
        query = db.session.query(SelectingStudent).with_parent(self)
        return get_count(query)


    @property
    def number_submitters(self):
        query = db.session.query(SubmittingStudent).with_parent(self)
        return get_count(query)


    @property
    def selector_data(self):
        """
        Report simple statistics about selectors attached to this ProjectClassConfg instance.

        **
        BEFORE SELECTIONS ARE CLOSED,
        we report the total number of selectors, the number who have already made submissions, the number who have
        bookmarks but have not yet made a submission, and the number who are entirely missing.

        AFTER SELECTIONS ARE CLOSED,
        we report the total number of selectors, the number who made submissions,
        and the number who are entirely missing. This is because bookmarks are converted to SelectionRecords
        on project closure, if needed.
        :return:
        """

        if self.selector_lifecycle < self.SELECTOR_LIFECYCLE_READY_MATCHING:
            return self._open_selector_data

        return self._closed_selector_data


    @property
    def _open_selector_data(self):
        total = 0
        submitted = 0
        bookmarks = 0
        missing = 0

        for student in self.selecting_students:
            total += 1

            if student.has_submitted:
                submitted += 1

            if not student.has_submitted and student.has_bookmarks:
                bookmarks += 1

            if not student.has_submitted and not student.has_bookmarks:
                missing += 1

        return submitted, bookmarks, missing, total


    @property
    def _closed_selector_data(self):
        total = 0
        submitted = 0
        missing = 0

        for student in self.selecting_students:
            total += 1

            if student.has_submitted:
                submitted += 1
            else:
                missing += 1

        return submitted, missing, total


    @property
    def convenor_email(self):
        if self.convenor is not None and self.convenor.user is not None:
            return self.convenor.user.email
        else:
            raise RuntimeError('convenor not set')


    @property
    def convenor_name(self):
        if self.convenor is not None and self.convenor.user is not None:
            return self.convenor.user.name
        else:
            raise RuntimeError('convenor not set')


    def generate_golive_requests(self):
        """
        Generate sign-off requests to all active faculty
        :return:
        """
        # exit if called in error
        if not self.require_confirm:
            return

        # select faculty that are enrolled on this particular project class
        eq = db.session.query(EnrollmentRecord.id, EnrollmentRecord.owner_id) \
            .filter_by(pclass_id=self.pclass_id).subquery()
        fd = db.session.query(eq.c.owner_id, User, FacultyData) \
            .join(User, User.id == eq.c.owner_id) \
            .join(FacultyData, FacultyData.id == eq.c.owner_id) \
            .filter(User.active == True)

        for id, user, data in fd:
            if data not in self.golive_required:      # don't object if we are generating a duplicate request
                self.golive_required.append(data)


    @property
    def has_published_matches(self):
        query = self.matching_attempts.filter_by(published=True)
        return get_count(query) > 0


    def get_period(self, n):
        if n <= 0 or n > self.submissions:
            return None

        return self.periods.filter_by(submission_period=n).first()


    @property
    def current_period(self):
        return self.get_period(self.submission_period)


    @property
    def confirm_outstanding_count(self):
        return get_count(self.golive_required)


class SubmissionPeriodRecord(db.Model):
    """
    Capture details about a submission period
    """

    __tablename__ = 'submission_periods'

    id = db.Column(db.Integer(), primary_key=True)

    # parent ProjectClassConfig
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', foreign_keys=[config_id], uselist=False,
                             backref=db.backref('periods', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # submission period
    submission_period = db.Column(db.Integer(), index=True)

    # alternative textual name for this period (eg. "Autumn Term", "Spring Term");
    # can be null if not used
    name = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # does this submission period have an associated presentation assessment
    has_presentation = db.Column(db.Boolean())

    # retired flag, set by rollover code
    retired = db.Column(db.Boolean(), index=True)

    # has feedback been opened in this period
    feedback_open = db.Column(db.Boolean())

    # who opened feedback?
    feedback_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    feedback_by = db.relationship('User', uselist=False, foreign_keys=[feedback_id])

    # feedback opened timestamp
    feedback_timestamp = db.Column(db.DateTime())

    # deadline for feedback to be submitted
    feedback_deadline = db.Column(db.DateTime())

    # has this period been closed?
    closed = db.Column(db.Boolean())

    # who closed the period?
    closed_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    closed_by = db.relationship('User', uselist=False, foreign_keys=[closed_id])

    # closed timestamp
    closed_timestamp = db.Column(db.DateTime())


    @property
    def display_name(self):
        if self.name is not None and len(self.name) > 0:
            return self.name

        return 'Submission Period #{n}'.format(n=self.submission_period)


    @property
    def time_to_feedback_deadline(self):
        if self.feedback_deadline is None:
            return '<invalid>'

        delta = self.feedback_deadline.date() - date.today()
        return format_readable_time(delta)


    def get_supervisor_records(self, fac_id):
        # querying for the SubmissionRecords attached to a given faculty member requires a join
        # to the liveprojects table
        students = self.config.submitting_students.subquery()

        return db.session.query(SubmissionRecord) \
            .join(students, students.c.id == SubmissionRecord.owner_id) \
            .filter(SubmissionRecord.submission_period == self.submission_period) \
            .join(LiveProject) \
            .filter(LiveProject.owner_id == fac_id) \
            .join(User, User.id == students.c.student_id) \
            .order_by(SubmissionRecord.submission_period.asc(), LiveProject.number.asc(),
                      User.last_name.asc(), User.first_name.asc()).all()


    def get_marker_records(self, fac_id):
        students = self.config.submitting_students.subquery()

        return db.session.query(SubmissionRecord) \
            .join(students, students.c.id == SubmissionRecord.owner_id) \
            .filter(SubmissionRecord.submission_period == self.submission_period) \
            .filter(SubmissionRecord.marker_id == fac_id) \
            .join(StudentData, StudentData.id == students.c.student_id) \
            .order_by(SubmissionRecord.submission_period.asc(), StudentData.exam_number).all()

    @property
    def submitter_list(self):
        students = self.config.submitting_students.subquery()

        return db.session.query(SubmissionRecord) \
            .join(students, students.c.id == SubmissionRecord.owner_id) \
            .filter(SubmissionRecord.submission_period == self.submission_period)


    @property
    def projects_list(self):
        students = self.config.submitting_students.subquery()

        records = db.session.query(SubmissionRecord.project_id) \
            .join(students, students.c.id == SubmissionRecord.owner_id) \
            .filter(SubmissionRecord.submission_period == self.submission_period).subquery()

        return db.session.query(LiveProject) \
            .join(records, records.c.project_id == LiveProject.id).distinct()


    @property
    def number_projects(self):
        return get_count(self.projects_list)


    @property
    def assessors_list(self):
        projects = self.projects_list.subquery()

        assessors = db.session.query(live_assessors.c.faculty_id) \
            .join(projects, projects.c.id == live_assessors.c.project_id).distinct().subquery()

        return db.session.query(FacultyData) \
            .join(assessors, assessors.c.faculty_id == FacultyData.id)


    @property
    def label(self):
        return self.config.project_class.make_label(self.config.abbreviation + ': ' + self.display_name)



class EnrollmentRecord(db.Model):
    """
    Capture details about a faculty member's enrollment in a single project class
    """

    __tablename__ = 'enrollment_record'

    id = db.Column(db.Integer(), primary_key=True)

    # pointer to project class for which this is an enrollment record
    pclass_id = db.Column(db.Integer(), db.ForeignKey('project_classes.id'))
    pclass = db.relationship('ProjectClass', uselist=False, foreign_keys=[pclass_id])

    # pointer to faculty member this record is associated with
    owner_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'))
    owner = db.relationship('FacultyData', uselist=False, foreign_keys=[owner_id],
                            backref=db.backref('enrollments', lazy='dynamic', cascade='all, delete, delete-orphan'))


    # SUPERVISOR STATUS

    # enrollment for supervision
    SUPERVISOR_ENROLLED = 1
    SUPERVISOR_SABBATICAL = 2
    SUPERVISOR_EXEMPT = 3
    supervisor_choices = [(SUPERVISOR_ENROLLED, 'Normally enrolled'),
                          (SUPERVISOR_SABBATICAL, 'On sabbatical or buy-out'),
                          (SUPERVISOR_EXEMPT, 'Exempt')]
    supervisor_state = db.Column(db.Integer(), index=True)

    # comment (eg. can be used to note circumstances of exemptions)
    supervisor_comment = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # sabbatical auto re-enroll year (after sabbatical)
    supervisor_reenroll = db.Column(db.Integer())


    # MARKER STATUS

    # enrollment for 2nd marking
    MARKER_ENROLLED = 1
    MARKER_SABBATICAL = 2
    MARKER_EXEMPT = 3
    marker_choices = [(MARKER_ENROLLED, 'Normally enrolled'),
                      (MARKER_SABBATICAL, 'On sabbatical or buy-out'),
                      (MARKER_EXEMPT, 'Exempt')]
    marker_state = db.Column(db.Integer(), index=True)

    # comment (eg. can be used to note circumstances of exemption)
    marker_comment = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # marker auto re-enroll year (after sabbatical)
    marker_reenroll = db.Column(db.Integer())


    # PRESENTATION ASSESSOR STATUS

    # enrollment for assessing talks
    PRESENTATIONS_ENROLLED = 1
    PRESENTATIONS_SABBATICAL = 2
    PRESENTATIONS_EXEMPT = 3
    presentations_choices = [(MARKER_ENROLLED, 'Normally enrolled'),
                             (MARKER_SABBATICAL, 'On sabbatical or buy-out'),
                             (MARKER_EXEMPT, 'Exempt')]
    presentations_state = db.Column(db.Integer(), index=True)

    # comment (eg. can be used to note circumstances of exemption)
    presentations_comment = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # marker auto re-enroll year (after sabbatical)
    presentations_reenroll = db.Column(db.Integer())


    # METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    @orm.reconstructor
    def _reconstruct(self):
        if self.supervisor_state is None:
            self.supervisor_state = EnrollmentRecord.SUPERVISOR_ENROLLED

        if self.marker_state is None:
            self.marker_state = EnrollmentRecord.MARKER_ENROLLED

        if self.presentations_state is None:
            self.presentations_state = EnrollmentRecord.PRESENTATIONS_ENROLLED


    @property
    def supervisor_label(self):

        if self.supervisor_state == self.SUPERVISOR_ENROLLED:
            return '<span class="label label-success"><i class="fa fa-check"></i> Supervisor: active</span>'
        elif self.supervisor_state == self.SUPERVISOR_SABBATICAL:
            return '<span class="label label-warning"><i class="fa fa-times"></i> Supervisor: sab{year}</span>'.format(
                year='' if self.supervisor_reenroll is None else ' ({yr})'.format(yr=self.supervisor_reenroll))
        elif self.supervisor_state == self.SUPERVISOR_EXEMPT:
            return '<span class="label label-danger"><i class="fa fa-times"></i> Supervisor: exempt</span>'

        return '<span class="label label-danger">Unknown state</span>'


    @property
    def marker_label(self):

        if self.marker_state == EnrollmentRecord.MARKER_ENROLLED:
            return '<span class="label label-success"><i class="fa fa-check"></i> Marker: active</span>'
        elif self.marker_state == EnrollmentRecord.MARKER_SABBATICAL:
            return '<span class="label label-warning"><i class="fa fa-times"></i> Marker: sab{year}</span>'.format(
                year='' if self.marker_reenroll is None else ' ({yr})'.format(yr=self.marker_reenroll))
        elif self.marker_state == EnrollmentRecord.MARKER_EXEMPT:
            return '<span class="label label-danger"><i class="fa fa-times"></i> Marker: exempt</span>'

        return '<span class="label label-danger">Unknown state</span>'


    @property
    def presentation_label(self):

        if self.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED:
            return '<span class="label label-success"><i class="fa fa-check"></i> Presentations: active</span>'
        elif self.presentations_state == EnrollmentRecord.PRESENTATIONS_SABBATICAL:
            return '<span class="label label-warning"><i class="fa fa-times"></i> Presentations: sab{year}</span>'.format(
                year='' if self.presentations_reenroll is None else ' ({yr})'.format(yr=self.presentations_reenroll))
        elif self.presentations_state == EnrollmentRecord.PRESENTATIONS_EXEMPT:
            return '<span class="label label-danger"><i class="fa fa-times"></i> Presentations: exempt</span>'

        return '<span class="label label-danger">Unknown state</span>'


    @property
    def enrolled_labels(self):
        label = self.supervisor_label
        if self.pclass.uses_marker:
            label += ' ' + self.marker_label
        if self.pclass.uses_presentations:
            label += ' ' + self.presentation_label

        return label


@listens_for(EnrollmentRecord, 'before_update')
def _EnrollmentRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)


@listens_for(EnrollmentRecord, 'before_insert')
def _EnrollmentRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)


@listens_for(EnrollmentRecord, 'before_delete')
def _EnrollmentRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable)
        cache.delete_memoized(_Project_num_assessors)


class Supervisor(db.Model, ColouredLabelMixin):
    """
    Model a supervision team member
    """

    # make table name plural
    __tablename__ = 'supervision_team'

    id = db.Column(db.Integer(), primary_key=True)

    # role name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True)

    # role abbreviation
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True, index=True)

    # active flag
    active = db.Column(db.Boolean())

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def disable(self):
        """
        Disable this supervisory role and cascade, ie. remove from any projects that have been labelled with it
        :return:
        """

        self.active = False

        # remove this supervisory role from any projects that have been labelled with it
        for proj in self.projects:
            proj.team.remove(self)


    def enable(self):
        """
        Enable this supervisory role
        :return:
        """

        self.active = True


    def make_label(self, text=None, user_classes=None):
        if text is None:
            text = self.abbreviation

        return self._make_label(text, user_classes)


@cache.memoize()
def _Project_is_offerable(pid):
    """
    Determine whether a given Project instance is offerable.
    Must be implemented as a simple function to work well with Flask-Caching.
    This is quite annoying but there seems no reliable workaround, and we can't live without caching.
    :param pid:
    :return:
    """
    project = db.session.query(Project).filter_by(id=pid).one()

    if get_count(project.project_classes.filter(ProjectClass.active)) == 0:
        return False, "No active project types assigned to project"

    if project.group is None:
        return False, "No active research group affiliated with project"

    # for each project class we are attached to, check whether enough assessors have been assigned
    # and whether a project description is available
    for pclass in project.project_classes:
        if pclass.uses_marker:
            if project.num_assessors(pclass) < pclass.number_assessors:
                return False, "Too few assessors assigned for '{name}'".format(name=pclass.name)

        desc = project.get_description(pclass)

        if desc is None:
            return False, "No project description assigned for '{name}'".format(name=pclass.name)

        if get_count(desc.team.filter(Supervisor.active)) == 0:
            return False, "No active supervisory roles assigned for '{name}'".format(name=pclass.name)

        if project.enforce_capacity:
            if desc.capacity is None or desc.capacity <= 0:
                return False, "Capacity is zero or unset for '{name}', " \
                              "but enforcement is enabled".format(name=pclass.name)

    return True, None


@cache.memoize()
def _Project_num_assessors(pid, pclass_id):
    project = db.session.query(Project).filter_by(id=pid).one()
    return get_count(project.assessor_list_query(pclass_id))


class Project(db.Model):
    """
    Model a project
    """

    # make table name plural
    __tablename__ = "projects"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # project name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True, index=True)

    # active flag
    active = db.Column(db.Boolean())

    # which faculty member owns this project?
    owner_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'), index=True)
    owner = db.relationship('FacultyData', foreign_keys=[owner_id], backref=db.backref('projects', lazy='dynamic'))


    # TAGS AND METADATA

    # free keywords describing scientific area
    keywords = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # which research group is associated with this project?
    group_id = db.Column(db.Integer(), db.ForeignKey('research_groups.id'), index=True)
    group = db.relationship('ResearchGroup', backref=db.backref('projects', lazy='dynamic'))

    # which project classes are associated with this project?
    project_classes = db.relationship('ProjectClass', secondary=project_classes, lazy='dynamic',
                                      backref=db.backref('projects', lazy='dynamic'))

    # which transferable skills are associated with this project?
    skills = db.relationship('TransferableSkill', secondary=project_skills, lazy='dynamic',
                             backref=db.backref('projects', lazy='dynamic'))

    # which degree programmes are preferred for this project?
    programmes = db.relationship('DegreeProgramme', secondary=project_programmes, lazy='dynamic',
                                 backref=db.backref('projects', lazy='dynamic'))


    # SELECTION

    # is a meeting required before selecting this project?
    MEETING_REQUIRED = 1
    MEETING_OPTIONAL = 2
    MEETING_NONE = 3
    meeting_reqd = db.Column(db.Integer())


    # MATCHING

    # impose limitation on capacity
    enforce_capacity = db.Column(db.Boolean())

    # table of allowed assessors
    assessors = db.relationship('FacultyData', secondary=assessors, lazy='dynamic',
                                backref=db.backref('assessor_for', lazy='dynamic'))


    # PROJECT DESCRIPTION

    # 'descriptions' field is established by backreference from ProjectDescription
    # (this works well but is a bit awkward because it creates a circular dependency between
    # Project and ProjectDescription which we solve using the SQLAlchemy post_update option)

    # link to default description, if one exists
    default_id = db.Column(db.Integer(), db.ForeignKey('descriptions.id'))
    default = db.relationship('ProjectDescription', foreign_keys=[default_id], uselist=False, post_update=True,
                              backref=db.backref('default', uselist=False))


    # POPULARITY DISPLAY

    # show popularity estimate
    show_popularity = db.Column(db.Boolean())

    # show number of selections
    show_selections = db.Column(db.Boolean())

    # show number of bookmarks
    show_bookmarks = db.Column(db.Boolean())


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error = None


    @orm.reconstructor
    def _reconstruct(self):
        self.error = None


    @property
    def show_popularity_data(self):
        return False


    def disable(self):
        """
        Disable this project
        :return:
        """

        self.active = False


    def enable(self):
        """
        Enable this project
        :return:
        """

        self.active = True


    @property
    def is_offerable(self):
        """
        Determine whether this project is available for selection
        :return:
        """
        flag, self.error = _Project_is_offerable(self.id)

        return flag



    @property
    def is_deletable(self):
        return get_count(self.live_projects) == 0


    def add_skill(self, skill):
        self.skills.append(skill)


    def remove_skill(self, skill):
        self.skills.remove(skill)


    @property
    def ordered_skills(self):
        return self.skills \
            .join(SkillGroup, SkillGroup.id == TransferableSkill.group_id) \
            .order_by(SkillGroup.name.asc(),
                      TransferableSkill.name.asc())


    def add_programme(self, prog):
        self.programmes.append(prog)


    def remove_programme(self, prog):
        self.programmes.remove(prog)


    @property
    def ordered_programmes(self):
        return self.programmes \
            .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
            .order_by(DegreeType.name.asc(), DegreeProgramme.name.asc())


    def remove_project_class(self, pclass):
        self.project_classes.remove(pclass)


    @property
    def available_degree_programmes(data):
        """
        Computes the degree programmes available to this project, from knowing which project
        classes it is available to
        :param data:
        :return:
        """
        # get list of active degree programmes relevant for our degree classes;
        # to do this we have to build a rather complex UNION query
        queries = []
        for proj_class in data.project_classes:
            queries.append(
                DegreeProgramme.query.filter(DegreeProgramme.active,
                                             DegreeProgramme.project_classes.any(id=proj_class.id)))

        if len(queries) > 0:
            q = queries[0]
            for query in queries[1:]:
                q = q.union(query)
        else:
            q = None

        return q


    def validate_programmes(self):
        """
        Validate that the degree programmes associated with this project
        are valid, given the current project class associations
        :return:
        """

        available_programmes = self.available_degree_programmes
        if available_programmes is None:
            self.programmes = []
            return

        for prog in self.programmes:
            if prog not in available_programmes:
                self.remove_programme(prog)


    def is_assessor(self, faculty):
        """
        Determine whether a given FacultyData instance is a 2nd marker for this project
        :param faculty:
        :return:
        """
        return faculty in self.assessors


    def num_assessors(self, pclass):
        """
        Determine the number of assessors enrolled who are available for a given project class
        :param pclass:
        :return:
        """
        return _Project_num_assessors(self.id, pclass.id)


    def assessor_list_query(self, pclass):
        if isinstance(pclass, int):
            pclass_id = pclass
        else:
            pclass_id = pclass.id

        query = self.assessors \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active == True) \
            .join(EnrollmentRecord, EnrollmentRecord.owner_id == FacultyData.id) \
            .filter(EnrollmentRecord.pclass_id == pclass_id,
                    or_(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED,
                        EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED)) \
            .order_by(User.last_name.asc(), User.first_name.asc())

        return query


    def get_assessor_list(self, pclass):
        """
        Build a list of FacultyData objects for assessors attached to this project who are
        available for a given project class
        :param pclass:
        :return:
        """
        return self.assessor_list_query(pclass).all()


    def can_enroll_marker(self, faculty):
        """
        Determine whether a given FacultyData instance can be enrolled as an assessor for this project
        :param faculty:
        :return:
        """
        if self.is_assessor(faculty):
            return False

        if not faculty.user.active:
            return False

        # need to determine whether this faculty member is enrolled as a second marker for any project
        # class we are attached to
        pclasses = self.project_classes.subquery()

        query = faculty.enrollments \
            .join(pclasses, pclasses.c.id == EnrollmentRecord.pclass_id) \
            .filter(or_(EnrollmentRecord.marker_state == EnrollmentRecord.MARKER_ENROLLED,
                        EnrollmentRecord.presentations_state == EnrollmentRecord.PRESENTATIONS_ENROLLED))

        return get_count(query) > 0


    def add_assessor(self, faculty):
        """
        Add a FacultyData instance as a 2nd marker
        :param faculty:
        :return:
        """
        if self.is_assessor(faculty):
            return

        self.assessors.append(faculty)
        db.session.commit()


    def remove_assessor(self, faculty):
        """
        Remove a FacultyData instance as a 2nd marker
        :param faculty:
        :return:
        """
        if not self.is_assessor(faculty):
            return

        self.assessors.remove(faculty)
        db.session.commit()


    def get_description(self, pclass):
        """
        Gets the ProjectDescription instance for project class pclass, or returns None if no
        description is available
        :param pclass:
        :return:
        """
        desc = self.descriptions.filter(ProjectDescription.project_classes.any(id=pclass.id)).first()
        if desc is not None:
            return desc

        return self.default


    def get_capacity(self, pclass):
        """
        Get the available capacity for a given pclass, or return None if unset
        :param pclass:
        :return:
        """
        desc = self.get_description(pclass)

        if desc is None:
            return None

        return desc.capacity


@listens_for(Project, 'before_update')
def _Project_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.id)

        for pclass in target.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.id, pclass.id)


@listens_for(Project, 'before_insert')
def _Project_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.id)

        for pclass in target.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.id, pclass.id)



class ProjectDescription(db.Model):
    """
    Capture a project description. Projects can have multiple descriptions, each
    attached to a set of project classes
    """

    __tablename__ = "descriptions"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # owning project
    parent_id = db.Column(db.Integer(), db.ForeignKey('projects.id'))
    parent = db.relationship('Project', foreign_keys=[parent_id], uselist=False,
                             backref=db.backref('descriptions', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # which project classes are associated with this description?
    project_classes = db.relationship('ProjectClass', secondary=description_pclasses, lazy='dynamic',
                                      backref=db.backref('descriptions', lazy='dynamic'))

    # label
    label = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # description
    description = db.Column(db.Text())

    # recommended reading
    reading = db.Column(db.Text())

    # supervisory roles
    team = db.relationship('Supervisor', secondary=description_supervisors, lazy='dynamic',
                           backref=db.backref('descriptions', lazy='dynamic'))

    # maximum number of students
    capacity = db.Column(db.Integer())


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


@listens_for(ProjectDescription, 'before_update')
def _ProjectDescription_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.parent_id)

        for pclass in target.parent.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.parent_id, pclass.id)


@listens_for(ProjectDescription, 'before_insert')
def _ProjectDescription_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.parent_id)

        for pclass in target.parent.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.parent_id, pclass.id)


@listens_for(ProjectDescription, 'before_delete')
def _ProjectDescription_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_Project_is_offerable, target.parent_id)

        for pclass in target.parent.project_classes:
            cache.delete_memoized(_Project_num_assessors, target.parent_id, pclass.id)


class LiveProject(db.Model):
    """
    The definitive live project table
    """

    __tablename__ = 'live_projects'


    # surrogate key for (config_id, number) -- need to ensure these are unique!
    id = db.Column(db.Integer(), primary_key=True)

    # key to ProjectClassConfig record that identifies the year and pclass
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', uselist=False,
                             backref=db.backref('live_projects', lazy='dynamic'))

    # key linking to parent project
    parent_id = db.Column(db.Integer(), db.ForeignKey('projects.id'))
    parent = db.relationship('Project', uselist=False,
                             backref=db.backref('live_projects', lazy='dynamic'))

    # definitive project number in this year
    number = db.Column(db.Integer())

    # project name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)

    # which faculty member owns this project?
    owner_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'), index=True)
    owner = db.relationship('FacultyData', foreign_keys=[owner_id],
                            backref=db.backref('live_projects', lazy='dynamic'))


    # TAGS AND METADATA

    # free keywords describing scientific area
    keywords = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # which research group is associated with this project?
    group_id = db.Column(db.Integer(), db.ForeignKey('research_groups.id'), index=True)
    group = db.relationship('ResearchGroup', backref=db.backref('live_projects', lazy='dynamic'))

    # which transferable skills are associated with this project?
    skills = db.relationship('TransferableSkill', secondary=live_project_skills, lazy='dynamic',
                             backref=db.backref('live_projects', lazy='dynamic'))

    # which degree programmes are preferred for this project?
    programmes = db.relationship('DegreeProgramme', secondary=live_project_programmes, lazy='dynamic',
                                 backref=db.backref('live_projects', lazy='dynamic'))


    # SELECTION

    # is a meeting required before selecting this project?
    MEETING_REQUIRED = 1
    MEETING_OPTIONAL = 2
    MEETING_NONE = 3
    meeting_reqd = db.Column(db.Integer())


    # MATCHING

    # impose limitation on capacity
    enforce_capacity = db.Column(db.Boolean())

    # maximum number of students
    capacity = db.Column(db.Integer())

    # table of allowed assessors
    assessors = db.relationship('FacultyData', secondary=live_assessors, lazy='dynamic',
                                backref=db.backref('assessor_for_live', lazy='dynamic'))


    # PROJECT DESCRIPTION

    # project description
    description = db.Column(db.Text())

    # recommended reading
    reading = db.Column(db.Text())

    # supervisor roles
    team = db.relationship('Supervisor', secondary=live_project_supervision, lazy='dynamic',
                           backref=db.backref('live_projects', lazy='dynamic'))


    # POPULARITY DISPLAY

    # show popularity estimate
    show_popularity = db.Column(db.Boolean())

    # show number of selections
    show_selections = db.Column(db.Boolean())

    # show number of bookmarks
    show_bookmarks = db.Column(db.Boolean())


    # METADATA

    # count number of page views
    page_views = db.Column(db.Integer())

    # date of last view
    last_view = db.Column(db.DateTime())


    def is_available(self, sel):
        """
        determine whether a this LiveProject is available for selection to a particular SelectingStudent
        :param sel:
        :return:
        """

        # if project doesn't require sign off, is always available
        # if project owner doesn't require confirmation, is always available
        if self.meeting_reqd != self.MEETING_REQUIRED or self.owner.sign_off_students is False:
            return True

        # otherwise, check if sel is in list of confirmed students
        if self.meeting_confirmed(sel):
            return True

        return False


    def meeting_confirmed(self, sel):
        if sel in self.confirmed_students:
            return True


    @property
    def ordered_skills(self):
        return self.skills \
            .join(SkillGroup, SkillGroup.id == TransferableSkill.group_id) \
            .order_by(SkillGroup.name.asc(),
                      TransferableSkill.name.asc())


    def _get_popularity_attr(self, getter):
        record = PopularityRecord.query \
            .filter_by(liveproject_id=self.id) \
            .order_by(PopularityRecord.datestamp.desc()).first()

        now = datetime.now()

        # return None if no value stored, or if stored value is too stale (> 1 day old)
        if record is None or (now - record.datestamp) > timedelta(days=1):
            return None

        return getter(record)


    @property
    def popularity_score(self):
        def getter(record):
            return record.score

        return self._get_popularity_attr(getter)


    @property
    def popularity_rank(self):
        def getter(record):
            return record.score_rank, record.total_number

        value = self._get_popularity_attr(getter)

        return value


    @property
    def lowest_popularity_rank(self):
        def getter(record):
            return record.lowest_score_rank

        value = self._get_popularity_attr(getter)

        return value


    @property
    def views_rank(self):
        def getter(record):
            return record.views_rank, record.total_number

        return self._get_popularity_attr(getter)


    @property
    def bookmarks_rank(self):
        def getter(record):
            return record.bookmarks_rank, record.total_number

        return self._get_popularity_attr(getter)


    @property
    def selections_rank(self):
        def getter(record):
            return record.selections_rank, record.total_number

        return self._get_popularity_attr(getter)


    @property
    def show_popularity_data(self):
        return self.parent.show_popularity or self.parent.show_bookmarks or self.parent.show_selections


    @property
    def number_bookmarks(self):
        return get_count(self.bookmarks)


    @property
    def number_selections(self):
        return get_count(self.selections)


    @property
    def number_pending(self):
        return get_count(self.confirm_waiting)


    @property
    def number_confirmed(self):
        return get_count(self.confirmed_students)


    def format_popularity_label(self, css_classes=None):
        if not self.parent.show_popularity:
            return None

        return self.popularity_label(css_classes)


    def popularity_label(self, css_classes=None):
        cls = '' if css_classes is None else ' '.join(css_classes)

        score = self.popularity_rank
        if score is None:
            return '<span class="label label-default {cls}">Popularity score unavailable</span>'.format(cls=cls)

        rank, total = score
        lowest_rank = self.lowest_popularity_rank

        # don't report popularity data if there isn't enough differentiation between projects for it to be
        # meaningful. Remember the lowest rank is actually numerically the highest number.
        # We report scores only if there is enoug differentiation to push this rank above the 50th percentile
        frac = float(rank)/float(total)
        lowest_frac = float(lowest_rank)/float(total)

        if lowest_frac < 0.5:
            return '<span class="label label-default {cls}">Insufficient data for popularity score</span>'.format(cls=cls)

        label = 'Low'
        if frac < 0.1:
            label = 'Very high'
        elif frac < 0.3:
            label = 'High'
        elif frac < 0.5:
            label = 'Medium'

        return '<span class="label label-success {cls}">Popularity: {label}</span>'.format(cls=cls, label=label)


    def format_bookmarks_label(self, css_classes=None):
        if not self.parent.show_bookmarks:
            return None

        return self.bookmarks_label(css_classes)


    def bookmarks_label(self, css_classes=None):
        pl = 's' if self.number_bookmarks != 1 else ''
        cls = '' if css_classes is None else ' '.join(css_classes)
        return '<span class="label label-info {cls}">{n} bookmark{pl}</span>'.format(cls=cls, n=self.number_bookmarks, pl=pl)


    def views_label(self, css_classes=None):
        pl = 's' if self.page_views != 1 else ''
        return '<span class="label label-info">{n} view{pl}</span>'.format(n=self.page_views, pl=pl)


    def format_selections_label(self, css_classes=None):
        if not self.parent.show_selections:
            return None

        return self.selections_label(css_classes)


    def selections_label(self, css_classes=None):
        pl = 's' if self.number_selections != 1 else ''
        cls = '' if css_classes is None else ' '.join(css_classes)
        return '<span class="label label-primary {cls}">{n} selection{pl}</span>'.format(cls=cls, n=self.number_selections, pl=pl)


    def satisfies_preferences(self, sel):
        number_preferences = get_count(self.programmes)
        number_matches = get_count(self.programmes.filter_by(id=sel.student.programme_id))

        if number_matches == 1:
            return True

        if number_matches > 1:
            raise RuntimeError('Inconsistent number of degree preferences match a single SelectingStudent')

        if number_matches == 0 and number_preferences == 0:
            return None

        return False


    @property
    def assessor_list_query(self):
        return self.assessors \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active == True) \
            .order_by(User.last_name.asc(), User.first_name.asc())


    @property
    def assessor_list(self):
        return self.assessor_list_query.all()


class SelectingStudent(db.Model):
    """
    Model a student who is selecting a project in the current cycle
    """

    __tablename__ = 'selecting_students'


    id = db.Column(db.Integer(), primary_key=True)

    # retired flag
    retired = db.Column(db.Boolean(), index=True)

    # key to ProjectClass config record that identifies this year and pclass
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', uselist=False,
                             backref=db.backref('selecting_students', lazy='dynamic'))

    # key to student userid
    student_id = db.Column(db.Integer(), db.ForeignKey('student_data.id'))
    student = db.relationship('StudentData', foreign_keys=[student_id], uselist=False,
                              backref=db.backref('selecting', lazy='dynamic'))

    # confirmation requests issued
    confirm_requests = db.relationship('LiveProject', secondary=confirmation_requests, lazy='dynamic',
                                       backref=db.backref('confirm_waiting', lazy='dynamic'))

    # confirmation requests granted
    confirmed = db.relationship('LiveProject', secondary=faculty_confirmations, lazy='dynamic',
                                backref=db.backref('confirmed_students', lazy='dynamic'))

    # research group filters applied
    group_filters = db.relationship('ResearchGroup', secondary=sel_group_filter_table, lazy='dynamic',
                                    backref=db.backref('filtering_students', lazy='dynamic'))

    # transferable skill group filters applied
    skill_filters = db.relationship('SkillGroup', secondary=sel_skill_filter_table, lazy='dynamic',
                                    backref=db.backref('filtering_students', lazy='dynamic'))


    # SELECTION METADATA

    # 'selections' field is added by backreference from SelectionRecord
    # 'bookmarks' field is added by backreference from Bookmark

    # record time of last selection submission
    submission_time = db.Column(db.DateTime())

    # record IP address of selection request
    submission_IP = db.Column(db.String(IP_LENGTH))


    @property
    def number_pending(self):
        return get_count(self.confirm_requests)


    @property
    def number_confirmed(self):
        return get_count(self.confirmed)


    @property
    def has_bookmarks(self):
        """
        determine whether this SelectingStudent has bookmarks
        :return:
        """
        return self.bookmarks.first() is not None


    @property
    def ordered_bookmarks(self):
        """
        return bookmarks in rank order
        :return:
        """
        return self.bookmarks.order_by(Bookmark.rank)


    @property
    def number_bookmarks(self):
        return get_count(self.bookmarks)


    @property
    def academic_year(self):
        """
        Compute the current academic year for this student, relative to our ProjectClassConfig record
        :return:
        """
        return self.student.academic_year(self.config.year)


    @property
    def academic_year_label(self):
        return self.student.academic_year_label(self.config.year)


    @property
    def is_initial_selection(self):
        """
        Determine whether this is the initial selection or a switch
        :return:
        """
        return self.academic_year == self.config.start_year - 1


    @property
    def is_optional(self):
        """
        Determine whether this selection is optional (an example would be to sign-up for a research placement project).
        Optional means that the individual's degree programme isn't one of the programmes associated with the
        project class
        :return:
        """
        return self.student.programme not in self.config.project_class.programmes


    @property
    def number_choices(self):
        """
        Compute the number of choices this student should make
        :return:
        """
        if self.is_initial_selection:
            return self.config.project_class.initial_choices

        else:
            return self.config.project_class.switch_choices


    @property
    def is_valid_selection(self):
        """
        Determine whether the current selection is valid
        :return:
        """
        num_choices = self.number_choices

        if self.bookmarks.count() < num_choices:
            return False

        count = 0
        for item in self.bookmarks.order_by(Bookmark.rank).all():
            if not item.liveproject.is_available(self):
                return False

            count += 1
            if count >= num_choices:
                break

        return True


    @property
    def has_submitted(self):
        """
        Determine whether a submission has been made
        :return:
        """
        return self.selections.first() is not None


    def is_project_submitted(self, proj):
        if not self.has_submitted:
            return False

        for item in self.selections:
            if item.liveproject_id == proj.id:
                return True

        return False


    def is_project_bookmarked(self, proj):
        if not self.has_bookmarks:
            return False

        for item in self.bookmarks:
            if item.liveproject_id == proj.id:
                return True

        return False


    @property
    def ordered_selection(self):
        return self.selections.order_by(SelectionRecord.rank)


    def project_rank(self, proj_id):
        # ignore bookmarks; these will have been converted to
        # SelectionRecords after closure if needed, and project_rank() is only really
        # meaningful once selections have closed
        if self.has_submitted:
            for item in self.selections.all():
                if item.liveproject_id == proj_id:
                    return item.rank
            return None

        return None


class SubmittingStudent(db.Model):
    """
    Model a student who is submitting work for evaluation in the current cycle
    """

    __tablename__ = 'submitting_students'


    id = db.Column(db.Integer(), primary_key=True)

    # retired flag
    retired = db.Column(db.Boolean(), index=True)

    # key to ProjectClass config record that identifies this year and pclass
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', uselist=False,
                             backref=db.backref('submitting_students', lazy='dynamic'))

    # key to student userid
    student_id = db.Column(db.Integer(), db.ForeignKey('student_data.id'))
    student = db.relationship('StudentData', foreign_keys=[student_id], uselist=False,
                              backref=db.backref('submitting', lazy='dynamic'))

    # capture parent SelectingStudent, if one exists
    selector_id = db.Column(db.Integer(), db.ForeignKey('selecting_students.id'), default=None)
    selector = db.relationship('SelectingStudent', foreign_keys=[selector_id], uselist=False,
                               backref=db.backref('submitters', lazy='dynamic'))

    # are the assignments published to the student?
    published = db.Column(db.Boolean())


    @property
    def academic_year(self):
        """
        Compute the current academic year for this student, relative this ProjectClassConfig
        :return:
        """
        return self.student.academic_year(self.config.year)


    @property
    def academic_year_label(self):
        return self.student.academic_year_label(self.config.year)


    def get_assignment(self, period):
        records = self.records.filter_by(submission_period=period).all()

        if len(records) == 0:
            return None
        elif len(records) == 1:
            return records[0]

        raise RuntimeError('Too many projects assigned for this submission period')


    @property
    def ordered_assignments(self):
        return self.records.order_by(SubmissionRecord.submission_period.asc())


    @property
    def supervisor_feedback_late(self):
        supervisor_states = [r.supervisor_feedback_state == SubmissionRecord.FEEDBACK_LATE for r in self.records]
        response_states = [r.supervisor_response_state == SubmissionRecord.FEEDBACK_LATE for r in self.records]

        return any(supervisor_states) or any(response_states)


    @property
    def marker_feedback_late(self):
        marker_states = [r.marker_feedback_state == SubmissionRecord.FEEDBACK_LATE for r in self.records]

        return any(marker_states)


    @property
    def has_late_feedback(self):
        return self.supervisor_feedback_late or self.marker_feedback_late


    @property
    def has_not_started_flags(self):
        return self.records.filter(SubmissionRecord.submission_period <= self.config.submission_period,
                                   SubmissionRecord.student_engaged == False).count() > 0


class SubmissionRecord(db.Model):
    """
    Collect details for a student submission
    """

    __tablename__ = "submission_records"


    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # submission period this record is associated with
    submission_period = db.Column(db.Integer(), index=True)

    # retired flag, set by rollover code
    retired = db.Column(db.Boolean(), index=True)

    # id of owning SubmittingStudent
    owner_id = db.Column(db.Integer(), db.ForeignKey('submitting_students.id'))
    owner = db.relationship('SubmittingStudent', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('records', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # assigned project
    project_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'), default=None)
    project = db.relationship('LiveProject', foreign_keys=[project_id], uselist=False,
                              backref=db.backref('submission_records', lazy='dynamic'))

    # assigned marker
    marker_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'), default=None)
    marker = db.relationship('FacultyData', foreign_keys=[marker_id], uselist=False,
                             backref=db.backref('marking_records', lazy='dynamic'))

    # link to ProjectClassConfig that selections were drawn from; used to offer a list of LiveProjects
    # if the convenor wishes to reassign
    selection_config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    selection_config = db.relationship('ProjectClassConfig', foreign_keys=[selection_config_id], uselist=None)

    # capture parent MatchingRecord, if one exists
    matching_record_id = db.Column(db.Integer(), db.ForeignKey('matching_records.id'), default=None)
    matching_record = db.relationship('MatchingRecord', foreign_keys=[matching_record_id], uselist=False,
                                      backref=db.backref('submission_record', uselist=False))


    # LIFECYCLE DATA

    # has the project started? Helpful for convenor and senior tutor reports
    student_engaged = db.Column(db.Boolean())


    # MARKER FEEDBACK TO STUDENT

    # supervisor positive feedback
    supervisor_positive = db.Column(db.Text())

    # supervisor negative feedback
    supervisor_negative = db.Column(db.Text())

    # supervisor submitted?
    supervisor_submitted = db.Column(db.Boolean())

    # supervisor submission datestamp
    supervisor_timestamp = db.Column(db.DateTime())

    # marker positive feedback
    marker_positive = db.Column(db.Text())

    # marker negative feedback
    marker_negative = db.Column(db.Text())

    # marker submitted?
    marker_submitted = db.Column(db.Boolean())

    # marker submission timestamp
    marker_timestamp = db.Column(db.DateTime())


    # STUDENT FEEDBACK

    # free-form feedback field
    student_feedback = db.Column(db.Text())

    # student feedback submitted
    student_feedback_submitted = db.Column(db.Boolean())

    # student feedback timestamp
    student_feedback_timestamp = db.Column(db.DateTime())

    # faculty acknowledge
    acknowledge_feedback = db.Column(db.Boolean())

    # faculty response
    faculty_response = db.Column(db.Text())

    # faculty response submitted
    faculty_response_submitted = db.Column(db.Boolean())

    # faculty response timestamp
    faculty_response_timestamp = db.Column(db.DateTime())


    @property
    def supervisor(self):
        """
        supervisor is just a pass-through to the assigned project owner
        :return:
        """
        return self.project.owner


    @property
    def period(self):
        """
        Returns SubmissionPeriodRecord for the submission period associated with this SubmissionRecord
        :return:
        """
        return self.owner.config.get_period(self.submission_period)


    @property
    def is_supervisor_valid(self):
        if self.supervisor_positive is None or len(self.supervisor_positive) == 0:
            return False

        if self.supervisor_negative is None or len(self.supervisor_negative) == 0:
            return False

        return True


    @property
    def is_marker_valid(self):
        if self.marker_positive is None or len(self.marker_positive) == 0:
            return False

        if self.marker_negative is None or len(self.marker_negative) == 0:
            return False

        return True


    @property
    def is_student_valid(self):
        if self.student_feedback is None or len(self.student_feedback) == 0:
            return False

        return True


    @property
    def is_response_valid(self):
        if self.faculty_response is None or len(self.faculty_response) == 0:
            return False

        return True


    @property
    def is_feedback_valid(self):
        return self.is_supervisor_valid or self.is_marker_valid


    FEEDBACK_NOT_YET = 0
    FEEDBACK_SUBMITTED = 1
    FEEDBACK_WAITING = 2
    FEEDBACK_ENTERED = 3
    FEEDBACK_LATE = 4


    def _feedback_state(self, valid):
        period = self.period

        if not period.feedback_open:
            return SubmissionRecord.FEEDBACK_NOT_YET

        if self.supervisor_submitted:
            return SubmissionRecord.FEEDBACK_SUBMITTED

        if valid:
            return SubmissionRecord.FEEDBACK_ENTERED

        if not period.closed:
            return SubmissionRecord.FEEDBACK_WAITING

        return SubmissionRecord.FEEDBACK_LATE


    @property
    def supervisor_feedback_state(self):
        return self._feedback_state(self.is_supervisor_valid)


    @property
    def marker_feedback_state(self):
        return self._feedback_state(self.is_marker_valid)


    @property
    def supervisor_response_state(self):
        period = self.period

        if not period.feedback_open or not self.student_feedback_submitted:
            return SubmissionRecord.FEEDBACK_NOT_YET

        if self.faculty_response_submitted:
            return SubmissionRecord.FEEDBACK_SUBMITTED

        if self.is_response_valid:
            return SubmissionRecord.FEEDBACK_ENTERED

        if not period.closed:
            return SubmissionRecord.FEEDBACK_WAITING

        return SubmissionRecord.FEEDBACK_LATE


    @property
    def has_feedback(self):
        return self.supervisor_submitted or self.marker_submitted


    @property
    def previous_config(self):
        if self.selection_config:
            return self.selection_config

        current_config = self.owner.config
        config = ProjectClassConfig.query.filter_by(year=current_config.year-1,
                                                    pclass_id=current_config.pclass_id).first()

        return config


    @property
    def pclass_id(self):
        return self.owner.config.pclass_id


    @property
    def pclass(self):
        return self.owner.config.project_class


    @property
    def supervising_CATS(self):
        config = self.previous_config

        if config is not None:
            return config.CATS_supervision

        return None


    @property
    def marking_CATS(self):
        config = self.previous_config

        if config is not None:
            return config.CATS_marking

        return None


class Bookmark(db.Model):
    """
    Model an (orderable) bookmark
    """

    __tablename__ = "bookmarks"


    # unique ID for this bookmark
    id = db.Column(db.Integer(), primary_key=True)

    # id of owning SelectingStudent
    # note we tag the backref with 'delete-orphan' to ensure that orphaned bookmark records are automatically
    # removed from the database
    owner_id = db.Column(db.Integer(), db.ForeignKey('selecting_students.id'))
    owner = db.relationship('SelectingStudent', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('bookmarks', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # LiveProject we are linking to
    liveproject_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    liveproject = db.relationship('LiveProject', foreign_keys=[liveproject_id], uselist=False,
                                  backref=db.backref('bookmarks', lazy='dynamic'))

    # rank in owner's list
    rank = db.Column(db.Integer())


    @property
    def format_project(self):
        return self.liveproject.name


    @property
    def format_name(self):
        return self.owner.student.user.name


class SelectionRecord(db.Model):
    """
    Model an ordered list of project selections
    """

    __tablename__ = "selections"


    # unique ID for this preference record
    id = db.Column(db.Integer(), primary_key=True)

    # id of owning SelectingStudent
    # note we tag the backref with 'delete-orphan' to ensure that orphaned bookmark records are automatically
    # removed from the database
    owner_id = db.Column(db.Integer(), db.ForeignKey('selecting_students.id'))
    owner = db.relationship('SelectingStudent', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('selections', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # LiveProject we are linking to
    liveproject_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    liveproject = db.relationship('LiveProject', foreign_keys=[liveproject_id], uselist=False,
                                  backref=db.backref('selections', lazy='dynamic'))

    # rank in owner's list
    rank = db.Column(db.Integer())

    # was this record converted from a bookmark when selections were closed?
    converted_from_bookmark = db.Column(db.Boolean())

    SELECTION_HINT_NEUTRAL = 0
    SELECTION_HINT_REQUIRE = 1
    SELECTION_HINT_FORBID = 2
    SELECTION_HINT_ENCOURAGE = 3
    SELECTION_HINT_DISCOURAGE = 4
    SELECTION_HINT_ENCOURAGE_STRONG = 5
    SELECTION_HINT_DISCOURAGE_STRONG = 6

    _icons = {SELECTION_HINT_NEUTRAL: '',
              SELECTION_HINT_REQUIRE: '<i class="fa fa-check"></i>',
              SELECTION_HINT_FORBID: '<i class="fa fa-times"></i>',
              SELECTION_HINT_ENCOURAGE: '<i class="fa fa-plus"></i>',
              SELECTION_HINT_DISCOURAGE: '<i class="fa fa-minus"></i>',
              SELECTION_HINT_ENCOURAGE_STRONG: '<i class="fa fa-plus"></i> <i class="fa fa-plus"></i>',
              SELECTION_HINT_DISCOURAGE_STRONG: '<i class="fa fa-minus"></i> <i class="fa fa-minus"></i>'}

    _menu_items = {SELECTION_HINT_NEUTRAL: 'Neutral',
                   SELECTION_HINT_REQUIRE: 'Require',
                   SELECTION_HINT_FORBID: 'Forbid',
                   SELECTION_HINT_ENCOURAGE: 'Encourage',
                   SELECTION_HINT_DISCOURAGE: 'Discourage',
                   SELECTION_HINT_ENCOURAGE_STRONG: 'Strongly encourage',
                   SELECTION_HINT_DISCOURAGE_STRONG: 'Strongly discourage'}

    _menu_order = [SELECTION_HINT_NEUTRAL,
                   "Force fit",
                   SELECTION_HINT_REQUIRE,
                   SELECTION_HINT_FORBID,
                   "Fitting hints",
                   SELECTION_HINT_ENCOURAGE,
                   SELECTION_HINT_DISCOURAGE,
                   SELECTION_HINT_ENCOURAGE_STRONG,
                   SELECTION_HINT_DISCOURAGE_STRONG]

    # convenor hint for this match
    hint = db.Column(db.Integer())


    @property
    def format_project(self):
        if self.hint in self._icons:
            tag = self._icons[self.hint]
        else:
            tag = ''

        if len(tag) > 0:
            tag += ' '

        return tag + self.liveproject.name


    @property
    def format_name(self):
        if self.hint in self._icons:
            tag = self._icons[self.hint]
        else:
            tag = ''

        if len(tag) > 0:
            tag += ' '

        return tag + self.owner.student.user.name


    @property
    def menu_order(self):
        return self._menu_order


    def menu_item(self, number):
        if number in self._menu_items:
            if number in self._icons:
                tag = self._icons[number]

            value = self._menu_items[number]
            if len(tag) > 0:
                value = tag + ' ' + value

            return value

        return None


    def set_hint(self, hint):
        if hint < SelectionRecord.SELECTION_HINT_NEUTRAL or hint > SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG:
            return

        if self.hint == hint:
            return

        if hint == SelectionRecord.SELECTION_HINT_REQUIRE:

            # count number of other 'require' flags attached to this selector
            count = 0
            for item in self.owner.selections:
                if item.id != self.id and item.hint == SelectionRecord.SELECTION_HINT_REQUIRE:
                    count += 1

            # if too many, remove one
            target = self.owner.config.submissions
            if count >= target:
                for item in self.owner.selections:
                    if item.id != self.id and item.hint == SelectionRecord.SELECTION_HINT_REQUIRE:
                        item.hint = SelectionRecord.SELECTION_HINT_NEUTRAL
                        count -= 1

                        if count < target:
                            break

        # note database has to be committed separately
        self.hint = hint


@listens_for(SelectionRecord, 'before_update')
def _SelectionRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score)
        cache.delete_memoized(_MatchingAttempt_hint_status)


@listens_for(SelectionRecord, 'before_insert')
def _SelectionRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score)
        cache.delete_memoized(_MatchingAttempt_hint_status)


@listens_for(SelectionRecord, 'before_delete')
def _SelectionRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score)
        cache.delete_memoized(_MatchingAttempt_hint_status)


class EmailLog(db.Model):
    """
    Model a logged email
    """

    __tablename__ = "email_log"


    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # id of user to whom email was sent, if it could be determined
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'), nullable=True)
    user = db.relationship('User', uselist=False, backref=db.backref('emails', lazy='dynamic'))

    # recipient as a string, used if user_id could not be determined
    recipient = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), nullable=True)

    # date of sending attempt
    send_date = db.Column(db.DateTime(), index=True)

    # subject
    subject = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # message body (text)
    body = db.Column(db.Text())

    # message body (HTML)
    html = db.Column(db.Text())


class MessageOfTheDay(db.Model):
    """
    Model a message broadcast to all users, or a specific subset of users
    """

    __tablename__ = "messages"


    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # id of issuing user
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    user = db.relationship('User', uselist=False,
                           backref=db.backref('messages', lazy='dynamic'))

    # date of issue
    issue_date = db.Column(db.DateTime(), index=True)

    # show to students?
    show_students = db.Column(db.Boolean())

    # show to faculty?
    show_faculty = db.Column(db.Boolean())

    # display on login screen?
    show_login = db.Column(db.Boolean())

    # is this message dismissible?
    dismissible = db.Column(db.Boolean())

    # title
    title = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # message text
    body = db.Column(db.Text())

    # associate with which projects?
    project_classes = db.relationship('ProjectClass', secondary=pclass_message_associations, lazy='dynamic',
                                      backref=db.backref('messages', lazy='dynamic'))

    # which users have dismissed this message already?
    dismissed_by = db.relationship('User', secondary=message_dismissals, lazy='dynamic')


class BackupConfiguration(db.Model):
    """
    Set details of the current backup configuration
    """

    __tablename__ = 'backup_config'

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # how many days to keep hourly backups for
    keep_hourly = db.Column(db.Integer())

    # how many weeks to keep daily backups for
    keep_daily = db.Column(db.Integer())

    # backup limit
    limit = db.Column(db.Integer())

    # backup units
    KEY_MB = 1
    _UNIT_MB = 1024 * 1024

    KEY_GB = 2
    _UNIT_GB = _UNIT_MB * 1024

    KEY_TB = 3
    _UNIT_TB = _UNIT_GB * 1024

    unit_map = {KEY_MB: _UNIT_MB, KEY_GB: _UNIT_GB, KEY_TB: _UNIT_TB}
    units = db.Column(db.Integer(), nullable=False, default=1)

    # last changed
    last_changed = db.Column(db.DateTime())


    @property
    def backup_max(self):

        if self.limit is None or self.limit == 0:
            return None

        return self.limit * self.unit_map[self.units]


class BackupRecord(db.Model):
    """
    Keep details of a website backup
    """

    __tablename__ = "backups"


    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # ID of owner, the user who initiated this backup
    owner_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    owner = db.relationship('User', backref=db.backref('backups', lazy='dynamic'))

    # optional text description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # date of backup
    date = db.Column(db.DateTime(), index=True)

    # type of backup
    SCHEDULED_BACKUP = 1
    PROJECT_ROLLOVER_FALLBACK = 2
    PROJECT_GOLIVE_FALLBACK = 3
    PROJECT_CLOSE_FALLBACK = 4

    _type_index = {SCHEDULED_BACKUP: 'Scheduled backup',
                   PROJECT_ROLLOVER_FALLBACK: 'Rollover restore point',
                   PROJECT_GOLIVE_FALLBACK: 'Go Live restore point',
                   PROJECT_CLOSE_FALLBACK: 'Close selection restore point'}

    type = db.Column(db.Integer())

    # filename
    filename = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # uncompressed database size, in bytes
    db_size = db.Column(db.Integer())

    # compressed archive size, in bytes
    archive_size = db.Column(db.Integer())

    # total size of backups at this time, in bytes
    backup_size = db.Column(db.Integer())



    def type_to_string(self):
        if self.type in self._type_index:
            return self._type_index[self.type]

        return '<Unknown>'


    @property
    def print_filename(self):
        return path.join("...", path.basename(self.filename))


    @property
    def readable_db_size(self):
        return format_size(self.db_size) if self.db_size is not None else "<unset>"


    @property
    def readable_archive_size(self):
        return format_size(self.archive_size) if self.archive_size is not None else "<unset>"


    @property
    def readable_total_backup_size(self):
        return format_size(self.backup_size) if self.backup_size is not None else "<unset>"


class TaskRecord(db.Model):

    __tablename__ = 'tasks'


    # unique identifier used by task queue
    id = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), primary_key=True)

    # task owner
    owner_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    owner = db.relationship('User', uselist=False, backref=db.backref('tasks', lazy='dynamic'))

    # task launch date
    start_date = db.Column(db.DateTime())

    # task name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)

    # optional task description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # status flag
    PENDING = 0
    RUNNING = 1
    SUCCESS = 2
    FAILURE = 3
    TERMINATED = 4
    STATES = { PENDING: 'PENDING',
               RUNNING: 'RUNNING',
               SUCCESS: 'SUCCESS',
               FAILURE: 'FAILURE',
               TERMINATED: 'TERMINATED'}
    status = db.Column(db.Integer())

    # percentage complete (if used)
    progress = db.Column(db.Integer())

    # progress message
    message = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))


class Notification(db.Model):

    __tablename__ = 'notifications'


    # unique id for this notificatgion
    id = db.Column(db.Integer(), primary_key=True)

    TASK_PROGRESS = 1
    USER_MESSAGE = 2
    SHOW_HIDE_REQUEST = 100
    REPLACE_TEXT_REQUEST = 101
    type = db.Column(db.Integer())

    # notifications are identified by the user they are intended for, plus a tag identifying
    # the source of the notification (eg. a task UUID)
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    user = db.relationship('User', uselist=False, backref=db.backref('notifications', lazy='dynamic'))

    # uuid identifies a set of notifications (eg. task progress updates for the same task, or messages for the same subject)
    uuid = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)

    # timestamp
    timestamp = db.Column(db.Integer(), index=True, default=time)

    # should this notification be removed on the next page request?
    remove_on_pageload = db.Column(db.Boolean())

    # payload as a JSON-serialized string
    payload_json = db.Column(db.Text())


    @property
    def payload(self):
        return json.loads(str(self.payload_json))


    @payload.setter
    def payload(self, obj):
        self.payload_json = json.dumps(obj)


class PopularityRecord(db.Model):

    __tablename = 'popularity'


    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # tag LiveProject to which this record applies
    liveproject_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    liveproject = db.relationship('LiveProject', uselist=False,
                                  backref=db.backref('popularity_data', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # tag ProjectClassConfig to which this record applies
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', uselist=False,
                             backref=db.backref('popularity_data', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # date stamp for this calculation
    datestamp = db.Column(db.DateTime(), index=True)

    # UUID identifying all popularity records in a group
    uuid = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), index=True)


    # COMMON DATA

    # total number of LiveProjects included in ranking
    total_number = db.Column(db.Integer())


    # POPULARITY SCORE

    # popularity score
    score = db.Column(db.Integer())

    # rank on popularity score
    score_rank = db.Column(db.Integer())

    # track lowest rank so we have an estimate of whether the popularity score is meaningful
    lowest_score_rank = db.Column(db.Integer())


    # PAGE VIEWS

    # page views
    views = db.Column(db.Integer())

    # rank on page views
    views_rank = db.Column(db.Integer())


    # BOOKMARKS

    # number of bookmarks
    bookmarks = db.Column(db.Integer())

    # rank on bookmarks
    bookmarks_rank = db.Column(db.Integer())


    # SELECTIONS

    # number of selections
    selections = db.Column(db.Integer())

    # rank of number of selections
    selections_rank = db.Column(db.Integer())


class FilterRecord(db.Model):

    __tablename__ = 'filters'


    # unique ID for this record
    id = db.Column(db.Integer(), primary_key=True)

    # tag with user_id to whom these filters are attached
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    user = db.relationship(User, foreign_keys=[user_id], uselist=False)

    # tag with ProjectClassConfig to which these filters are attached
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', foreign_keys=[config_id], uselist=False,
                             backref=db.backref('filters', lazy='dynamic'))

    # active research group filters
    group_filters = db.relationship('ResearchGroup', secondary=convenor_group_filter_table, lazy='dynamic')

    # active transferable skill group filters
    skill_filters = db.relationship('SkillGroup', secondary=convenor_skill_filter_table, lazy='dynamic')


@cache.memoize()
def _MatchingAttempt_current_score(id):
    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    if obj.levelling_bias is None or obj.mean_CATS_per_project is None or obj.intra_group_tension is None:
        return None
    
    # build objective function: this is the reward function that measures how well the student
    # allocations match their preferences; corresponds to
    #   objective += X[idx] * W[idx] / R[idx]
    # in app/tasks/matching.py
    scores = [x.current_score for x in obj.records]
    if None in scores:
        scores = [x for x in scores if x is not None]
    
    objective = sum(scores)
    
    # break up subscribed faculty in a list of markers only, supervisors only, and markers and supervisors
    mark_only, sup_and_mark, sup_only = obj._faculty_groups
    
    sup_CATS = obj._get_group_CATS(sup_only)
    mark_CATS = obj._get_group_CATS(mark_only)
    sup_mark_CATS = obj._get_group_CATS(sup_and_mark)
    
    globalMin = None
    globalMax = None
    
    # compute max(CATS) - min(CATS) values for each group, and also the global max and min cats
    sup_diff, globalMax, globalMin = obj._compute_group_max_min(sup_CATS, globalMax, globalMin)
    mark_diff, globalMax, globalMin = obj._compute_group_max_min(mark_CATS, globalMax, globalMin)
    sup_mark_diff, globalMax, globalMin = obj._compute_group_max_min(sup_mark_CATS, globalMax, globalMin)
    
    # finally compute the largest number of projects that anyone is scheduled to 2nd mark
    maxMarking = obj._max_marking_allocation
    
    global_diff = 0
    if globalMax is not None and globalMin is not None:
        global_diff = globalMax - globalMin
    
    levelling = sup_diff + mark_diff + sup_mark_diff + abs(float(obj.intra_group_tension)) * global_diff
    
    return objective \
           - abs(float(obj.levelling_bias)) * levelling / float(obj.mean_CATS_per_project) \
           - abs(float(obj.levelling_bias)) * maxMarking


@cache.memoize()
def _MatchingAttempt_get_faculty_CATS(id, fac_id, pclass_id):
    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    CATS_supervisor = 0
    CATS_marker = 0

    for item in obj.get_supervisor_records(fac_id).all():
        config = item.project.config

        if pclass_id is None or config.pclass_id == pclass_id:
            if config.CATS_supervision is not None and config.CATS_supervision > 0:
                CATS_supervisor += config.CATS_supervision

    for item in obj.get_marker_records(fac_id).all():
        config = item.project.config

        if pclass_id is None or config.pclass_id == pclass_id:
            if config.uses_marker:
                if config.CATS_marking is not None and config.CATS_marking > 0:
                    CATS_marker += config.CATS_marking

    return CATS_supervisor, CATS_marker


@cache.memoize()
def _MatchingAttempt_prefer_programme_status(id):
    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    if obj.ignore_programme_prefs:
        return None

    matched = 0
    failed = 0

    for rec in obj.records:
        outcome = rec.project.satisfies_preferences(rec.selector)

        if outcome is None:
            break

        if outcome:
            matched += 1
        else:
            failed += 1

    return matched, failed


@cache.memoize()
def _MatchingAttempt_hint_status(id):
    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    if not obj.use_hints:
        return None

    satisfied = set()
    violated = set()

    for rec in obj.records:

        s, v = rec.hint_status

        satisfied = satisfied | s
        violated = violated | v

    return len(satisfied), len(violated)


@cache.memoize()
def _MatchingAttempt_number_project_assignments(id, project_id):
    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    return get_count(obj.records.filter_by(project_id=project_id))


@cache.memoize()
def _MatchingAttempt_is_valid(id):
    obj = db.session.query(MatchingAttempt).filter_by(id=id).one()

    # there are several steps:
    #   1. Validate that each MatchingRecord is valid (2nd marker is not supervisor,
    #      LiveProject is attached to right class).
    #      These errors are fatal
    #   2. Validate that project capacity constraints are not violated.
    #      This is also a fatal error.
    #   3. Validate that faculty CATS limits are respected.
    #      This is a warning, not an error

    errors = {}
    warnings = {}
    student_issues = False
    faculty_issues = False

    for record in obj.records:
        if not record.is_valid:
            errors[('basic', record.id)] \
                = '{name}/{abbv}: {err}'.format(err=record.error,
                                                name=record.selector.student.user.name,
                                                abbv=record.selector.config.project_class.abbreviation)
            student_issues = True

    for project in obj.projects:
        if obj.is_project_overassigned(project):
            errors[('capacity', project.id)] = \
                'Project {name} ({supv}) is over-assigned ' \
                '(assigned={m}, max capacity={n})'.format(supv=project.owner.user.name, name=project.name,
                                                          m=obj.number_project_assignments(project),
                                                          n=project.capacity)
            student_issues = True
            faculty_issues = True

    for fac in obj.faculty:
        sup_over, CATS_sup, sup_lim = obj.is_supervisor_overassigned(fac)
        if sup_over:
            warnings[('supervising', fac.id)] = \
                'Supervising workload for {name} exceeds CATS limit ' \
                '(assigned={m}, max capacity={n})'.format(name=fac.user.name, m=CATS_sup, n=sup_lim)
            faculty_issues = True

        mark_over, CATS_mark, mark_lim = obj.is_marker_overassigned(fac)
        if mark_over:
            warnings[('marking', fac.id)] = \
                'Marking workload for {name} exceeds CATS limit ' \
                '(assigned={m}, max capacity={n})'.format(name=fac.user.name, m=CATS_mark, n=mark_lim)
            faculty_issues = True

    if len(errors) > 0 or len(warnings) > 0:
        return False, student_issues, faculty_issues, errors, warnings
    
    return True, student_issues, faculty_issues, errors, warnings


class PuLPMixin():
    # METADATA

    # outcome report from PuLP
    OUTCOME_OPTIMAL = 0
    OUTCOME_NOT_SOLVED = 1
    OUTCOME_INFEASIBLE = 2
    OUTCOME_UNBOUNDED = 3
    OUTCOME_UNDEFINED = 4

    # outcome of calculation
    outcome = db.Column(db.Integer())

    SOLVER_CBC_PACKAGED = 0
    SOLVER_CBC_CMD = 1
    SOLVER_GLPK_CMD = 2

    # which solver to use
    solver = db.Column(db.Integer())

    # time taken to construct the PuLP problem
    construct_time = db.Column(db.Numeric(8, 3))

    # time taken by PulP to compute the solution
    compute_time = db.Column(db.Numeric(8, 3))


    # MATCHING OUTCOME

    # value of objective function, if match was successful
    score = db.Column(db.Numeric(10, 2))


    _solvers = {0: 'PuLP-CBC', 1: 'CBC-CMD', 2: 'GLPK-CMD'}

    @property
    def solver_name(self):
        if self.solver in self._solvers:
            return self._solvers[self.solver]

        return None


    @property
    def formatted_construct_time(self):
        return format_time(self.construct_time)


    @property
    def formatted_compute_time(self):
        return format_time(self.compute_time)


class MatchingAttempt(db.Model, PuLPMixin):
    """
    Model configuration data for a matching attempt
    """

    # make table name plural
    __tablename__ = 'matching_attempts'

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # year should match an available year in MainConfig
    year = db.Column(db.Integer(), db.ForeignKey('main_config.year'))
    main_config = db.relationship('MainConfig', foreign_keys=[year], uselist=False,
                                  backref=db.backref('matching_attempts', lazy='dynamic'))

    # a name for this matching attempt
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True)

    # flag matching attempts that have been selected for use during rollover
    selected = db.Column(db.Boolean())


    # PARTICIPATING PCLASSES

    # pclasses that are part of this match
    config_members = db.relationship('ProjectClassConfig', secondary=match_configs, lazy='dynamic',
                                     backref=db.backref('matching_attempts', lazy='dynamic'))

    # flag whether this attempt has been published to convenors for comments/editing
    published = db.Column(db.Boolean())


    # CELERY TASK DATA

    # Celery taskid, used in case we need to revoke the task;
    # typically this will be a UUID
    celery_id = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # finished executing?
    finished = db.Column(db.Boolean())


    # MATCHING OPTIONS

    # ignore CATS limits specified in faculty accounts?
    ignore_per_faculty_limits = db.Column(db.Boolean())

    # ignore degree programme preferences specified in project descriptions?
    ignore_programme_prefs = db.Column(db.Boolean())

    # how many years memory to include when levelling CATS scores
    years_memory = db.Column(db.Integer())

    # global supervising CATS limit
    supervising_limit = db.Column(db.Integer())

    # global 2nd-marking CATS limit
    marking_limit = db.Column(db.Integer())

    # maximum multiplicity for 2nd markers
    max_marking_multiplicity = db.Column(db.Integer())


    # CONVENOR HINTS

    # enable/disable convenor hints
    use_hints = db.Column(db.Boolean())

    # bias for 'encourage'
    encourage_bias = db.Column(db.Numeric(8, 3))

    # bias for 'discourage'
    discourage_bias = db.Column(db.Numeric(8, 3))

    # bias for 'strong encourage'
    strong_encourage_bias = db.Column(db.Numeric(8, 3))

    # bias for 'strong discourage'
    strong_discourage_bias = db.Column(db.Numeric(8, 3))

    # bookmark bias - penalty for using bookmarks rather than a real submission
    bookmark_bias = db.Column(db.Numeric(8, 3))


    # WORKLOAD LEVELLING

    # workload levelling bias
    # (this is the prefactor we use to set the normalization of the tension term in the objective function.
    # the tension term represents the difference in CATS between the upper and lower workload in each group,
    # plus another term (the 'intra group tension') that tensions all groups together. 'Group' here means
    # faculty that supervise only, mark only, or supervise and mark. Each group will typically have a different
    # median workload.)
    levelling_bias = db.Column(db.Numeric(8, 3))

    # intra-group tensioning
    intra_group_tension = db.Column(db.Numeric(8, 3))

    # programme matching bias
    programme_bias = db.Column(db.Numeric(8, 3))

    # other MatchingAttempts to include in CATS calculations
    include_matches = db.relationship('MatchingAttempt', secondary=match_balancing,
                                      primaryjoin=match_balancing.c.child_id==id,
                                      secondaryjoin=match_balancing.c.parent_id==id,
                                      backref='balanced_with')


    # CONFIGURATION

    # record participants in this matching attempt
    # note, there is no need to track the selectors since they are in 1-to-1 correspondance with the attached
    # MatchingRecords, available under the backref .records

    # participating supervisors
    supervisors = db.relationship('FacultyData', secondary=supervisors_matching_table,
                                  backref=db.backref('supervisor_matching_attempts', lazy='dynamic'))

    # participating markers
    markers = db.relationship('FacultyData', secondary=marker_matching_table,
                              backref=db.backref('marker_matching_attempts', lazy='dynamic'))

    # participating projects
    projects = db.relationship('LiveProject', secondary=project_matching_table,
                               backref=db.backref('project_matching_attempts', lazy='dynamic'))

    # mean CATS per project during matching
    mean_CATS_per_project = db.Column(db.Numeric(8, 5))


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False,
                                 backref=db.backref('matching_attempts', lazy='dynamic'))

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selector_list = None
        self._faculty_list = None
        self._CATS_list = None

        self._validated = False
        self._student_issues = False
        self._faculty_issues = False
        self._errors = {}
        self._warnings = {}


    @orm.reconstructor
    def _reconstruct(self):
        self._selector_list = None
        self._faculty_list = None
        self._CATS_list = None

        self._validated = False
        self._student_issues = False
        self._faculty_issues = False
        self._errors = {}
        self._warnings = {}


    def _build_selector_list(self):
        if self._selector_list is not None:
            return

        self._selector_list = {}

        for item in self.records.order_by(MatchingRecord.submission_period.asc()).all():

            # if we haven't seen this selector ID before, start a new list containing this record.
            # Otherwise, attach current record to the end of the existing list.
            if item.selector_id not in self._selector_list:
                self._selector_list[item.selector_id] = [item]
            else:
                self._selector_list[item.selector_id].append(item)


    def _build_faculty_list(self):
        if self._faculty_list is not None:
            return

        self._faculty_list = {}

        for item in self.supervisors:
            if item.id not in self._faculty_list:
                self._faculty_list[item.id] = item

        for item in self.markers:
            if item.id not in self._faculty_list:
                self._faculty_list[item.id] = item


    def get_faculty_CATS(self, fac_id, pclass_id=None):
        """
        Compute faculty workload in CATS, optionally for a specific pclass
        :param fac: FacultyData instance
        :return:
        """
        return _MatchingAttempt_get_faculty_CATS(self.id, fac_id, pclass_id)


    def _build_CATS_list(self):
        if self._CATS_list is not None:
            return

        fsum = lambda x: x[0] + x[1]

        self._build_faculty_list()
        self._CATS_list = [fsum(self.get_faculty_CATS(fac.id)) for fac in self.faculty]


    @property
    def selectors(self):
        self._build_selector_list()
        return self._selector_list.values()


    @property
    def faculty(self):
        self._build_faculty_list()
        return self._faculty_list.values()


    @property
    def selector_deltas(self):
        self._build_selector_list()

        d = lambda recs: [y.delta for y in recs]
        delta_set = [d(x) for x in self.selectors]

        fsum = lambda deltas: sum(deltas) if None not in deltas else None
        sum_delta_set = [fsum(d) for d in delta_set]

        return sum_delta_set


    @property
    def faculty_CATS(self):
        self._build_CATS_list()
        return self._CATS_list


    @property
    def delta_max(self):
        filtered_deltas = [x for x in self.selector_deltas if x is not None]
        return max(filtered_deltas)


    @property
    def delta_min(self):
        filtered_deltas = [x for x in self.selector_deltas if x is not None]
        return min(filtered_deltas)


    @property
    def CATS_max(self):
        return max(self.faculty_CATS)


    @property
    def CATS_min(self):
        return min(self.faculty_CATS)


    def get_supervisor_records(self, fac_id):
        return self.records \
            .join(LiveProject, LiveProject.id == MatchingRecord.project_id) \
            .filter(LiveProject.owner_id == fac_id) \
            .order_by(MatchingRecord.submission_period.asc())


    def get_marker_records(self, fac_id):
        return self.records \
            .filter_by(marker_id=fac_id) \
            .order_by(MatchingRecord.submission_period.asc())


    def number_project_assignments(self, project):
        return _MatchingAttempt_number_project_assignments(self.id, project.id)


    def is_project_overassigned(self, project):
        count = self.number_project_assignments(project)
        if project.enforce_capacity and project.capacity is not None and 0 < project.capacity < count:
            return True

        return False


    def is_supervisor_overassigned(self, faculty):
        CATS_sup, CATS_mark = self.get_faculty_CATS(faculty.id)

        sup_lim = self.supervising_limit

        if not self.ignore_per_faculty_limits:
            if faculty.CATS_supervision is not None and faculty.CATS_supervision > 0:
                sup_lim = faculty.CATS_supervision

        if CATS_sup > sup_lim:
            return True, CATS_sup, sup_lim

        return False, CATS_sup, sup_lim


    def is_marker_overassigned(self, faculty):
        CATS_sup, CATS_mark = self.get_faculty_CATS(faculty.id)

        mark_lim = self.marking_limit

        if not self.ignore_per_faculty_limits:
            if faculty.CATS_marking is not None and faculty.CATS_marking > 0:
                mark_lim = faculty.CATS_marking

        if CATS_mark > mark_lim:
            return True, CATS_mark, mark_lim

        return False, CATS_mark, mark_lim


    @property
    def is_valid(self):
        """
        Perform validation
        :return:
        """
        flag, self._student_issues, self._faculty_issues, self._errors, self._warnings = _MatchingAttempt_is_valid(self.id)
        self._validated = True
        
        return flag


    @property
    def errors(self):
        if not self._validated:
            check = self.is_valid
        return self._errors.values()


    @property
    def warnings(self):
        if not self._validated:
            check = self.is_valid
        return self._warnings.values()


    @property
    def faculty_issues(self):
        if not self._validated:
            check = self.is_valid
        return self._faculty_issues


    @property
    def student_issues(self):
        if not self._validated:
            check = self.is_valid
        return self._student_issues


    @property
    def current_score(self):
        return _MatchingAttempt_current_score(self.id)


    def _compute_group_max_min(self, CATS_list, globalMax, globalMin):
        if len(CATS_list) == 0:
            return 0, globalMax, globalMin

        largest = max(CATS_list)
        smallest = min(CATS_list)

        if globalMax is None or largest > globalMax:
            globalMax = largest

        if globalMin is None or smallest < globalMin:
            globalMin = smallest

        return largest - smallest, globalMax, globalMin


    @property
    def _faculty_groups(self):
        sup_dict = {x.id: x for x in self.supervisors}
        mark_dict = {x.id: x for x in self.markers}

        supervisor_ids = sup_dict.keys()
        marker_ids = mark_dict.keys()

        # these are set difference and set intersection operators
        sup_only_ids = supervisor_ids - marker_ids
        mark_only_ids = marker_ids - supervisor_ids
        sup_and_mark_ids = supervisor_ids & marker_ids

        sup_only = [sup_dict[i] for i in sup_only_ids]
        mark_only = [mark_dict[i] for i in mark_only_ids]
        sup_and_mark = [sup_dict[i] for i in sup_and_mark_ids]

        return mark_only, sup_and_mark, sup_only


    def _get_group_CATS(self, group):
        fsum = lambda x: x[0] + x[1]

        return [fsum(self.get_faculty_CATS(x.id)) for x in group]


    @property
    def _max_marking_allocation(self):
        allocs = [len(self.get_marker_records(fac.id).all()) for fac in self.markers]
        return max(allocs)


    @property
    def prefer_programme_status(self):
        return _MatchingAttempt_prefer_programme_status(self.id)
    
    
    @property
    def hint_status(self):
        return _MatchingAttempt_hint_status(self.id)


    @property
    def available_pclasses(self):
        configs = self.config_members.subquery()
        pclass_ids = db.session.query(configs.c.pclass_id).distinct().subquery()

        return db.session.query(ProjectClass) \
            .join(pclass_ids, ProjectClass.id == pclass_ids.c.pclass_id).all()


    @property
    def is_modified(self):
        return self.last_edit_timestamp is not None


@listens_for(MatchingAttempt, 'before_update')
def _MatchingAttempt_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score, target.id)
        cache.delete_memoized(_MatchingAttempt_prefer_programme_status, target.id)
        cache.delete_memoized(_MatchingAttempt_is_valid, target.id)
        cache.delete_memoized(_MatchingAttempt_hint_status, target.id)

        cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
        cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@listens_for(MatchingAttempt, 'before_insert')
def _MatchingAttempt_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score, target.id)
        cache.delete_memoized(_MatchingAttempt_prefer_programme_status, target.id)
        cache.delete_memoized(_MatchingAttempt_is_valid, target.id)
        cache.delete_memoized(_MatchingAttempt_hint_status, target.id)

        cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
        cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@listens_for(MatchingAttempt, 'before_delete')
def _MatchingAttempt_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingAttempt_current_score, target.id)
        cache.delete_memoized(_MatchingAttempt_prefer_programme_status, target.id)
        cache.delete_memoized(_MatchingAttempt_is_valid, target.id)
        cache.delete_memoized(_MatchingAttempt_hint_status, target.id)

        cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
        cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@cache.memoize()
def _MatchingRecord_current_score(id):
    obj = db.session.query(MatchingRecord).filter_by(id=id).one()

    # return None is SelectingStudent record is missing
    if obj.selector is None:
        return None

    # return None if SelectingStudent has no submission records.
    # This happens if they didn't submit a choices list and have no bookmarks.
    # In this case we had to set thank rank matrix to 1 for all suitable projects, in order that
    # an allocation could be made (because of the constraint that allocation <= rank).
    # Also weight is 1 so we always score 1
    if not obj.selector.has_submitted:
        return 1.0

    # find selection record corresponding to our project
    record = obj.selector.selections.filter_by(liveproject_id=obj.project_id).first()

    # if there isn't one, presumably a convenor has reallocated us to a project for which
    # we score 0
    if record is None:
        return 0.0

    # if hint is forbid, we contribute nothing
    if record.hint == SelectionRecord.SELECTION_HINT_FORBID:
        return 0.0

    # score is 1/rank of assigned project, weighted
    weight = 1.0

    # downweight by penalty factor if selection record was converted from a bookmark
    if record.converted_from_bookmark:
        weight *= float(obj.matching_attempt.bookmark_bias)

    # upweight by encourage/discourage bias terms, if needed
    if obj.matching_attempt.use_hints:
        if record.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE:
            weight *= float(obj.matching_attempt.encourage_bias)
        elif record.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE:
            weight *= float(obj.matching_attempt.discourage_bias)
        elif record.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE_STRONG:
            weight *= float(obj.matching_attempt.strong_encourage_bias)
        elif record.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG:
            weight *= float(obj.matching_attempt.strong_discourage_bias)

    # upweight by programme bias, if this is not disabled
    if not obj.matching_attempt.ignore_programme_prefs:
        if obj.project.satisfies_preferences(obj.selector):
            weight *= float(obj.matching_attempt.programme_bias)

    return weight / float(record.rank)


@cache.memoize()
def _MatchingRecord_is_valid(id):
    obj = db.session.query(MatchingRecord).filter_by(id=id).one()

    if obj.supervisor_id == obj.marker_id:
        return False, 'Supervisor and marker are the same'

    if (obj.selector.has_submitted or obj.selector.has_bookmarks) \
            and obj.selector.project_rank(obj.project_id) is None:
        return False, "Assigned project does not appear in this selector's choices"

    if obj.project.config_id != obj.selector.config_id:
        return False, 'Assigned project does not belong to the correct class for this selector'

    # check whether this project is also assigned to the same selector in another submission period
    count = get_count(obj.matching_attempt.records.filter_by(selector_id=obj.selector_id,
                                                             project_id=obj.project_id))

    if count != 1:
        # only refuse to validate if we are the first member of the multiplet;
        # this prevents errors being reported multiple times
        lo_rec = obj.matching_attempt.records \
            .filter_by(selector_id=obj.selector_id, project_id=obj.project_id) \
            .order_by(MatchingRecord.submission_period.asc()).first()

        if lo_rec is not None and lo_rec.submission_period == obj.submission_period:
            return False, 'Project "{name}" is duplicated in multiple submission periods'.format(name=obj.project.name)

    # check whether the assigned marker is compatible with this project
    count = get_count(obj.project.assessor_list_query.filter_by(id=obj.marker_id))

    if count != 1:
        return False, 'Assigned 2nd marker is not compatible with assigned project'

    return True, None


class MatchingRecord(db.Model):
    """
    Store matching data for an individual selector
    """

    __tablename__ = 'matching_records'


    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # owning MatchingAttempt
    matching_id = db.Column(db.Integer(), db.ForeignKey('matching_attempts.id'))
    matching_attempt = db.relationship('MatchingAttempt', foreign_keys=[matching_id], uselist=False,
                                       backref=db.backref('records', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # owning SelectingStudent
    selector_id = db.Column(db.Integer(), db.ForeignKey('selecting_students.id'))
    selector = db.relationship('SelectingStudent', foreign_keys=[selector_id], uselist=False)

    # submission period
    submission_period = db.Column(db.Integer())

    # assigned project
    project_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    project = db.relationship('LiveProject', foreign_keys=[project_id], uselist=False)

    # keep copy of original project assignment, can use later to revert
    original_project_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))

    # rank of this project in the student's selection
    rank = db.Column(db.Integer())

    # assigned second marker, or none if second markers are not used
    marker_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'))
    marker = db.relationship('FacultyData', foreign_keys=[marker_id], uselist=False)

    # keep copy of original marker assignment, can use later to revert
    original_marker_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'))


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error = None


    @orm.reconstructor
    def _reconstruct(self):
        self.error = None


    @property
    def supervisor(self):
        """
        supervisor is just a pass-through to the assigned project owner
        :return:
        """
        if self.project:
            return self.project.owner
        return None


    @property
    def supervisor_id(self):
        """
        supervisor_id is just a pass-through to the assigned project owner

        :return:
        """
        if self.project:
            return self.project.owner_id
        return None


    @property
    def is_valid(self):
        flag, self.error = _MatchingRecord_is_valid(self.id)

        return flag


    @property
    def is_project_overassigned(self):
        if self.matching_attempt.is_project_overassigned(self.project):
            self.error = 'Project "{supv} - {name}" is over-assigned ' \
                         '(assigned={m}, max capacity={n})'.format(supv=self.project.owner.user.name, name=self.project.name,
                                                                   m=self.matching_attempt.number_project_assignments(self.project),
                                                                   n=self.project.capacity)
            return True

        return False


    @property
    def delta(self):
        if self.rank is None:
            return None
        return self.rank-1


    @property
    def hi_ranked(self):
        return self.rank == 1 or self.rank == 2


    @property
    def lo_ranked(self):
        choices = self.selector.config.project_class.initial_choices
        return self.rank == choices or self.rank == choices-1


    @property
    def current_score(self):
        return _MatchingRecord_current_score(self.id)


    @property
    def hint_status(self):
        if self.selector is None or self.selector.selections is None:
            return None

        satisfied = set()
        violated = set()

        for item in self.selector.selections:
            if item.hint == SelectionRecord.SELECTION_HINT_FORBID or \
                    item.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE or \
                    item.hint == SelectionRecord.SELECTION_HINT_DISCOURAGE_STRONG:

                if self.project_id == item.liveproject_id:
                    violated.add(item.id)
                else:
                    satisfied.add(item.id)

            if item.hint == SelectionRecord.SELECTION_HINT_REQUIRE or \
                    item.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE or \
                    item.hint == SelectionRecord.SELECTION_HINT_ENCOURAGE_STRONG:

                if self.project_id != item.liveproject_id:

                    # check whether any other MatchingRecord for the same selector but a different
                    # submission period satisfies the match
                    check = db.session.query(MatchingRecord).filter_by(matching_id=self.matching_id,
                                                                       selector_id=self.selector_id,
                                                                       project_id=item.liveproject_id).first()

                    if check is None:
                        violated.add(item.id)

                else:
                    satisfied.add(item.id)

        return satisfied, violated


@listens_for(MatchingRecord, 'before_update')
def _MatchingRecord_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingRecord_current_score, target.id)
        cache.delete_memoized(_MatchingRecord_is_valid, target.id)

        cache.delete_memoized(_MatchingAttempt_current_score, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_prefer_programme_status, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_is_valid, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_hint_status, target.matching_id)

        cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
        cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@listens_for(MatchingRecord, 'before_insert')
def _MatchingRecord_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingRecord_current_score, target.id)
        cache.delete_memoized(_MatchingRecord_is_valid, target.id)

        cache.delete_memoized(_MatchingAttempt_current_score, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_prefer_programme_status, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_is_valid, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_hint_status, target.matching_id)

        cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
        cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@listens_for(MatchingRecord, 'before_delete')
def _MatchingRecord_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_MatchingRecord_current_score, target.id)
        cache.delete_memoized(_MatchingRecord_is_valid, target.id)

        cache.delete_memoized(_MatchingAttempt_current_score, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_prefer_programme_status, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_is_valid, target.matching_id)
        cache.delete_memoized(_MatchingAttempt_hint_status, target.matching_id)

        cache.delete_memoized(_MatchingAttempt_get_faculty_CATS)
        cache.delete_memoized(_MatchingAttempt_number_project_assignments)


@cache.memoize()
def _PresentationAssessment_is_valid(id):
    obj = db.session.query(PresentationAssessment).filter_by(id=id).one()

    errors = {}
    warnings = {}

    # CONSTRAINT 1 - sessions should satisfy their own consistency rules
    for sess in obj.sessions:
        # check whether each session validates individually
        if not sess.is_valid:
            errors[('basic', sess.id)] = \
                '{date}: {err}'.format(date=sess.short_date_as_string, err=sess.error)

    # CONSTRAINT 2 - number of assessors should be nonzero
    if obj.number_assessors is None or obj.number_assessors == 0:
        errors[('settings', 0)] = \
            'Number of assessors is zero or unset'

    if len(errors) > 0 or len(warnings) > 0:
        return False, errors, warnings

    return True, errors, warnings


class PresentationAssessment(db.Model):
    """
    Store data for a presentation assessment
    """

    __tablename__ = 'presentation_assessments'


    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # year should match an available year in MainConfig
    year = db.Column(db.Integer(), db.ForeignKey('main_config.year'))
    main_config = db.relationship('MainConfig', foreign_keys=[year], uselist=False,
                                  backref=db.backref('presentation_assessments', lazy='dynamic'))


    # CONFIGURATION

    # name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True)

    # submission sessions to which we are attached
    submission_periods = db.relationship('SubmissionPeriodRecord', secondary=assessment_to_periods, lazy='dynamic',
                                         backref=db.backref('presentation_assessments', lazy='dynamic'))

    # number of faculty assessors to schedule
    number_assessors = db.Column(db.Integer())


    # AVAILABILITY LIFECYCLE

    # have we sent availability requests to faculty?
    requested_availability = db.Column(db.Boolean())

    # can availabilities still be modified?
    availability_closed = db.Column(db.Boolean())

    # what deadline has been set of availability information to be returned?
    availability_deadline = db.Column(db.Date())

    # list of faculty members still to return availability data
    availability_outstanding = db.relationship('FacultyData', secondary=faculty_availability_waiting, lazy='dynamic',
                                               backref=db.backref('availability_waiting', lazy='dynamic'))

    # list of faculty members who are potential assessors for talks in this assessment
    # (this list is computed and populated when we issue availability requests)
    assessors = db.relationship('FacultyData', secondary=assessment_to_assessors, lazy='dynamic',
                                backref=db.backref('presentation_assessments', lazy='dynamic'))


    # STUDENTS/TALKS

    # list of students who can't attend the main sessions
    cant_attend = db.relationship('SubmissionRecord', secondary=assessment_not_attend, lazy='dynamic')


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False,
                                 backref=db.backref('presentation_assessments', lazy='dynamic'))

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = {}
        self._warnings = {}


    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = {}
        self._warnings = {}


    AVAILABILITY_NOT_REQUESTED = 0
    AVAILABILITY_REQUESTED = 1
    AVAILABILITY_CLOSED = 2

    @property
    def availability_lifecycle(self):
        if self.requested_availability is False:
            return PresentationAssessment.AVAILABILITY_NOT_REQUESTED

        if self.availability_closed is False:
            return PresentationAssessment.AVAILABILITY_REQUESTED

        return PresentationAssessment.AVAILABILITY_CLOSED


    @property
    def availability_outstanding_count(self):
        return get_count(self.availability_outstanding)


    def is_faculty_outstanding(self, faculty_id):
        return get_count(self.availability_outstanding.filter_by(id=faculty_id)) > 0


    @property
    def time_to_availability_deadline(self):
        if self.availability_deadline is None:
            return '<invalid>'

        delta = self.availability_deadline - date.today()
        return format_readable_time(delta)


    @property
    def ordered_sessions(self):
        return self.sessions.order_by(PresentationSession.date.asc(), PresentationSession.session_type.asc())


    @property
    def number_slots(self):
        return sum([sess.number_rooms for sess in self.sessions])


    @property
    def is_valid(self):
        """
        Perform validation
        :return:
        """

        flag, self._errors, self._warnings = _PresentationAssessment_is_valid(self.id)
        self._validated = True

        return flag


    @property
    def errors(self):
        if not self._validated:
            check = self.is_valid
        return self._errors.values()


    @property
    def warnings(self):
        if not self._validated:
            check = self.is_valid
        return self._warnings.values()


    @property
    def available_pclasses(self):
        q = self.submission_periods.subquery()

        pclass_ids = db.session.query(ProjectClass.id) \
            .select_from(q) \
            .join(ProjectClassConfig, ProjectClassConfig.id == q.c.config_id) \
            .join(ProjectClass, ProjectClass.id == ProjectClassConfig.pclass_id).distinct().subquery()

        return db.session.query(ProjectClass) \
            .join(pclass_ids, ProjectClass.id == pclass_ids.c.id) \
            .order_by(ProjectClass.name.asc()).all()


    @property
    def available_buildings(self):
        q = self.sessions.subquery()

        building_ids = db.session.query(Room.building_id) \
            .select_from(q) \
            .join(session_to_rooms, session_to_rooms.c.session_id == q.c.id) \
            .join(Room, Room.id == session_to_rooms.c.room_id).distinct().subquery()

        return db.session.query(Building) \
            .join(building_ids, Building.id == building_ids.c.id) \
            .order_by(Building.name.asc()).all()


    @property
    def available_rooms(self):
        q = self.sessions.subquery()

        room_ids = db.session.query(session_to_rooms.c.room_id) \
            .select_from(q) \
            .join(session_to_rooms, session_to_rooms.c.session_id == q.c.id).distinct().subquery()

        return db.session.query(Room) \
            .join(room_ids, Room.id == room_ids.c.id) \
            .join(Building, Building.id == Room.building_id) \
            .order_by(Building.name.asc(), Room.name.asc()).all()


    @property
    def available_sessions(self):
        return self.sessions.order_by(PresentationSession.date.asc(), PresentationSession.session_type.asc()).all()


    @property
    def available_talks(self):
        talks = []

        for period in self.submission_periods:
            talks += period.submitter_list.all()

        return talks


    def not_attending(self, record_id):
        return get_count(self.cant_attend.filter_by(id=record_id)) > 0


@listens_for(PresentationAssessment, 'before_update')
def _PresentationAssessment_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.id)


@listens_for(PresentationAssessment, 'before_insert')
def _PresentationAssessment_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.id)


@listens_for(PresentationAssessment, 'before_delete')
def _PresentationAssessment_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationAssessment_is_valid, target.id)


@cache.memoize()
def _PresentationSession_is_valid(id):
    obj = db.session.query(PresentationSession).filter_by(id=id).one()

    # CONSTRAINT 1 - sessions should be scheduled on a weekday
    if obj.date.weekday() >= 5:
        return False, 'Session scheduled on a weekend'

    # CONSTRAINT 2 - only one session should be scheduled per morning/afternoon on a fixed date
    # check how many sessions are assigned to this date and morning/afternoon
    count = get_count(obj.owner.sessions.filter_by(date=obj.date, session_type=obj.session_type))

    if count != 1:
        lo_rec = obj.owner.sessions \
            .filter_by(date=obj.date, session_type=obj.session_type) \
            .order_by(PresentationSession.date.asc(),
                      PresentationSession.session_type.asc()).first()

        if lo_rec is not None:
            if lo_rec.id == obj.id:
                return False, 'A duplicate copy of this session exists'
            else:
                return False, 'This session is a duplicate'

    # CONSTRAINT 3 - if faculty availability information is available, then there should be enough
    # faculty available to cover all the available rooms
    if obj.owner.requested_availability:
        number_rooms = get_count(obj.rooms)
        number_faculty = get_count(obj.faculty)

        if obj.owner.number_assessors is not None:
            if number_faculty < obj.owner.number_assessors * number_rooms:
                return False, 'Too few assessors are available for the number of rooms'

    return True, None


class PresentationSession(db.Model):
    """
    Store data about a presentation session
    """

    __tablename__ = 'presentation_sessions'


    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # assessment this session is part of
    owner_id = db.Column(db.Integer(), db.ForeignKey('presentation_assessments.id'))
    owner = db.relationship('PresentationAssessment', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('sessions', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # session date
    date = db.Column(db.Date())

    # morning or afternoon
    MORNING_SESSION = 0
    AFTERNOON_SESSION = 1

    SESSION_TO_TEXT = {MORNING_SESSION: 'morning',
                       AFTERNOON_SESSION: 'afternoon'}

    SESSION_LABEL_TYPES = {MORNING_SESSION: 'label-success',
                           AFTERNOON_SESSION: 'label-primary'}

    session_type = db.Column(db.Integer())

    # rooms available for this session
    rooms = db.relationship('Room', secondary=session_to_rooms, lazy='dynamic',
                            backref=db.backref('sessions', lazy='dynamic'))

    # faculty available for this session
    faculty = db.relationship('FacultyData', secondary=faculty_availability, lazy='dynamic',
                              backref=db.backref('session_availability', lazy='dynamic'))


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False,
                                 backref=db.backref('presentation_sessions', lazy='dynamic'))

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error = None


    @orm.reconstructor
    def _reconstruct(self):
        self.error = None


    def make_label(self, text):
        if self.session_type in PresentationSession.SESSION_LABEL_TYPES:
            label_type = PresentationSession.SESSION_LABEL_TYPES[self.session_type]
        else:
            label_type = 'label-default'

        return '<span class="label {type}">{text}</span>'.format(type=label_type, text=text)

    @property
    def label(self):
        return self.make_label(self.short_date_as_string + ' ' + self.session_type_string)


    @property
    def date_as_string(self):
        return self.date.strftime("%a %d %b %Y")


    @property
    def short_date_as_string(self):
        return self.date.strftime("%d/%m/%Y")


    @property
    def session_type_string(self):
        if self.session_type in PresentationSession.SESSION_TO_TEXT:
            return PresentationSession.SESSION_TO_TEXT[self.session_type]

        return '<unknown>'


    @property
    def session_type_label(self):
        if self.session_type in PresentationSession.SESSION_TO_TEXT:
            if self.session_type in PresentationSession.SESSION_LABEL_TYPES:
                label_type = PresentationSession.SESSION_LABEL_TYPES[self.session_type]
            else:
                label_type = 'label-default'

            return '<span class="label {type}">{tag}</span>'.format(type=label_type, tag=self.session_type_string)

        return '<span class="label label-danger">Unknown session type</span>'


    @property
    def is_valid(self):
        flag, self.error = _PresentationSession_is_valid(self.id)

        return flag


    @property
    def ordered_rooms(self):
        return self.rooms.filter_by(active=True) \
            .join(Building, Building.id == Room.building_id) \
            .order_by(Building.name.asc(),
                      Room.name.asc())


    @property
    def number_faculty(self):
        return get_count(self.faculty)


    @property
    def number_rooms(self):
        return get_count(self.rooms)


    @property
    def ordered_faculty(self):
        return self.faculty \
            .join(User, User.id == FacultyData.id) \
            .order_by(User.last_name.asc(), User.first_name.asc())


    def in_session(self, faculty_id):
        return get_count(self.faculty.filter_by(id=faculty_id)) > 0


@listens_for(PresentationSession, 'before_update')
def _PresentationSession_update_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationSession_is_valid, target.id)
        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)

        dups = db.session.query(PresentationSession) \
            .filter_by(date=target.date, owner_id=target.owner_id, session_type=target.session_type).all()
        for dup in dups:
            if dup.id != target.id:
                cache.delete_memoized(_PresentationSession_is_valid, dup.id)


@listens_for(PresentationSession, 'before_insert')
def _PresentationSession_insert_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationSession_is_valid, target.id)
        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)

        dups = db.session.query(PresentationSession) \
            .filter_by(date=target.date, owner_id=target.owner_id, session_type=target.session_type).all()
        for dup in dups:
            if dup.id != target.id:
                cache.delete_memoized(_PresentationSession_is_valid, dup.id)


@listens_for(PresentationSession, 'before_delete')
def _PresentationSession_delete_handler(mapper, connection, target):
    with db.session.no_autoflush:
        cache.delete_memoized(_PresentationSession_is_valid, target.id)
        cache.delete_memoized(_PresentationAssessment_is_valid, target.owner_id)

        dups = db.session.query(PresentationSession) \
            .filter_by(date=target.date, owner_id=target.owner_id, session_type=target.session_type).all()
        for dup in dups:
            if dup.id != target.id:
                cache.delete_memoized(_PresentationSession_is_valid, dup.id)


class Building(db.Model, ColouredLabelMixin):
    """
    Store data modelling a building that houses bookable rooms for presentation assessments
    """

    __tablename__ = 'buildings'


    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)

    # active flag
    active = db.Column(db.Boolean())


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    def make_label(self, text=None, user_classes=None):
        if text is None:
            text = self.name

        return self._make_label(text, user_classes)


    def enable(self):
        self.active = True

        for room in self.rooms:
            room.disable()


    def disable(self):
        self.active = False


class Room(db.Model):
    """
    Store data modelling a bookable room for presentation assessments
    """

    __tablename__ = 'rooms'


    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # building
    building_id = db.Column(db.Integer(), db.ForeignKey('buildings.id'))
    building = db.relationship('Building', foreign_keys=[building_id], uselist=False,
                               backref=db.backref('rooms', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # room name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)

    # room capacity (currently not used)
    capacity = db.Column(db.Integer())

    # active flag
    active = db.Column(db.Boolean())


    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    @property
    def full_name(self):
        return self.building.name + ' ' + self.name


    @property
    def label(self):
        return self.make_label()


    def make_label(self, user_classes=None):
        return self.building.make_label(self.full_name, user_classes)


    def enable(self):
        if self.available:
            self.active = True


    def disable(self):
        self.active = False


    @property
    def available(self):
        return self.building.active


class ScheduleAttempt(db.Model, PuLPMixin):
    """
    Model configuration data for an assessment scheduling attempt
    """

    # make table name plural
    __tablename__ = 'scheduling_attempts'


    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # owning assessment
    owner_id = db.Column(db.Integer(), db.ForeignKey('presentation_assessments.id'))
    owner = db.relationship('PresentationAssessment', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('scheduling_attempts', lazy='dynamic'))

    # a name for this matching attempt
    name = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), unique=True)

    # flag whether this attempt has been published to convenors for comments or editing
    published = db.Column(db.Boolean())


    # CELERY TASK DATA

    # Celery taskid, used in case we need to revoke the task;
    # normally this will be the UUID
    celery_id = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'))

    # finished executing?
    finished = db.Column(db.Boolean())


    # CONFIGURATION

    # target number of students per group;
    max_group_size = db.Column(db.Integer())



    # EDITING METADATA

    # created by
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[creator_id], uselist=False)

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())

    # last editor
    last_edit_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    last_edited_by = db.relationship('User', foreign_keys=[last_edit_id], uselist=False)

    # last edited timestamp
    last_edit_timestamp = db.Column(db.DateTime())


    @property
    def available_pclasses(self):
        return self.owner.available_pclasses


    @property
    def buildings_query(self):
        q = self.slots.subquery()

        building_ids = db.session.query(Room.building_id) \
            .select_from(q) \
            .join(PresentationSession, PresentationSession.id == q.c.session_id) \
            .join(session_to_rooms, session_to_rooms.c.session_id == PresentationSession.id) \
            .join(Room, Room.id == session_to_rooms.c.room_id).distinct().subquery()

        return db.session.query(Building) \
            .join(building_ids, Building.id == building_ids.c.building_id) \
            .order_by(Building.name.asc())


    @property
    def available_buildings(self):
        return self.buildings_query.all()


    @property
    def number_buildings(self):
        return get_count(self.buildings_query)


    @property
    def rooms_query(self):
        q = self.slots.subquery()

        return db.session.query(Room) \
            .select_from(q) \
            .join(Room, Room.id == q.c.room_id) \
            .join(Building, Building.id == Room.building_id) \
            .order_by(Building.name.asc(), Room.name.asc()).distinct()


    @property
    def available_rooms(self):
        return self.rooms_query.all()


    @property
    def number_rooms(self):
        return get_count(self.rooms_query)


    @property
    def sessions_query(self):
        q = self.slots.subquery()

        session_ids = db.session.query(PresentationSession.id) \
            .select_from(q) \
            .join(PresentationSession, PresentationSession.id == q.c.session_id).distinct().subquery()

        return db.session.query(PresentationSession) \
            .join(session_ids, PresentationSession.id == session_ids.c.id) \
            .order_by(PresentationSession.date.asc(), PresentationSession.session_type.asc())


    @property
    def available_sessions(self):
        return self.sessions_query.all()


    @property
    def number_sessions(self):
        return get_count(self.sessions_query)


    @property
    def is_valid(self):
        return False


class ScheduleSlot(db.Model):
    """
    Model a single slot in a schedule
    """

    __tablename__ = 'schedule_slots'


    # primary key id
    id = db.Column(db.Integer(), primary_key=True)


    # owning schedule
    owner_id = db.Column(db.Integer(), db.ForeignKey('scheduling_attempts.id'))
    owner = db.relationship('ScheduleAttempt', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('slots', lazy='dynamic', cascade='all, delete, delete-orphan'))

    # session
    session_id = db.Column(db.Integer(), db.ForeignKey('presentation_sessions.id'))
    session = db.relationship('PresentationSession', foreign_keys=[session_id], uselist=False)

    # room
    room_id = db.Column(db.Integer(), db.ForeignKey('rooms.id'))
    room = db.relationship('Room', foreign_keys=[room_id], uselist=False)

    # assessors attached to this slot
    assessors = db.relationship('FacultyData', secondary=faculty_to_slots, lazy='dynamic')

    # talks scheduled in this slot
    talks = db.relationship('SubmissionRecord', secondary=submitter_to_slots, lazy='dynamic')


    def has_pclass(self, pclass_id):
        q = self.talks \
            .join(SubmittingStudent, SubmittingStudent.id == SubmissionRecord.owner_id) \
            .join(ProjectClassConfig, ProjectClassConfig.id == SubmittingStudent.config_id) \
            .filter(ProjectClassConfig.pclass_id == pclass_id)
        return get_count(q) > 0


# ############################



# Models imported from thirdparty/celery_sqlalchemy_scheduler



class CrontabSchedule(db.Model):

    __tablename__ = 'celery_crontabs'

    id = db.Column(db.Integer, primary_key=True)
    minute = db.Column(db.String(64), default='*')
    hour = db.Column(db.String(64), default='*')
    day_of_week = db.Column(db.String(64), default='*')
    day_of_month = db.Column(db.String(64), default='*')
    month_of_year = db.Column(db.String(64), default='*')

    @property
    def schedule(self):
        return schedules.crontab(minute=self.minute,
                                 hour=self.hour,
                                 day_of_week=self.day_of_week,
                                 day_of_month=self.day_of_month,
                                 month_of_year=self.month_of_year)

    @classmethod
    def from_schedule(cls, dbsession, schedule):
        spec = {'minute': schedule._orig_minute,
                'hour': schedule._orig_hour,
                'day_of_week': schedule._orig_day_of_week,
                'day_of_month': schedule._orig_day_of_month,
                'month_of_year': schedule._orig_month_of_year}
        try:
            query = dbsession.query(CrontabSchedule)
            query = query.filter_by(**spec)
            existing = query.one()
            return existing
        except db.exc.NoResultFound:
            return cls(**spec)
        except db.exc.MultipleResultsFound:
            query = dbsession.query(CrontabSchedule)
            query = query.filter_by(**spec)
            query.delete()
            dbsession.commit()
            return cls(**spec)


class IntervalSchedule(db.Model):

    __tablename__ = 'celery_intervals'

    id = db.Column(db.Integer, primary_key=True)
    every = db.Column(db.Integer, nullable=False)
    period = db.Column(db.String(24))

    @property
    def schedule(self):
        return schedules.schedule(timedelta(**{self.period: self.every}))

    @classmethod
    def from_schedule(cls, dbsession, schedule, period='seconds'):
        every = max(schedule.run_every.total_seconds(), 0)
        try:
            query = dbsession.query(IntervalSchedule)
            query = query.filter_by(every=every, period=period)
            existing = query.one()
            return existing
        except db.exc.NoResultFound:
            return cls(every=every, period=period)
        except db.exc.MultipleResultsFound:
            query = dbsession.query(IntervalSchedule)
            query = query.filter_by(every=every, period=period)
            query.delete()
            dbsession.commit()
            return cls(every=every, period=period)


class DatabaseSchedulerEntry(db.Model):

    __tablename__ = 'celery_schedules'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255, collation='utf8_bin'))
    task = db.Column(db.String(255, collation='utf8_bin'))
    interval_id = db.Column(db.Integer, db.ForeignKey('celery_intervals.id'))
    crontab_id = db.Column(db.Integer, db.ForeignKey('celery_crontabs.id'))
    arguments = db.Column(db.String(255), default='[]')
    keyword_arguments = db.Column(db.String(255, collation='utf8_bin'), default='{}')
    queue = db.Column(db.String(255))
    exchange = db.Column(db.String(255))
    routing_key = db.Column(db.String(255))
    expires = db.Column(db.DateTime)
    enabled = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    total_run_count = db.Column(db.Integer, default=0)
    date_changed = db.Column(db.DateTime)

    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    owner = db.relationship(User, backref=db.backref('scheduled_tasks', lazy='dynamic'))

    interval = db.relationship(IntervalSchedule, backref=db.backref('entries', lazy='dynamic'))
    crontab = db.relationship(CrontabSchedule, backref=db.backref('entries', lazy='dynamic'))

    @property
    def args(self):
        return json.loads(self.arguments)

    @args.setter
    def args(self, value):
        self.arguments = json.dumps(value)

    @property
    def kwargs(self):
        kwargs_ = json.loads(self.keyword_arguments)
        if self.task == 'app.tasks.backup.backup' and isinstance(kwargs_, dict):
            if 'owner_id' in kwargs_:
                del kwargs_['owner_id']
            kwargs_['owner_id'] = self.owner_id
        return kwargs_

    @kwargs.setter
    def kwargs(self, kwargs_):
        if self.task == 'app.tasks.backup.backup' and isinstance(kwargs_, dict):
            if 'owner_id' in kwargs_:
                del kwargs_['owner_id']
        self.keyword_arguments = json.dumps(kwargs_)

    @property
    def schedule(self):
        if self.interval:
            return self.interval.schedule
        if self.crontab:
            return self.crontab.schedule


@listens_for(DatabaseSchedulerEntry, 'before_insert')
def _set_entry_changed_date(mapper, connection, target):

    target.date_changed = datetime.utcnow()
