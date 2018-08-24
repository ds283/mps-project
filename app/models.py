#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import flash
from flask_security import current_user, UserMixin, RoleMixin
from flask_sqlalchemy import SQLAlchemy

import sqlalchemy
from sqlalchemy import orm
from celery import schedules

from .shared.formatters import format_size, format_time
from .shared.colours import get_text_colour

from datetime import date, datetime, timedelta
import json
from os import path
from time import time
from uuid import uuid4


# make db available as a static variable, so we can import into other parts of the code
db = SQLAlchemy()


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


# labels and keys for 'submissions' field
submission_choices = [(0, 'None'), (1, 'One (yearly)'), (2, 'Two (termly)')]

# labels and keys for 'year' field; it's not possible to join in Y1; treat students as
# joining in Y2
year_choices = [(2, 'Year 2'), (3, 'Year 3'), (4, 'Year 4')]

# labels and keys for 'extent' field
extent_choices = [(1, '1 year'), (2, '2 years')]

# labels and keys for 'academic titles' field
academic_titles = [(1, 'Dr'), (2, 'Professor'), (3, 'Mr'), (4, 'Ms'), (5, 'Mrs'), (6, 'Miss')]

# labels and keys for years_history
matching_history_choices = [(1, '1 year'), (2, '2 years'), (3, '3 years'), (4, '4 years'), (5, '5 years')]


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

# association table giving association between projects and supervision team
project_supervision = db.Table('project_to_supervision',
                               db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                               db.Column('supervisor.id', db.Integer(), db.ForeignKey('supervision_team.id'), primary_key=True))

# association table giving 2nd markers
second_markers = db.Table('project_to_markers',
                          db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                          db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True))


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

# association table giving 2nd markers
live_second_markers = db.Table('live_project_to_markers',
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


class MainConfig(db.Model):
    """
    Main application configuration table; generally, there should only
    be one row giving the current configuration
    """

    # year is the main configuration variable
    year = db.Column(db.Integer(), primary_key=True)

    # which matching configuration did we use to rollover from this year?
    # null means not committed yet
    matching_id = db.Column(db.Integer(), db.ForeignKey('matching_attempts.id'), nullable=True)
    matching_config = db.relationship('MatchingAttempt', foreign_keys=[matching_id], uselist=False)


    @property
    def matching_is_set(self):

        return self.matching_id is not None


class Role(db.Model, RoleMixin):
    """
    Model a row from the roles table in the application database
    """

    # make table name plural
    __tablename__ = 'roles'

    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True)
    description = db.Column(db.String(DEFAULT_STRING_LENGTH))


class User(db.Model, UserMixin):
    """
    Model a row from the user table in the application database
    """

    # make table name plural
    __tablename__ = 'users'

    id = db.Column(db.Integer(), primary_key=True)
    email = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True, unique=True)

    username = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True, unique=True)
    password = db.Column(db.String(PASSWORD_HASH_LENGTH))

    first_name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)
    last_name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)

    active = db.Column(db.Boolean())

    confirmed_at = db.Column(db.DateTime())
    last_login_at = db.Column(db.DateTime())
    current_login_at = db.Column(db.DateTime())
    last_login_ip = db.Column(db.String(IP_LENGTH))
    current_login_ip = db.Column(db.String(IP_LENGTH))
    login_count = db.Column(db.Integer())

    roles = db.relationship('Role', secondary=roles_to_users,
                            backref=db.backref('users', lazy='dynamic'))


    # allow user objects to get all project classes so that we can render
    # a 'Convenor' menu in the navbar for all admin users
    def get_project_classes(self):
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
               'danger': 'alert-danger'}


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


class ResearchGroup(db.Model):
    """
    Model a row from the research group table
    """

    # make table name plural
    __tablename__ = 'research_groups'

    id = db.Column(db.Integer(), primary_key=True)

    # abbreviation for use in space-limited contexts
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True, unique=True)

    # long-form name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # optional website
    website = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # active flag
    active = db.Column(db.Boolean())

    # colour string
    colour = db.Column(db.String(DEFAULT_STRING_LENGTH))

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


    def make_CSS_style(self):

        if self.colour is None:
            return None

        return "background-color:{bg}; color:{fg};".format(bg=self.colour, fg=get_text_colour(self.colour))


    def make_label(self, text=None):
        """
        Make approriately coloured label
        :param text:
        :return:
        """

        if text is None:
            text = self.abbreviation

        style = self.make_CSS_style()
        if style is None:
            return '<span class="label label-default">{msg}</span>'.format(msg=text)

        return '<span class="label label-default" style="{sty}">{msg}</span>'.format(msg=text,
                                                                                     sty=self.make_CSS_style())


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
    office = db.Column(db.String(DEFAULT_STRING_LENGTH))


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
            return '<span class="label label-warning"><i class="fa fa-times"></i> {n} available</span>'.format(n=n)

        return '<span class="label label-primary"><i class="fa fa-check"></i> {n} available</span>'.format(n=n)


    @property
    def projects_unofferable(self):

        unofferable = 0
        for proj in self.projects:
            if proj.active and not proj.offerable:
                unofferable += 1

        return unofferable


    @property
    def projects_unofferable_label(self):

        n = self.projects_unofferable

        if n == 0:
            return '<span class="label label-default"><i class="fa fa-check"></i> {n} unofferable</span>'.format(n=n)

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


    def remove_enrollment(self, pclass, autocommit=False):
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

        if autocommit:
            db.session.commit()


    def add_enrollment(self, pclass, autocommit=False):
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
                                  creator_id=current_user.id,
                                  creation_timestamp=datetime.now(),
                                  last_edit_id=None,
                                  last_edit_timestamp=None)

        db.session.add(record)
        db.session.commit()

        if autocommit:
            db.session.commit()


    def enrolled_labels(self, pclass):

        record = self.get_enrollment_record(pclass)

        if record is None:
            return '<span class="label label-warning">Not enrolled</span>'

        return record.enrolled_labels()


    def get_enrollment_record(self, pclass):

        return self.enrollments.filter_by(pclass_id=pclass.id).first()


    @property
    def is_convenor(self):
        """
        Determine whether this faculty member is convenor for any projects
        :return:
        """

        if self.convenor_for is not None and self.convenor_for.first() is not None:
            return True

        if self.coconvenor_for is not None and self.coconvenor_for.first() is not None:
            return True

        return False


    @property
    def convenor_list(self):
        """
        Return list of projects for which this faculty member is a convenor
        :return:
        """

        pcls = self.convenor_for.all() + self.coconvenor_for.all()
        return set(pcls)


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
    def number_marker(self):
        """
        Determine the number of projects to which we are attached as a 2nd marker
        :return:
        """

        return db.session.query(sqlalchemy.func.count(self.second_marker_for.subquery().c.id)).scalar()


    @property
    def marker_label(self):
        """
        Generate a label for the number of projects to which we are attached as a second marker
        :param pclass:
        :return:
        """

        num = self.number_marker

        if num == 0:
            return '<span class="label label-default"><i class="fa fa-times"></i> 0 marker</span>'

        return '<span class="label label-success"><i class="fa fa-check"></i> {n} marker</span>'.format(n=num)


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


    def cohort_label(self):

        return '<span class="label label-primary">{c} cohort</span>'.format(c=self.cohort)


