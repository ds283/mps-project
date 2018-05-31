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
from flask_security import UserMixin, RoleMixin
from flask_sqlalchemy import SQLAlchemy

from datetime import date, timedelta


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
academic_titles = [(1, 'Dr'), (2, 'Professor')]


# association table holding mapping from roles to users
roles_to_users = db.Table('roles_users',
                          db.Column('user_id', db.Integer(), db.ForeignKey('users.id'), primary_key=True),
                          db.Column('role_id', db.Integer(), db.ForeignKey('roles.id'), primary_key=True)
                          )

# association table giving faculty research group affiliations
faculty_affiliations = db.Table('faculty_affiliations',
                                db.Column('user_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                                db.Column('group_id', db.Integer(), db.ForeignKey('research_groups.id'), primary_key=True)
                                )


# PROJECT CLASS ASSOCIATIONS


# association table giving faculty enrollment on project classes
faculty_enrollments = db.Table('faculty_enrollments',
                               db.Column('user_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                               db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True)
                               )

# association table giving association between project classes and degree programmes
pclass_programme_associations = db.Table('project_class_to_programmes',
                                         db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True),
                                         db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True)
                                         )


# SYSTEM MESSAGES


# association between project classes and messages
pclass_message_associations = db.Table('project_class_to_messages',
                                       db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True),
                                       db.Column('message_id', db.Integer(), db.ForeignKey('messages.id'), primary_key=True)
                                       )

# associate dismissals with messages
message_dismissals = db.Table('message_dismissals',
                              db.Column('message_id', db.Integer(), db.ForeignKey('messages.id'), primary_key=True),
                              db.Column('user_id', db.Integer(), db.ForeignKey('users.id'), primary_key=True)
                              )


# GO-LIVE CONFIRMATIONS FROM FACULTY

golive_confirmation = db.Table('go_live_confirmation',
                               db.Column('faculty_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                               db.Column('pclass_config_id', db.Integer(), db.ForeignKey('project_class_config.id'), primary_key=True)
                               )


# PROJECT ASSOCIATIONS (NOT LIVE)


# association table giving association between projects and project classes
project_classes = db.Table('project_to_classes',
                           db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                           db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True)
                           )

# association table giving association between projects and transferable skills
project_skills = db.Table('project_to_skills',
                          db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                          db.Column('skill_id', db.Integer(), db.ForeignKey('transferable_skills.id'), primary_key=True)
                          )

# association table giving association between projects and degree programmes
project_programmes = db.Table('project_to_programmes',
                              db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                              db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True)
                              )

# association table giving association between projects and supervision tram
project_supervision = db.Table('project_to_supervision',
                               db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                               db.Column('supervisor.id', db.Integer(), db.ForeignKey('supervision_team.id'), primary_key=True)
                               )


# PROJECT ASSOCIATIONS (LIVE)


# association table giving association between projects and project classes
live_project_classes = db.Table('live_project_to_classes',
                                db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True)
                                )

# association table giving association between projects and transferable skills
live_project_skills = db.Table('live_project_to_skills',
                               db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                               db.Column('skill_id', db.Integer(), db.ForeignKey('transferable_skills.id'), primary_key=True)
                               )

# association table giving association between projects and degree programmes
live_project_programmes = db.Table('live_project_to_programmes',
                                   db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                   db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True)
                                   )

# association table giving association between projects and supervision tram
live_project_supervision = db.Table('live_project_to_supervision',
                                    db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                    db.Column('supervisor.id', db.Integer(), db.ForeignKey('supervision_team.id'), primary_key=True)
                                    )


# LIVE STUDENT ASSOCIATIONS

# association table: faculty confirmation requests
confirmation_requests = db.Table('confirmation_requests',
                                 db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                 db.Column('student_id', db.Integer(), db.ForeignKey('selecting_students.id'), primary_key=True)
                                 )

