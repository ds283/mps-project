#
# Created by David Seery on 01/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask_login import current_user

from app import db, User
from app.models import DegreeType, DegreeProgramme, SkillGroup, FacultyData, ProjectClass, Role, ResearchGroup, \
    EnrollmentRecord, Supervisor, Project, ProjectDescription, project_classes, description_pclasses, \
    MatchingAttempt


def GetActiveDegreeTypes():

    return DegreeType.query.filter_by(active=True)


def GetActiveDegreeProgrammes():

    return DegreeProgramme.query.filter_by(active=True)


def GetActiveSkillGroups():

    return SkillGroup.query.filter_by(active=True)


def BuildDegreeProgrammeName(programme):

    return programme.full_name


def GetActiveFaculty():

    return db.session.query(FacultyData) \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active) \
            .order_by(User.last_name, User.first_name)


def GetPossibleConvenors():

    return db.session.query(FacultyData) \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active) \
            .order_by(User.last_name, User.first_name)


def BuildActiveFacultyName(fac):

    return fac.user.name


def BuildConvenorRealName(fac):

    return fac.user.name


def GetAllProjectClasses():

    return ProjectClass.query.filter_by(active=True)


def GetConvenorProjectClasses():

    return ProjectClass.query.filter(ProjectClass.active, ProjectClass.convenor_id==current_user.id)


def GetSysadminUsers():

    return User.query.filter(User.active, User.roles.any(Role.name == 'root')) \
        .order_by(User.last_name, User.first_name)


def BuildSysadminUserName(user):

    return user.name_and_username


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


def AvailableProjectDescriptionClasses(project_id, desc_id):

    # query for pclass identifiers available from project_id
    pclass_ids = db.session.query(project_classes.c.project_class_id) \
        .filter(project_classes.c.project_id == project_id).subquery()

    # query for pclass identifiers used by descriptions associated with project_id, except (possibly) for desc_id
    used_ids = db.session.query(description_pclasses.c.project_class_id) \
        .join(ProjectDescription, ProjectDescription.id == description_pclasses.c.description_id) \
        .filter(ProjectDescription.parent_id == project_id)

    if desc_id is not None:
        used_ids = used_ids.filter(description_pclasses.c.description_id != desc_id)

    used_ids = used_ids.distinct().subquery()

    # query for unused pclass identifiers
    unused_ids = db.session.query(pclass_ids.c.project_class_id) \
        .join(used_ids, used_ids.c.project_class_id == pclass_ids.c.project_class_id, isouter=True) \
        .filter(used_ids.c.project_class_id == None).subquery()

    # construct ProjectClass records for these ids
    return db.session.query(ProjectClass) \
        .join(unused_ids, ProjectClass.id == unused_ids.c.project_class_id)


def ProjectDescriptionClasses(project_id):

    project = db.session.query(Project).filter_by(id=project_id).first()

    # if a default has been set, we can use any project class to which the main project is attached
    if project is not None and project.default is not None:
        return project.project_classes

    # otherwise, we can only use project classes for which descriptions are available

    # query for pclass identifiers used by descriptions associated with project_id
    used_ids = db.session.query(description_pclasses.c.project_class_id) \
        .join(ProjectDescription, ProjectDescription.id == description_pclasses.c.description_id) \
        .filter(ProjectDescription.parent_id == project_id).distinct().subquery()

    # construct ProjectClass records for these ids
    return db.session.query(ProjectClass) \
        .join(used_ids, ProjectClass.id == used_ids.c.project_class_id)


def GetAutomatedMatchPClasses():
    return db.session.query(ProjectClass).filter_by(active=True, do_matching=True)


def GetMatchingAttempts(year):
    return db.session.query(MatchingAttempt).filter_by(year=year).order_by(MatchingAttempt.name)