class DegreeType(db.Model):
    """
    Model a degree type
    """

    # make table name plural
    __tablename__ = 'degree_types'

    id = db.Column(db.Integer(), primary_key=True)

    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)
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


class DegreeProgramme(db.Model):
    """
    Model a row from the degree programme table
    """

    # make table name plural
    __tablename__ = 'degree_programmes'

    id = db.Column(db.Integer(), primary_key=True)

    name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)
    active = db.Column(db.Boolean())

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

        if self.available():
            self.active = True


    def available(self):
        """
        Determine whether this degree programme is available for use (or activation)
        :return:
        """

        # ensure degree type is active
        return self.degree_type.active


    @property
    def full_name(self):

        return '{p} {t}'.format(p=self.name, t=self.degree_type.name)


    def label(self):

        return '<span class="label label-default">{n}</span>'.format(n=self.full_name)


class SkillGroup(db.Model):
    """
    Model a group of transferable skills
    """

    # make table name plural
    __tablename__ = "skill_groups"

    id = db.Column(db.Integer(), primary_key=True)

    # name of skill group
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)

    # active?
    active = db.Column(db.Boolean())

    # tag with a colour for easy recognition
    colour = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # add group name to lables
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


    def make_CSS_style(self):

        if self.colour is None:
            return None

        return "background-color:{bg}; color:{fg};".format(bg=self.colour, fg=get_text_colour(self.colour))



    def make_label(self, text=None, user_classes=None):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """

        if text is None:
            text = self.name

        css_style = self.make_CSS_style()
        if user_classes is None:
            classes = 'label label-default'
        else:
            classes = 'label label-default {cls}'.format(cls=user_classes)

        if css_style is None:
                return '<span class="{cls}">{msg}</span>'.format(msg=text, cls=classes)

        return '<span class="{cls}" style="{sty}">{msg}</span>'.format(msg=text, cls=classes, sty=css_style)


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

        return self.make_label(text=label, user_classes=user_classes)


class TransferableSkill(db.Model):
    """
    Model a transferable skill
    """

    # make table name plural
    __tablename__ = "transferable_skills"

    id = db.Column(db.Integer(), primary_key=True)

    # name of skill
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)

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


class ProjectClass(db.Model):
    """
    Model a single project class
    """

    # make table name plural
    __tablename__ = "project_classes"

    id = db.Column(db.Integer(), primary_key=True)

    # project class name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)

    # user-facing abbreviatiaon
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)

    # active?
    active = db.Column(db.Boolean())

    # colour to use to identify this project
    colour = db.Column(db.String(DEFAULT_STRING_LENGTH))


    # PRACTICAL DATA

    # which year does this project class run for?
    year = db.Column(db.Integer(), index=True)

    # how many years does the project extend? usually 1, but RP is more
    extent = db.Column(db.Integer())

    # how many submissions per year does this project have?
    submissions = db.Column(db.Integer())

    # are the submissions second marked?
    uses_marker = db.Column(db.Boolean())

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


    # AUTOMATED MATCHING

    # what level of automated student/project/2nd-marker matching does this project class use?
    # does it participate in the global automated matching, or is matching manual?
    do_matching = db.Column(db.Boolean())

    # number of 2nd markers that should be specified per project
    number_markers = db.Column(db.Integer())


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

        if self.available():
            self.active = True


    def available(self):
        """
        Determine whether this project class is available for use (or activation)
        :return:
        """

        # ensure that at least one active programme is available
        if not self.programmes.filter(DegreeProgramme.active).first():
            return False

        return True


    @property
    def convenor_email(self):

        return self.convenor.user.email


    @property
    def convenor_name(self):

        return self.convenor.user.name


    def is_convenor(self, id):

        if self.convenor_id == id:
            return True

        if any([item.id == id for item in self.coconvenors]):
            return True

        return False


    def make_CSS_style(self):

        if self.colour is None:
            return None

        return "background-color:{bg}; color:{fg};".format(bg=self.colour, fg=get_text_colour(self.colour))


    def make_label(self, text=None):
        """
        Make appropriately coloured label
        :param text:
        :return:
        """

        if text is None:
            text = self.name

        style = self.make_CSS_style()
        if style is None:
            return '<span class="label label-default">{msg}</span>'.format(msg=text)

        return '<span class="label label-default" style="{sty}">{msg}</span>'.format(msg=text,
                                                                                     sty=self.make_CSS_style())


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
    request_deadline = db.Column(db.DateTime())

    # have we gone 'live' this year, ie. frozen a definitive 'live table' of projects and
    # made these available to students?
    live = db.Column(db.Boolean())

    # who signed-off on go live event?
    golive_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    golive_by = db.relationship('User', uselist=False, foreign_keys=[golive_id])

    # golive timestamp
    golive_timestamp = db.Column(db.DateTime())

    # deadline for students to make their choices on the live system
    live_deadline = db.Column(db.DateTime())

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

    # is feedback open for the current submission period?
    feedback_open = db.Column(db.Boolean())


    # WORKLOAD MODEL

    # CATS awarded for supervising in this year
    CATS_supervision = db.Column(db.Integer())

    # CATS awarded for 2nd marking in this year
    CATS_marking = db.Column(db.Integer())


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
            if self.project_class.do_matching:
                # check whether a matching configuration has been assigned for the current year
                current_config = MainConfig.query.order_by(MainConfig.year.desc()).first()

                if current_config.matching_config is not None:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER
                else:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_MATCHING
            else:
                return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_ROLLOVER

        # open case is simple
        if self._selection_open:
            return ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN

        # if we get here, project is not open

        if self.project_class.require_confirm:
            if self.requests_issued:
                if self.golive_required.count() > 0:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS
                else:
                    return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE
            else:
                return ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED

        return ProjectClassConfig.SELECTOR_LIFECYCLE_READY_GOLIVE


    @property
    def time_to_request_deadline(self):

        if self.request_deadline is None:
            return '<invalid>'

        delta = self.request_deadline.date() - date.today()
        days = delta.days

        str = '{days} day'.format(days=days)

        if days != 1:
            str += 's'

        return str


    @property
    def time_to_live_deadline(self):

        if self.live_deadline is None:
            return '<invalid>'

        delta = self.live_deadline.date() - date.today()
        days = delta.days

        if days > 7:

            weeks = int(days/7)
            str = '{weeks} week'.format(weeks=weeks)

            if weeks != 1:
                str += 's'

            return str

        str = '{days} day'.format(days=days)

        if days != 1:
            str += 's'

        return str


    @property
    def number_selectors(self):

        return db.session.query(sqlalchemy.func.count(SelectingStudent.id)).with_parent(self).scalar()


    @property
    def number_submitters(self):

        return db.session.query(sqlalchemy.func.count(SubmittingStudent.id)).with_parent(self).scalar()


    @property
    def count_submitted_students(self):

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
        if not self.project_class.require_confirm:
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


class EnrollmentRecord(db.Model):
    """
    Capture details about a faculty member's enrollment
    """

    __tablename__ = 'enrollment_record'

    id = db.Column(db.Integer(), primary_key=True)

    # pointer to project class for which this is an enrollment record
    pclass_id = db.Column(db.Integer(), db.ForeignKey('project_classes.id'))
    pclass = db.relationship('ProjectClass', uselist=False, foreign_keys=[pclass_id])

    # pointer to faculty member this record is associated with
    owner_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'))
    owner = db.relationship('FacultyData', uselist=False, foreign_keys=[owner_id],
                            backref=db.backref('enrollments', lazy='dynamic', cascade='all, delete-orphan'))

    # enrollment for supervision
    SUPERVISOR_ENROLLED = 1
    SUPERVISOR_SABBATICAL = 2
    SUPERVISOR_EXEMPT = 3
    supervisor_choices = {(SUPERVISOR_ENROLLED, 'Normally enrolled'),
                          (SUPERVISOR_SABBATICAL, 'On sabbatical or buy-out'),
                          (SUPERVISOR_EXEMPT, 'Exempt')}
    supervisor_state = db.Column(db.Integer())

    # comment (eg. can be used to note circumstances of exemptions)
    supervisor_comment = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # sabbatical auto re-enroll year (after sabbatical)
    supervisor_reenroll = db.Column(db.Integer())

    # enrollment for 2nd marking
    MARKER_ENROLLED = 1
    MARKER_SABBATICAL = 2
    MARKER_EXEMPT = 3
    marker_choices = {(MARKER_ENROLLED, 'Normally enrolled'),
                      (MARKER_SABBATICAL, 'On sabbatical or buy-out'),
                      (MARKER_EXEMPT, 'Exempt')}
    marker_state = db.Column(db.Integer())

    # comment (eg. can be used to note circumstances of exemption)
    marker_comment = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # marker auto re-enroll year (after sabbatical)
    marker_reenroll = db.Column(db.Integer())

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


    def supervisor_label(self):

        if self.supervisor_state == self.SUPERVISOR_ENROLLED:
            return '<span class="label label-success"><i class="fa fa-check"></i> Supv active</span>'
        elif self.supervisor_state == self.SUPERVISOR_SABBATICAL:
            return '<span class="label label-warning"><i class="fa fa-times"></i> Supv sabbat{year}</span>'.format(
                year='' if self.supervisor_reenroll is None else ' ({yr})'.format(yr=self.supervisor_reenroll))
        elif self.supervisor_state == self.SUPERVISOR_EXEMPT:
            return '<span class="label label-danger"><i class="fa fa-times"></i> Supv exempt</span>'

        return ''


    def marker_label(self):

        if self.marker_state == EnrollmentRecord.MARKER_ENROLLED:
            return '<span class="label label-success"><i class="fa fa-check"></i> 2nd mk active</span>'
        elif self.marker_state == EnrollmentRecord.MARKER_SABBATICAL:
            return '<span class="label label-warning"><i class="fa fa-times"></i> 2nd mk sabbat{year}</span>'.format(
                year='' if self.marker_reenroll is None else ' ({yr})'.format(yr=self.marker_reenroll))
        elif self.marker_state == EnrollmentRecord.MARKER_EXEMPT:
            return '<span class="label label-danger"><i class="fa fa-times"></i> 2nd mk exempt</span>'

        return ''


    def enrolled_labels(self):

        return self.supervisor_label() + ' ' + self.marker_label()


class Supervisor(db.Model):
    """
    Model a supervision team member
    """

    # make table name plural
    __tablename__ = 'supervision_team'

    id = db.Column(db.Integer(), primary_key=True)

    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True)
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


class Project(db.Model):
    """
    Model a project
    """

    # make table name plural
    __tablename__ = "projects"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # project name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)

    # active flag
    active = db.Column(db.Boolean())

    # which faculty member owns this project?
    owner_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'), index=True)
    owner = db.relationship('FacultyData', foreign_keys=[owner_id], backref=db.backref('projects', lazy='dynamic'))


    # TAGS AND METADATA

    # free keywords describing scientific area
    keywords = db.Column(db.String(DEFAULT_STRING_LENGTH))

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

    # maximum number of students
    capacity = db.Column(db.Integer())

    # table of allowed 2nd markers
    second_markers = db.relationship('FacultyData', secondary=second_markers, lazy='dynamic',
                                     backref=db.backref('second_marker_for', lazy='dynamic'))


    # PROJECT DESCRIPTION

    # project description
    description = db.Column(db.Text())

    # recommended reading
    reading = db.Column(db.Text())

    # supervisory roles
    team = db.relationship('Supervisor', secondary=project_supervision, lazy='dynamic',
                           backref=db.backref('projects', lazy='dynamic'))


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
    def offerable(self):
        """
        Determine whether this project is available for selection
        :return:
        """

        if not self.project_classes.filter(ProjectClass.active).first():
            self.error = "No active project types assigned to project"
            return False

        if not self.team.filter(Supervisor.active).first():
            self.error = "No active supervisory roles assigned to project"
            return False

        if self.group is None:
            self.error = "No active research group affiliated with project"
            return False

        if (self.capacity is None or self.capacity == 0) and self.enforce_capacity:
            self.error = "Capacity is zero or unset, but enforcement is enabled"
            return False

        # for each project class we are attached to, check whether enough 2nd markers have been assigned
        for pclass in self.project_classes:

            if pclass.uses_marker:
                if self.num_markers(pclass) < pclass.number_markers:
                    self.error = "Too few 2nd markers assigned for '{name}'".format(name=pclass.name)
                    return False

        return True


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

        for prog in self.programmes:

            if available_programmes is None or prog not in available_programmes:
                self.remove_programme(prog)


    def is_second_marker(self, faculty):
        """
        Determine whether a given FacultyData instance is a 2nd marker for this project
        :param faculty:
        :return:
        """

        return faculty in self.second_markers


    def num_markers(self, pclass):
        """
        Determine the number of 2nd markers enrolled who are available for a given project class
        :param pclass:
        :return:
        """

        number = 0

        for marker in self.second_markers:

            # ignore inactive users
            if not marker.user.active:
                break

            # count number of enrollment records for this marker matching the project class, and marked as active
            query = marker.enrollments.subquery()

            num = db.session.query(sqlalchemy.func.count(query.c.id)) \
                .filter(query.c.pclass_id == pclass.id,
                        query.c.marker_state == EnrollmentRecord.MARKER_ENROLLED) \
                .scalar()

            if num == 1:
                number += 1
            elif num > 1:
                raise RuntimeError('Inconsistent enrollment records')

        return number


    def get_marker_list(self, pclass):
        """
        Build a list of FacultyData objects for 2nd markers attached to this project who are
        available for a given project class
        :param pclass:
        :return:
        """

        markers = []

        for marker in self.second_markers:

            # ignore inactive users
            if not marker.user.active:
                break

            # count number of enrollment records for this marker matching the project class, and marked as active
            query = marker.enrollments.subquery()

            num = db.session.query(sqlalchemy.func.count(query.c.id)) \
                .filter(query.c.pclass_id == pclass.id,
                        query.c.marker_state == EnrollmentRecord.MARKER_ENROLLED) \
                .scalar()

            if num == 1:
                markers.append(marker)
            elif num > 1:
                raise RuntimeError('Inconsistent enrollment records')

        return markers


    def can_enroll_marker(self, faculty):
        """
        Determine whether a given FacultyData instance can be enrolled as a 2nd marker for this project
        :param faculty:
        :return:
        """

        if self.is_second_marker(faculty):
            return False

        # need to determine whether this faculty member is enrolled as a second marker for any project
        # class we are attached to
        enrollments = faculty.enrollments.subquery()
        pclasses = self.project_classes.subquery()

        number = db.session.query(sqlalchemy.func.count(enrollments.c.id)) \
            .join(User, User.id == enrollments.c.owner_id) \
            .join(pclasses, pclasses.c.id == enrollments.c.pclass_id) \
            .filter(User.active == True,
                    enrollments.c.marker_state == EnrollmentRecord.MARKER_ENROLLED) \
            .scalar()

        return number > 0


    def add_marker(self, faculty):
        """
        Add a FacultyData instance as a 2nd marker
        :param faculty:
        :return:
        """

        if self.is_second_marker(faculty):
            return

        self.second_markers.append(faculty)
        db.session.commit()


    def remove_marker(self, faculty):
        """
        Remove a FacultyData instance as a 2nd marker
        :param faculty:
        :return:
        """

        if not self.is_second_marker(faculty):
            return

        self.second_markers.remove(faculty)
        db.session.commit()



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
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)

    # which faculty member owns this project?
    owner_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'), index=True)
    owner = db.relationship('FacultyData', foreign_keys=[owner_id],
                            backref=db.backref('live_projects', lazy='dynamic'))


    # TAGS AND METADATA

    # free keywords describing scientific area
    keywords = db.Column(db.String(DEFAULT_STRING_LENGTH))

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

    # table of allowed 2nd markers
    second_markers = db.relationship('FacultyData', secondary=live_second_markers, lazy='dynamic',
                                     backref=db.backref('second_marker_for_live', lazy='dynamic'))


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
        if self.meeting_reqd != self.MEETING_REQUIRED or self.owner.faculty_data.sign_off_students is False:
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

        return db.session.query(sqlalchemy.func.count(Bookmark.id)).filter_by(liveproject_id=self.id).scalar()


    @property
    def number_selections(self):

        return db.session.query(sqlalchemy.func.count(SelectionRecord.id)).filter_by(liveproject_id=self.id).scalar()


    @property
    def number_pending(self):

        return db.session.query(sqlalchemy.func.count(self.confirm_waiting.subquery().c.id)).scalar()


    @property
    def number_confirmed(self):

        return db.session.query(sqlalchemy.func.count(self.confirmed_students.subquery().c.id)).scalar()


    def format_popularity_label(self, css_classes=None):

        if not self.parent.show_popularity:
            return None

        return self.popularity_label(css_classes)


    def popularity_label(self, css_classes=None):

        cls = '' if css_classes is None else ' '.join(css_classes)

        score = self.popularity_rank
        if score is None:
            return '<span class="label label-default {cls}">Popularity unavailable</span>'.format(cls=cls)

        rank, total = score
        lowest_rank = self.lowest_popularity_rank

        frac = float(rank)/float(total)
        lowest_frac = float(lowest_rank)/float(total)

        if lowest_frac > 0.4:
            return '<span class="label label-default {cls}">Popularity available soon</span>'.format(cls=cls)

        label='Low'
        if frac > 0.9:
            label = 'Very high'
        elif frac > 0.7:
            label = 'High'
        elif frac > 0.4:
            label = 'Medium'

        return '<span class="label label-success {cls}">Popularity: {{ label }}</span>'.format(cls=cls, label=label)


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

        prog_query = self.programmes.subquery()
        count = db.session.query(sqlalchemy.func.count(prog_query.c.id)) \
            .filter(prog_query.c.id == sel.student.programme_id).scalar()

        if count == 1:
            return True

        if count > 1:
            raise RuntimeError('Inconsistent number of degree preferences match a single SelectingStudent')

        return False


class SelectingStudent(db.Model):
    """
    Model a student who is selecting a project in the current cycle
    """

    __tablename__ = 'selecting_students'


    # surrogate key for (config_id, user_id) - need to ensure these remain unique!
    id = db.Column(db.Integer(), primary_key=True)

    retired = db.Column(db.Integer())

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

        return db.session.query(sqlalchemy.func.count(self.confirm_requests.subquery().c.id)).scalar()


    @property
    def number_confirmed(self):

        return db.session.query(sqlalchemy.func.count(self.confirmed.subquery().c.id)).scalar()


    @property
    def has_bookmarks(self):
        """
        determine whether this SelectingStudent has bookmarks
        :return:
        """

        return self.bookmarks.first() is not None


    @property
    def get_ordered_bookmarks(self):
        """
        return bookmarks in rank order
        :return:
        """

        return self.bookmarks.order_by(Bookmark.rank)


    @property
    def get_num_bookmarks(self):

        return db.session.query(sqlalchemy.func.count(Bookmark.id)).with_parent(self).scalar()


    @property
    def get_academic_year(self):
        """
        Compute the current academic year for this student, relative this ProjectClassConfig
        :return:
        """

        return self.config.year - self.student.cohort + 1


    def academic_year_label(self):

        return '<span class="label label-info">Y{y}</span>'.format(y=self.get_academic_year)


    @property
    def is_initial_selection(self):
        """
        Determine whether this is the initial selection or a switch
        :return:
        """

        academic_year = self.get_academic_year

        return academic_year == self.config.project_class.year-1


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
    def get_ordered_selection(self):

        return self.selections.order_by(SelectionRecord.rank)


    def project_rank(self, proj_id):

        if self.has_submitted:
            for item in self.selections.all():
                if item.liveproject_id == proj_id:
                    return item.rank
            return None

        if self.has_bookmarks:
            for item in self.bookmarks.all():
                if item.liveproject_id == proj_id:
                    return item.rank
            return None

        return None


class SubmittingStudent(db.Model):
    """
    Model a student who is submitting work for evaluation in the current cycle
    """

    __tablename__ = 'submitting_students'


    # surrogate key for (config_id, user_id) - need to ensure these remain unique!
    id = db.Column(db.Integer(), primary_key=True)

    retired = db.Column(db.Integer())

    # key to ProjectClass config record that identifies this year and pclass
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', uselist=False,
                             backref=db.backref('submitting_students', lazy='dynamic'))

    # key to student userid
    student_id = db.Column(db.Integer(), db.ForeignKey('student_data.id'))
    student = db.relationship('StudentData', foreign_keys=[student_id], uselist=False,
                              backref=db.backref('submitting', lazy='dynamic'))


    @property
    def get_academic_year(self):
        """
        Compute the current academic year for this student, relative this ProjectClassConfig
        :return:
        """

        return self.config.year - self.student.cohort + 1


    def academic_year_label(self):

        return '<span class="label label-info">Y{y}</span>'.format(y=self.get_academic_year)


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
    user_id = db.Column(db.Integer(), db.ForeignKey('selecting_students.id'))
    owner = db.relationship('SelectingStudent', uselist=False,
                           backref=db.backref('bookmarks', lazy='dynamic', cascade='all, delete-orphan'))

    # LiveProject we are linking to
    liveproject_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    liveproject = db.relationship('LiveProject', uselist=False,
                                  backref=db.backref('bookmarks', lazy='dynamic'))

    # rank in owner's list
    rank = db.Column(db.Integer())


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
                           backref=db.backref('selections', lazy='dynamic', cascade='all, delete-orphan'))

    # LiveProject we are linking to
    liveproject_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    liveproject = db.relationship('LiveProject', foreign_keys=[liveproject_id], uselist=False,
                                  backref=db.backref('selections', lazy='dynamic'))

    # rank in owner's list
    rank = db.Column(db.Integer())


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
    recipient = db.Column(db.String(DEFAULT_STRING_LENGTH), nullable=True)

    # date of sending attempt
    send_date = db.Column(db.DateTime(), index=True)

    # subject
    subject = db.Column(db.String(DEFAULT_STRING_LENGTH))

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
    title = db.Column(db.String(DEFAULT_STRING_LENGTH))

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
    description = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # date of backup
    date = db.Column(db.DateTime(), index=True)

    # type of backup
    SCHEDULED_BACKUP = 1
    PROJECT_ROLLOVER_FALLBACK = 2
    PROJECT_GOLIVE_FALLBACK = 3

    type = db.Column(db.Integer())

    # filename
    filename = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # uncompressed database size, in bytes
    db_size = db.Column(db.Integer())

    # compressed archive size, in bytes
    archive_size = db.Column(db.Integer())

    # total size of backups at this time, in bytes
    backup_size = db.Column(db.Integer())


    def type_to_string(self):

        if self.type == self.SCHEDULED_BACKUP:
            return 'Scheduled backup'
        elif self.type == self.PROJECT_ROLLOVER_FALLBACK:
            return 'Rollover restore point'
        elif self.type == self.PROJECT_GOLIVE_FALLBACK:
            return 'Go Live restore point'
        else:
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
    id = db.Column(db.String(DEFAULT_STRING_LENGTH), primary_key=True)

    # task owner
    owner_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    owner = db.relationship('User', uselist=False, backref=db.backref('tasks', lazy='dynamic'))

    # task launch date
    start_date = db.Column(db.DateTime())

    # task name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)

    # optional task description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH))

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
    message = db.Column(db.String(DEFAULT_STRING_LENGTH))


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
    uuid = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)

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
                                  backref=db.backref('popularity_data', lazy='dynamic', cascade='all, delete-orphan'))

    # tag ProjectClassConfig to which this record applies
    config_id = db.Column(db.Integer(), db.ForeignKey('project_class_config.id'))
    config = db.relationship('ProjectClassConfig', uselist=False,
                             backref=db.backref('popularity_data', lazy='dynamic', cascade='all, delete-orphan'))

    # date stamp for this calculation
    datestamp = db.Column(db.DateTime(), index=True)

    # UUID identifying all popularity records in a group
    uuid = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)


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


class MatchingAttempt(db.Model):
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

    # a name for this configuration
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True)


    # CELERY TASK DATA

    # Celery taskid, used in case we need to revoke the task;
    # typically this will be a UUID
    celery_id = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # finished executing?
    finished = db.Column(db.Boolean())


    # METADATA

    # outcome report from PuLP
    OUTCOME_OPTIMAL = 0
    OUTCOME_NOT_SOLVED = 1
    OUTCOME_INFEASIBLE = 2
    OUTCOME_UNBOUNDED = 3
    OUTCOME_UNDEFINED = 4
    outcome = db.Column(db.Integer())

    # timestamp
    timestamp = db.Column(db.DateTime(), index=True)

    # time taken to construct the PuLP problem
    construct_time = db.Column(db.Numeric(8, 3))

    # time taken by PulP to compute the solution
    compute_time = db.Column(db.Numeric(8, 3))

    # owner
    owner_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    owner = db.relationship('User', foreign_keys=[owner_id], uselist=False,
                            backref=db.backref('matching_attempts', lazy='dynamic'))


    # MATCHING OPTIONS

    # ignore CATS limits
    ignore_per_faculty_limits = db.Column(db.Boolean())

    # ignore degree programme preferences
    ignore_programme_prefs = db.Column(db.Boolean())

    # how many years memory to include when levelling CATS scores
    years_memory = db.Column(db.Integer())

    # global supervising CATS limit
    supervising_limit = db.Column(db.Integer())

    # global 2nd-marking CATS limit
    marking_limit = db.Column(db.Integer())

    # maximum multiplicity for 2nd markers
    max_marking_multiplicity = db.Column(db.Integer())


    # WORKLOAD LEVELLING

    # workload levelling bias
    # (this is the prefactor we use to set the normalization of the tension term in the objective function.
    # the tension term represents the difference in CATS between the upper and lower workload in each group,
    # plus another term (the 'intra group tension') that tensions all groups together. 'Group' here means
    # faculty that supervise only, mark only, or supervise and mark. Each group will typically have a different
    # median workload.)
    levelling_bias = db.Column(db.Numeric(8,3))

    # intra-group tensioning
    intra_group_tension = db.Column(db.Numeric(8,3))

    # programme matching bias
    programme_bias = db.Column(db.Numeric(8,3))


    # MATCHING OUTCOME

    # value of objective function, if match was successful
    score = db.Column(db.Numeric(10,2))


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
    mean_CATS_per_project = db.Column(db.Numeric(8,5))


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


    def get_faculty_CATS(self, fac):
        """
        :param fac: FacultyData instance
        :return:
        """

        CATS_supervisor = 0
        CATS_marker = 0

        for item in self.records.filter_by(supervisor_id=fac.id).all():
            config = item.project.config

            if config.CATS_supervision is not None and config.CATS_supervision > 0:
                CATS_supervisor += config.CATS_supervision

        for item in self.records.filter_by(marker_id=fac.id).all():
            config = item.project.config

            if config.project_class.uses_marker:
                if config.CATS_marking is not None and config.CATS_marking > 0:
                    CATS_marker += config.CATS_marking

        return CATS_supervisor, CATS_marker


    def _build_CATS_list(self):

        if self._CATS_list is not None:
            return

        fsum = lambda x: x[0] + x[1]

        self._build_faculty_list()
        self._CATS_list = [fsum(self.get_faculty_CATS(fac)) for fac in self.faculty]


    @property
    def selectors(self):
        self._build_selector_list()
        return self._selector_list.values()


    @property
    def faculty(self):
        self._build_faculty_list()
        return self._faculty_list.values()


    @property
    def formatted_construct_time(self):
        return format_time(self.construct_time)


    @property
    def formatted_compute_time(self):
        return format_time(self.compute_time)


    @property
    def selector_deltas(self):
        self._build_selector_list()
        fsum = lambda recs: sum([rec.delta for rec in recs])
        return [fsum(x) for x in self.selectors]


    @property
    def faculty_CATS(self):
        self._build_CATS_list()
        return self._CATS_list


    @property
    def delta_max(self):
        return max(self.selector_deltas)


    @property
    def delta_min(self):
        return min(self.selector_deltas)


    @property
    def CATS_max(self):
        return max(self.faculty_CATS)


    @property
    def CATS_min(self):
        return min(self.faculty_CATS)


    def get_supervisor_records(self, fac):
        return self.records.filter_by(supervisor_id=fac.id).order_by(MatchingRecord.submission_period.asc())


    def get_marker_records(self, fac):
        return self.records.filter_by(marker_id=fac.id).order_by(MatchingRecord.submission_period.asc())


    def number_project_assignments(self, project):
        records = self.records.subquery()

        return db.session.query(sqlalchemy.func.count(records.c.id)) \
            .filter(records.c.project_id == project.id).scalar()


    def is_project_overassigned(self, project):
        count = self.number_project_assignments(project)
        if project.enforce_capacity and project.capacity > 0 and count > project.capacity:
            return True

        return False


    def is_supervisor_overassigned(self, faculty):
        CATS_sup, CATS_mark = self.get_faculty_CATS(faculty)

        sup_lim = self.supervising_limit

        if not self.ignore_per_faculty_limits:
            if faculty.CATS_supervision is not None and faculty.CATS_supervision > 0:
                sup_lim = faculty.CATS_supervision

        if CATS_sup > sup_lim:
            return True, CATS_sup, sup_lim

        return False, CATS_sup, sup_lim


    def is_marker_overassigned(self, faculty):
        CATS_sup, CATS_mark = self.get_faculty_CATS(faculty)

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

        # there are several steps:
        #   1. Validate that each MatchingRecord is valid (2nd marker is not supervisor,
        #      LiveProject is attached to right class).
        #      These errors are fatal
        #   2. Validate that project capacity constraints are not violated.
        #      This is also a fatal error.
        #   3. Validate that faculty CATS limits are respected.
        #      This is a warning, not an error

        self._errors = {}
        self._warnings = {}
        self._student_issues = False
        self._faculty_issues = False

        for record in self.records:
            if not record.is_valid:
                self._errors[('basic', record.id)] \
                    = '{name}/{abbv}: {err}'.format(err=record.error,
                                                    name=record.selector.student.user.name,
                                                    abbv=record.selector.config.project_class.abbreviation)
                self._student_issues = True

        for project in self.projects:
            if self.is_project_overassigned(project):
                self._errors[('capacity', project.id)] = \
                    'Project "{supv}: {name}" is over-assigned ' \
                    '(assigned={m}, max capacity={n})'.format(supv=project.owner.user.name, name=project.name,
                                                              m=self.number_project_assignments(project),
                                                              n=project.capacity)
                self._student_issues = True

        for fac in self.faculty:
            sup_over, CATS_sup, sup_lim = self.is_supervisor_overassigned(fac)
            if sup_over:
                self._warnings[('supervising', fac.id)] = \
                    'Supervising workload for {name} exceeds CATS limit ' \
                    '(assigned={m}, max capacity={n})'.format(name=fac.user.name, m=CATS_sup, n=sup_lim)
                self._faculty_issues = True

            mark_over, CATS_mark, mark_lim = self.is_marker_overassigned(fac)
            if mark_over:
                self._warnings[('marking', fac.id)] = \
                    'Marking workload for {name} exceeds CATS limit ' \
                    '(assigned={m}, max capacity={n})'.format(name=fac.user.name, m=CATS_mark, n=mark_lim)
                self._faculty_issues = True

        self._validated = True

        if len(self._errors) > 0 or len(self._warnings) > 0:
            return False

        return True


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
        objective = sum([x.current_score for x in self.records])

        sup_dict = {x.id: x for x in self.supervisors}
        mark_dict = {x.id: x for x in self.markers}

        supervisor_ids = sup_dict.keys()
        marker_ids = mark_dict.keys()

        # these are set difference and set intersection operators
        sup_only_ids = supervisor_ids - marker_ids
        mark_only_ids = marker_ids - supervisor_ids
        sup_and_mark_ids = supervisor_ids & marker_ids

        sup_only = [sup_dict[i] for i in sup_only_ids]
        mark_only = [sup_dict[i] for i in mark_only_ids]
        sup_and_mark = [sup_dict[i] for i in sup_and_mark_ids]

        fsum = lambda x: x[0] + x[1]

        sup_CATS = [fsum(self.get_faculty_CATS(x)) for x in sup_only]
        mark_CATS = [fsum(self.get_faculty_CATS(x)) for x in mark_only]
        sup_mark_CATS = [fsum(self.get_faculty_CATS(x)) for x in sup_and_mark]

        minList = []
        maxList = []

        if len(sup_CATS) > 0:
            supMax = max(sup_CATS)
            supMin = min(sup_CATS)

            maxList.append(supMax)
            minList.append(supMin)
        else:
            supMax = 0.0
            supMin = 0.0

        if len(mark_CATS) > 0:
            markMax = max(mark_CATS)
            markMin = min(mark_CATS)

            maxList.append(markMax)
            minList.append(markMin)
        else:
            markMax = 0.0
            markMin = 0.0

        if len(sup_mark_CATS) > 0:
            supMarkMax = max(sup_mark_CATS)
            supMarkMin = min(sup_mark_CATS)

            maxList.append(supMarkMax)
            minList.append(supMarkMin)
        else:
            supMarkMax = 0.0
            supMarkMin = 0.0

        globalMin = min(minList) if len(minList) > 0 else 0.0
        globalMax = max(maxList) if len(maxList) > 0 else 0.0

        levelling = (supMax - supMin) \
                    + (markMax - markMin) \
                    + (supMarkMax - supMarkMin) \
                    + abs(float(self.intra_group_tension)) * (globalMax - globalMin)

        return objective - abs(float(self.levelling_bias))*levelling/float(self.mean_CATS_per_project)


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
                                       backref=db.backref('records', lazy='dynamic'))

    # owning SelectingStudent
    selector_id = db.Column(db.Integer(), db.ForeignKey('selecting_students.id'))
    selector = db.relationship('SelectingStudent', foreign_keys=[selector_id], uselist=False,
                               backref=db.backref('matching_records', lazy='dynamic'))

    # submission period
    submission_period = db.Column(db.Integer())

    # assigned project
    project_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    project = db.relationship('LiveProject', foreign_keys=[project_id], uselist=False,
                              backref=db.backref('student_matches', lazy='dynamic'))

    # assigned supervisor (redundant with project, but allows us to attach a backref from the
    # supervisor's FacultyData record)
    supervisor_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'))
    supervisor = db.relationship('FacultyData', foreign_keys=[supervisor_id], uselist=False,
                                 backref=db.backref('supervisor_matches', lazy='dynamic'))

    # rank of this project in the student's selection
    rank = db.Column(db.Integer())

    # assigned second marker, or none if second markers are not used
    marker_id = db.Column(db.Integer(), db.ForeignKey('faculty_data.id'))
    marker = db.relationship('FacultyData', foreign_keys=[marker_id], uselist=False,
                             backref=db.backref('marker_matches', lazy='dynamic'))


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error = None


    @orm.reconstructor
    def _reconstruct(self):
        self.error = None


    @property
    def is_valid(self):

        if self.supervisor_id == self.marker_id:
            self.error = 'Supervisor and marker are the same'
            return False

        if (self.selector.has_submitted or self.selector.has_bookmarks) \
                and self.selector.project_rank(self.project_id) is None:
            self.error = "Assigned project does not appear in this selector's choices"
            return False

        if self.project.config_id != self.selector.config_id:
            self.error = 'Assigned project does not belong to the correct class for this selector'
            return False

        markers = self.project.second_markers.subquery()
        count = db.session.query(sqlalchemy.func.count(markers.c.id)) \
            .filter(markers.c.id == self.marker_id).scalar()
        if count != 1:
            self.error = 'Assigned 2nd marker is not compatible with assigned project'
            return False

        return True


    @property
    def is_overassigned(self):
        if self.matching_attempt.is_project_overassigned(self.project):
            self.error = 'Project "{supv} - {name}" is over-assigned ' \
                         '(assigned={m}, max capacity={n})'.format(supv=self.project.owner.user.name, name=self.project.name,
                                                                   m=self.matching_attempt.number_project_assignments(self.project),
                                                                   n=self.project.capacity)
            return True

        return False


    @property
    def delta(self):
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
        # score is 1/rank of assigned project, weighted
        weight = 1.0

        if not self.matching_attempt.ignore_programme_prefs:
            if self.project.satisfies_preferences(self.selector):
                weight *= self.matching_attempt.programme_bias

        return weight / float(self.rank)


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
    name = db.Column(db.String(255))
    task = db.Column(db.String(255))
    interval_id = db.Column(db.Integer, db.ForeignKey('celery_intervals.id'))
    crontab_id = db.Column(db.Integer, db.ForeignKey('celery_crontabs.id'))
    arguments = db.Column(db.String(255), default='[]')
    keyword_arguments = db.Column(db.String(255), default='{}')
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


@sqlalchemy.event.listens_for(DatabaseSchedulerEntry, 'before_insert')
def _set_entry_changed_date(mapper, connection, target):

    target.date_changed = datetime.utcnow()
