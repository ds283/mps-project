#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security import UserMixin, RoleMixin
from flask_sqlalchemy import SQLAlchemy

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


# auxiliary table holding mapping from roles to users
roles_to_users = db.Table('roles_users',
                          db.Column('user_id', db.Integer(), db.ForeignKey('users.id'), primary_key=True),
                          db.Column('role_id', db.Integer(), db.ForeignKey('roles.id'), primary_key=True)
                          )

# auxiliary table giving faculty research group affiliations
faculty_affiliations = db.Table('faculty_affiliations',
                                db.Column('user_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                                db.Column('group_id', db.Integer(), db.ForeignKey('research_groups.id'), primary_key=True)
                                )

# auxiliary table giving faculty enrollment on project classes
faculty_enrollments = db.Table('faculty_enrollments',
                               db.Column('user_id', db.Integer(), db.ForeignKey('faculty_data.id'), primary_key=True),
                               db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True)
                               )

# auxiliary table giving association between project classes and degree programmes
project_class_associations = db.Table('project_class_to_programmes',
                                      db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True),
                                      db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True)
                                      )

# auxiliary table giving association between projects and project classes
project_classes = db.Table('project_to_classes',
                           db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                           db.Column('project_class_id', db.Integer(), db.ForeignKey('project_classes.id'), primary_key=True)
                           )

# auxiliary table giving association between projects and transferable skills
project_skills = db.Table('project_to_skills',
                          db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                          db.Column('skill_id', db.Integer(), db.ForeignKey('transferable_skills.id'), primary_key=True)
                          )

# auxiliary table giving association between projects and degree programmes
project_programmes = db.Table('project_to_programmes',
                              db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                              db.Column('programme_id', db.Integer(), db.ForeignKey('degree_programmes.id'), primary_key=True)
                              )

# auxiliary table giving association between projects and supervision tram
project_supervision = db.Table('project_to_supervision',
                               db.Column('project_id', db.Integer(), db.ForeignKey('projects.id'), primary_key=True),
                               db.Column('supervisor.id', db.Integer(), db.ForeignKey('supervision_team.id'), primary_key=True)
                               )

class MainConfig(db.Model):
    """
    Main application configuration table; generally, there should only
    be one row giving the current configuration
    """
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

        return ProjectClass.query.all()


class ResearchGroup(db.Model):
    """
    Model a row from the research group table
    """

    # make table name plural
    __tablename__ = 'research_groups'

    id = db.Column(db.Integer(), primary_key=True)

    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH), index=True, unique=True)
    name = db.Column(db.String(DEFAULT_STRING_LENGTH))

    active = db.Column(db.Boolean())


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

    # research group affiliations for this faculty member
    affiliations = db.relationship('ResearchGroup', secondary=faculty_affiliations, lazy='dynamic',
                                   backref=db.backref('faculty', lazy='dynamic'))

    # project class enrollments for this faculty member
    enrollments = db.relationship('ProjectClass', secondary=faculty_enrollments, lazy='dynamic',
                                  backref=db.backref('enrolled_faculty', lazy='dynamic'))

    # does this faculty want to sign off on students before they can apply?
    sign_off_students = db.Column(db.Boolean())


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

    exam_number = db.Column(db.Integer(), index=True, unique=True)
    cohort = db.Column(db.Integer(), index=True, unique=True)

    programme_id = db.Column(db.Integer, db.ForeignKey('degree_programmes.id'))
    programme = db.relationship('DegreeProgramme', backref=db.backref('students', lazy='dynamic'))


class DegreeType(db.Model):
    """
    Model a degree type
    """

    # make table name plural
    __tablename__ = 'degree_types'

    id = db.Column(db.Integer(), primary_key=True)

    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)
    active = db.Column(db.Boolean())


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

    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)
    abbreviation = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True, index=True)
    active = db.Column(db.Boolean())

    # which year does this project class run for?
    year = db.Column(db.Integer(), index=True)

    # how many submissions per year does this project have?
    submissions = db.Column(db.Integer())

    # project convenor; must be a faculty member, so might be pereferable to link to faculty_data table,
    # but to generate eg. tables we will need to extract usernames and emails
    # For that purpose, it's better to link to the User table directly
    convenor_id = db.Column(db.Integer(), db.ForeignKey('users.id'), index=True)
    convenor = db.relationship('User', backref=db.backref('convenor_for', lazy='dynamic'))

    # associate this project class with a set of degree programmes
    programmes = db.relationship('DegreeProgramme', secondary=project_class_associations, lazy='dynamic',
                                 backref=db.backref('project_classes', lazy='dynamic'))


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


class Supervisor(db.Model):
    """
    Model a supervision team member
    """

    # make table name plural
    __tablename__ = 'supervision_team'

    id = db.Column(db.Integer(), primary_key=True)

    name = db.Column(db.String(DEFAULT_STRING_LENGTH), unique=True)
    active = db.Column(db.Boolean())


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
    owner = db.relationship('User', backref=db.backref('projects', lazy='dynamic'))

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

    team = db.relationship('Supervisor', secondary=project_supervision, lazy='dynamic',
                           backref=db.backref('projects', lazy='dynamic'))

    # project description
    description = db.Column(db.String(DESCRIPTION_STRING_LENGTH))

    # recommended reading
    reading = db.Column(db.String(DESCRIPTION_STRING_LENGTH))


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

        available_programmes = self.available_degree_programmes()

        for prog in self.programmes:

            if available_programmes is None or prog not in available_programmes:
                self.remove_programme(prog)
