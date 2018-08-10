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
from app.models import DegreeType, DegreeProgramme, SkillGroup, FacultyData, ProjectClass, Role


def GetActiveDegreeTypes():

    return DegreeType.query.filter_by(active=True)


def GetActiveDegreeProgrammes():

    return DegreeProgramme.query.filter_by(active=True)


def GetActiveSkillGroups():

    return SkillGroup.query.filter_by(active=True)


def BuildDegreeProgrammeName(programme):

    return programme.full_name


def GetActiveFaculty():

    return db.session.query(User) \
            .filter(User.active) \
            .join(FacultyData, FacultyData.id == User.id) \
            .order_by(User.last_name, User.first_name)


def GetPossibleConvenors():

    return db.session.query(FacultyData) \
            .join(User, User.id == FacultyData.id) \
            .filter(User.active) \
            .order_by(User.last_name, User.first_name)


def BuildUserRealName(user):

    return user.name_and_username


def BuildConvenorRealName(facdata):

    return facdata.user.name_and_username


def GetAllProjectClasses():

    return ProjectClass.query.filter_by(active=True)


def GetConvenorProjectClasses():

    return ProjectClass.query.filter(ProjectClass.active, ProjectClass.convenor_id==current_user.id)


def GetSysadminUsers():

    return User.query.filter(User.active, User.roles.any(Role.name == 'root')).order_by(User.last_name, User.first_name)