# association table: faculty confirmed meetings
faculty_confirmations = db.Table('faculty_confirmations',
                                 db.Column('project_id', db.Integer(), db.ForeignKey('live_projects.id'), primary_key=True),
                                 db.Column('student_id', db.Integer(), db.ForeignKey('selecting_students.id'), primary_key=True)
                                 )


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
    def build_name(self):

        prefix = ''

        if self.faculty_data is not None and self.faculty_data.use_academic_title:

            for key, value in academic_titles:

                if key == self.faculty_data.academic_title:

                    prefix = value + ' '
                    break

        return prefix + self.first_name + ' ' + self.last_name


    def build_name_and_username(self):

        return self.build_name() + ' (' + self.username + ')'


    def add_convenorship(self, pclass):
        """
        Set up this user (assumed to be linked to a FacultyData record) for the convenorship
        of the given project class. Currently empty.
        :param pclass:
        :return:
        """

        flash('Installed {name} as convenor of {title}'.format(name=self.build_name(), title=pclass.name))


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

        flash('Removed {name} as convenor of {title}'.format(name=self.build_name(), title=pclass.name))


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

    # project class enrollments for this faculty member
    enrollments = db.relationship('ProjectClass', secondary=faculty_enrollments, lazy='dynamic',
                                  backref=db.backref('enrolled_faculty', lazy='dynamic'))

    # academic title (Prof, Dr)
    academic_title = db.Column(db.Integer())

    # use academic title?
    use_academic_title = db.Column(db.Boolean())

    # does this faculty want to sign off on students before they can apply?
    sign_off_students = db.Column(db.Boolean())

    # office
    office = db.Column(db.String(DEFAULT_STRING_LENGTH))

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


    def projects_unofferable(self):

        unofferable = 0
        for proj in self.user.projects:
            if proj.active and not proj.offerable:
                unofferable += 1

        return unofferable


    def remove_affiliation(self, group):
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


    def add_affiliation(self, group):
        """
        Add an affiliation to this faculty member
        :param group:
        :return:
        """

        self.affiliations.append(group)


    def remove_enrollment(self, pclass):
        """
        Remove an enrollment from a faculty member
        :param pclass:
        :return:
        """

        self.enrollments.remove(pclass)

        # remove this project class from any projects owned by this faculty member
        ps = Project.query.filter(Project.owner_id==self.id, Project.project_classes.any(id=pclass.id))

        for proj in ps.all():
            proj.remove_project_class(pclass)


    def add_enrollment(self, pclass):
        """
        Add an enrollment to this faculty member
        :param pclass:
        :return:
        """

        self.enrollments.append(pclass)


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


class TransferableSkill(db.Model):
    """
    Model a transferable skill
    """

    # make table name plural
    __tablename__ = "transferable_skills"

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

    # which year does this project class run for?
    year = db.Column(db.Integer(), index=True)

    # how many years does the project extend? usually 1, but RP is more
    extent = db.Column(db.Integer())

    # explicitly ask supervisors to confirm projects each year?
    require_confirm = db.Column(db.Boolean())

    # carry over supervisor in subsequent years?
    supervisor_carryover = db.Column(db.Boolean())

    # how many submissions per year does this project have?
    submissions = db.Column(db.Integer())

    # how many initial_choices should students make?
    initial_choices = db.Column(db.Integer())

    # how many switch choices should students be allowed?
    switch_choices = db.Column(db.Integer())

    # is project selection open to all students?
    selection_open_to_all = db.Column(db.Boolean())

    # project convenor; must be a faculty member, so might be pereferable to link to faculty_data table,
    # but to generate eg. tables we will need to extract usernames and emails
    # For that purpose, it's better to link to the User table directly
    convenor_id = db.Column(db.Integer(), db.ForeignKey('users.id'), index=True)
    convenor = db.relationship('User', foreign_keys=[convenor_id],
                               backref=db.backref('convenor_for', lazy='dynamic'))

    # associate this project class with a set of degree programmes
    programmes = db.relationship('DegreeProgramme', secondary=pclass_programme_associations, lazy='dynamic',
                                 backref=db.backref('project_classes', lazy='dynamic'))

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

    # who created this record, ie. initiated the rollover of the academic year?
    creator_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    created_by = db.relationship('User', uselist=False, foreign_keys=[creator_id])

    # creation timestamp
    creation_timestamp = db.Column(db.DateTime())


    # SELECTION MANAGEMENT

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
    closed = db.Column(db.Boolean())

    # who signed-off on close event?
    closed_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    closed_by = db.relationship('User', uselist=False, foreign_keys=[closed_id])

    # closed timestamp
    closed_timestamp = db.Column(db.DateTime())

    # capture which faculty have still to sign-off on this configuration
    golive_required = db.relationship('FacultyData', secondary=golive_confirmation, lazy='dynamic',
                                      backref=db.backref('live', lazy='dynamic'))

    # SUBMISSION MANAGEMENT

    # submission period
    submission_period = db.Column(db.Integer())


    @property
    def open(self):

        return self.live and not self.closed


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

        str = '{days} day'.format(days=days)

        if days != 1:
            str += 's'

        return str


    @property
    def count_valid_students(self):

        total_students = self.selecting_students.count()

        count = 0
        for student in self.selecting_students:
            if student.is_valid_selection:
                count += 1

        return count, total_students


    def generate_golive_requests(self):
        """
        Generate sign-off requests to all active faculty
        :return:
        """

        # exit if called in error
        if not self.project_class.require_confirm:
            return

        active_faculty = FacultyData.query.join(User).filter(User.active)

        for member in active_faculty:

            if member not in self.golive_required:      # don't object if we are generating a duplicate request

                self.golive_required.append(member)


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

    id = db.Column(db.Integer(), primary_key=True)

    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)
    active = db.Column(db.Boolean())

    # free keywords describing scientific area
    keywords = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # which faculty member owns this project?
    owner_id = db.Column(db.Integer(), db.ForeignKey('users.id'), index=True)
    owner = db.relationship('User', foreign_keys=[owner_id], backref=db.backref('projects', lazy='dynamic'))

    # which research group is associated with this project?
    group_id = db.Column(db.Integer(), db.ForeignKey('research_groups.id'), index=True)
    group = db.relationship('ResearchGroup', backref=db.backref('projects', lazy='dynamic'))

    # which project class are associated with this project?
    project_classes = db.relationship('ProjectClass', secondary=project_classes, lazy='dynamic',
                                      backref=db.backref('projects', lazy='dynamic'))

    # which transferable skills are associated with this project?
    skills = db.relationship('TransferableSkill', secondary=project_skills, lazy='dynamic',
                             backref=db.backref('projects', lazy='dynamic'))

    # which degree programmes are associated with this project?
    programmes = db.relationship('DegreeProgramme', secondary=project_programmes, lazy='dynamic',
                                 backref=db.backref('projects', lazy='dynamic'))

    # is a meeting required before selecting this project?
    MEETING_REQUIRED = 1
    MEETING_OPTIONAL = 2
    MEETING_NONE = 3
    meeting_reqd = db.Column(db.Integer())

    # maximum number of students
    capacity = db.Column(db.Integer())

    # impose limitation on capacity
    enforce_capacity = db.Column(db.Boolean())

    # supervisory roles
    team = db.relationship('Supervisor', secondary=project_supervision, lazy='dynamic',
                           backref=db.backref('projects', lazy='dynamic'))

    # project description
    description = db.Column(db.String(DESCRIPTION_STRING_LENGTH))

    # recommended reading
    reading = db.Column(db.String(DESCRIPTION_STRING_LENGTH))

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

        return True


    def add_skill(self, skill):

        self.skills.append(skill)


    def remove_skill(self, skill):

        self.skills.remove(skill)


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

    # definitive project number in this year
    number = db.Column(db.Integer())

    # project name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True)

    # free keywords describing scientific area
    keywords = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # which faculty member owns this project?
    owner_id = db.Column(db.Integer(), db.ForeignKey('users.id'), index=True)
    owner = db.relationship('User', foreign_keys=[owner_id],
                            backref=db.backref('live_projects', lazy='dynamic'))

    # which research group is associated with this project?
    group_id = db.Column(db.Integer(), db.ForeignKey('research_groups.id'), index=True)
    group = db.relationship('ResearchGroup', backref=db.backref('live_projects', lazy='dynamic'))

    # which transferable skills are associated with this project?
    skills = db.relationship('TransferableSkill', secondary=live_project_skills, lazy='dynamic',
                             backref=db.backref('live_projects', lazy='dynamic'))

    # which degree programmes are associated with this project?
    programmes = db.relationship('DegreeProgramme', secondary=live_project_programmes, lazy='dynamic',
                                 backref=db.backref('live_projects', lazy='dynamic'))

    # maximum number of students
    capacity = db.Column(db.Integer())

    # impose limitation on capacity
    enforce_capacity = db.Column(db.Boolean())

    # is a meeting required before selecting this project?
    MEETING_REQUIRED = 1
    MEETING_OPTIONAL = 2
    MEETING_NONE = 3
    meeting_reqd = db.Column(db.Integer())

    team = db.relationship('Supervisor', secondary=live_project_supervision, lazy='dynamic',
                           backref=db.backref('live_projects', lazy='dynamic'))

    # project description
    description = db.Column(db.String(DESCRIPTION_STRING_LENGTH))

    # recommended reading
    reading = db.Column(db.String(DESCRIPTION_STRING_LENGTH))


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

        # otherwise, check is sel is in list of confirmed students
        if sel in self.confirmed_students:

            return True

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
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    user = db.relationship('User', foreign_keys=[user_id], uselist=False,
                           backref=db.backref('selecting', lazy='dynamic'))

    # confirmation requests issued
    confirm_requests = db.relationship('LiveProject', secondary=confirmation_requests, lazy='dynamic',
                                       backref=db.backref('confirm_waiting', lazy='dynamic'))

    # confirmation requests granted
    confirmed = db.relationship('LiveProject', secondary=faculty_confirmations, lazy='dynamic',
                                backref=db.backref('confirmed_students', lazy='dynamic'))


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
    def get_academic_year(self):
        """
        Compute the current academic year for this student, relative this ProjectClassConfig
        :return:
        """

        return self.config.year - self.user.student_data.cohort + 1


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
        Determine whether this selection is optional
        :return:
        """

        return self.user.student_data.programme in self.config.project_class.programmes


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

            count +=1
            if count >= num_choices:
                break

        return True


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
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    user = db.relationship('User', foreign_keys=[user_id], uselist=False,
                           backref=db.backref('submitting', lazy='dynamic'))


    @property
    def get_academic_year(self):
        """
        Compute the current academic year for this student, relative this ProjectClassConfig
        :return:
        """

        return self.config.year - self.user.student_data.cohort + 1


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
    user = db.relationship('SelectingStudent', uselist=False,
                           backref=db.backref('bookmarks', lazy='dynamic', cascade='all, delete-orphan'))

    # LiveProject we are linking to
    liveproject_id = db.Column(db.Integer(), db.ForeignKey('live_projects.id'))
    liveproject = db.relationship('LiveProject', uselist=False,
                                  backref=db.backref('bookmarks', lazy='dynamic'))

    # rank in owner's list
    rank = db.Column(db.Integer())


class EmailLog(db.Model):
    """
    Model a logged email
    """

    __tablename__ = "email_log"


    # unique id for this record
    id = db.Column(db.Integer(), primary_key=True)

    # id of owning user
    user_id = db.Column(db.Integer(), db.ForeignKey('users.id'))
    user = db.relationship('User', uselist=False,
                           backref=db.backref('emails', lazy='dynamic'))

    # date of sending attempt
    send_date = db.Column(db.DateTime(), index=True)

    # subject
    subject = db.Column(db.String(DEFAULT_STRING_LENGTH))

    # message body (text)
    body = db.Column(db.String(DESCRIPTION_STRING_LENGTH))

    # message body (HTML)
    html = db.Column(db.String(DESCRIPTION_STRING_LENGTH))


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

    # data of issue
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
    body = db.Column(db.String(DESCRIPTION_STRING_LENGTH))

    # associate with which projects?
    project_classes = db.relationship('ProjectClass', secondary=pclass_message_associations, lazy='dynamic',
                                      backref=db.backref('messages', lazy='dynamic'))

    # which users have dismissed this message already?
    dismissed_by = db.relationship('User', secondary=message_dismissals, lazy='dynamic')
