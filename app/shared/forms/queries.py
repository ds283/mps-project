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

from ...database import db
from ...models import User, DegreeType, DegreeProgramme, SkillGroup, FacultyData, ProjectClass, Role,\
    ResearchGroup, EnrollmentRecord, Supervisor, Project, ProjectDescription, project_classes, description_pclasses, \
    MatchingAttempt, SubmissionPeriodRecord, assessment_to_periods, PresentationAssessment, ProjectClassConfig, \
    Building, Room, PresentationFeedback, Module, FHEQ_Level, ScheduleSlot, PresentationSession, \
    ScheduleAttempt, SubmissionRecord

from ..utils import get_current_year


def GetActiveDegreeTypes():
    return DegreeType.query.filter_by(active=True).order_by(DegreeType.name.asc())


def GetActiveDegreeProgrammes():
    return DegreeProgramme.query.filter_by(active=True).order_by(DegreeProgramme.name.asc())


def GetActiveSkillGroups():
    return SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc())


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


def BuildPossibleOfficeContacts():
    return db.session.query(User) \
        .filter(User.active, User.roles.any(name='office')) \
        .order_by(User.last_name, User.first_name)


def BuildActiveFacultyName(fac):
    return fac.user.name


def BuildConvenorRealName(fac):
    return fac.user.name


def BuildOfficeContactName(user):
    return user.name


def GetAllProjectClasses():
    return ProjectClass.query.filter_by(active=True).order_by(ProjectClass.name.asc())


def GetConvenorProjectClasses():
    return ProjectClass.query.filter(ProjectClass.active, ProjectClass.convenor_id==current_user.id)


def GetSysadminUsers():
    return User.query.filter(User.active, User.roles.any(Role.name == 'root')) \
        .order_by(User.last_name, User.first_name)


def BuildSysadminUserName(user):
    return user.name_and_username


def CurrentUserResearchGroups():
    return ResearchGroup.query.filter(ResearchGroup.active, ResearchGroup.faculty.any(id=current_user.id)) \
        .order_by(ResearchGroup.name.asc())


def AllResearchGroups():
    return ResearchGroup.query.filter_by(active=True).order_by(ResearchGroup.name.asc())


def CurrentUserProjectClasses():
    # build list of enrollment records for the current user
    sq = EnrollmentRecord.query.filter_by(owner_id=current_user.id).subquery()

    # join to project class table
    return db.session.query(ProjectClass) \
        .filter_by(active=True, uses_supervisor=True) \
        .join(sq, sq.c.pclass_id == ProjectClass.id)


def AllProjectClasses():
    # don't require uses_supervisor=True because eg. MPhys Labs doesn't have this flag set,
    # but we still need to attach projects to it!
    return ProjectClass.query.filter_by(active=True).order_by(ProjectClass.name.asc())


def GetProjectClasses():
    return ProjectClass.query.filter_by(active=True).order_by(ProjectClass.name.asc())


def GetSupervisorRoles():
    return Supervisor.query.filter_by(active=True).order_by(Supervisor.name.asc())


def GetSkillGroups():
    return SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc())


def AvailableProjectDescriptionClasses(project_id, desc_id):
    # query for pclass identifiers available from project_id
    pclass_ids = db.session.query(project_classes.c.project_class_id) \
        .filter(project_classes.c.project_id == project_id).subquery()

    # query for pclass identifiers used by descriptions associated with project_id, except (possibly) for desc_id
    # if it is not None
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


def GetAutomatedMatchPClasses(year, base_id):
    pclasses = db.session.query(ProjectClass) \
        .filter(ProjectClass.active == True,
                ProjectClass.do_matching == True) \
        .join(ProjectClassConfig, ProjectClassConfig.pclass_id == ProjectClass.id) \
        .filter(ProjectClassConfig.year == year,
                ProjectClassConfig.live == True,
                ProjectClassConfig.selection_closed == True)

    if base_id is None:
        return pclasses

    base = db.session.query(MatchingAttempt).filter_by(id=base_id).one()
    c_members = base.config_members.subquery()
    p_members = db.session.query(ProjectClass) \
        .join(c_members, c_members.c.pclass_id == ProjectClass.id).subquery()

    pclasses = pclasses.join(p_members, p_members.c.id == ProjectClass.id, isouter=True) \
        .filter(p_members.c.id == None)

    return pclasses


def GetMatchingAttempts(year, base_id):
    attempts = db.session.query(MatchingAttempt) \
        .filter_by(year=year) \
        .order_by(MatchingAttempt.name.asc())

    if base_id is None:
        return attempts

    base = db.session.query(MatchingAttempt).filter_by(id=base_id).one()
    included = base.include_matches.subquery()

    attempts = attempts.join(included, included.c.id == MatchingAttempt.id, isouter=True) \
        .filter(included.c.id == None)

    return attempts


def GetComparatorMatches(year, self_id, pclasses, is_root):
    q = db.session.query(MatchingAttempt) \
        .filter(MatchingAttempt.year == year, MatchingAttempt.id != self_id)

    for pid in pclasses:
        q = q.filter(MatchingAttempt.config_members.any(pclass_id=pid))

    if not is_root:
        q = q.filter(MatchingAttempt.published == True)

    return q.order_by(MatchingAttempt.name.asc())


def GetComparatorSchedules(assessment_id, self_id, is_root):
    q = db.session.query(ScheduleAttempt) \
        .filter(ScheduleAttempt.owner_id == assessment_id,
                ScheduleAttempt.id != self_id)

    if not is_root:
        q = q.filter(ScheduleAttempt.published == True)

    return q.order_by(ScheduleAttempt.name.asc())


def MarkerQuery(live_project):
    if live_project is not None:
        return live_project.assessor_list_query

    return []


def BuildMarkerLabel(pclass_id, fac):
    pclass = db.session.query(ProjectClass).filter_by(id=pclass_id).one()
    CATS_supv, CATS_mark, CATS_pres = fac.CATS_assignment(pclass)
    return '{name} (CATS: {supv} supv, {mark} mark, {pres} pres, ' \
           '{tot} total)'.format(name=fac.user.name, supv=CATS_supv, mark=CATS_mark, pres=CATS_pres,
                                 tot=CATS_supv+CATS_mark)


def GetUnattachedSubmissionPeriods(assessment_id):
    # build list of submission periods for current year that have attached presentations.
    # we don't care whether they're closed or not; presentation assessment events are independent of that
    year = get_current_year()
    period_ids = db.session.query(SubmissionPeriodRecord.id) \
        .join(ProjectClassConfig, ProjectClassConfig.id == SubmissionPeriodRecord.config_id) \
        .filter(ProjectClassConfig.year == year,
                SubmissionPeriodRecord.has_presentation == True).subquery()

    # query for submission periods already attached to a PresentationAssessment, except (possibly) for
    # assessment_id (if it is not None)
    used_ids = db.session.query(assessment_to_periods.c.period_id) \
        .join(PresentationAssessment, PresentationAssessment.id == assessment_to_periods.c.assessment_id) \
        .filter(PresentationAssessment.year == year)

    if assessment_id is not None:
        used_ids = used_ids.filter(PresentationAssessment.id != assessment_id)

    used_ids = used_ids.distinct().subquery()

    # now query for unused periods
    unused_ids = db.session.query(period_ids.c.id) \
        .join(used_ids, used_ids.c.period_id == period_ids.c.id, isouter=True) \
        .filter(used_ids.c.period_id == None).subquery()

    # construct SubmissionPeriodRecord records for these ids
    return db.session.query(SubmissionPeriodRecord) \
        .join(unused_ids, SubmissionPeriodRecord.id == unused_ids.c.id)


def BuildSubmissionPeriodName(period):
    return period.display_name + ' (' + period.config.name + ')'


def GetAllBuildings():
    return db.session.query(Building).filter_by(active=True)


def GetAllRooms():
    return db.session.query(Room).filter_by(active=True) \
        .join(Building, Building.id == Room.building_id) \
        .order_by(Building.name.asc(),
                  Room.name.asc())


def BuildRoomLabel(room):
    return room.full_name + ' (capacity = {n})'.format(n=room.capacity)


def GetPresentationFeedbackFaculty(record_id):
    used_ids = db.session.query(PresentationFeedback.assessor_id) \
        .filter(PresentationFeedback.owner_id == record_id).distinct().subquery()

    return db.session.query(FacultyData) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active) \
        .join(used_ids, used_ids.c.assessor_id == FacultyData.id, isouter=True) \
        .filter(used_ids.c.assessor_id == None) \
        .order_by(User.last_name, User.first_name)


def GetPresentationAssessorFaculty(record_id, slot_id):
    used_ids = db.session.query(PresentationFeedback.assessor_id) \
        .filter(PresentationFeedback.owner_id == record_id).distinct().subquery()

    slot = db.session.query(ScheduleSlot).filter_by(id=slot_id).one()
    available_ids = slot.assessors.subquery()

    return db.session.query(FacultyData) \
        .join(available_ids, available_ids.c.id == FacultyData.id) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active) \
        .join(used_ids, used_ids.c.assessor_id == FacultyData.id, isouter=True) \
        .filter(used_ids.c.assessor_id == None) \
        .order_by(User.last_name, User.first_name)


def GetFHEQLevels():
    return db.session.query(FHEQ_Level).filter(FHEQ_Level.active).order_by(FHEQ_Level.academic_year.asc())


def BuildFHEQYearLabel(level):
    return 'Year {n}'.format(n=level.academic_year)


def ScheduleSessionQuery(schedule_id):
    sessions = db.session.query(ScheduleSlot.session_id) \
        .filter(ScheduleSlot.owner_id == schedule_id).distinct().subquery()

    return db.session.query(PresentationSession) \
        .join(sessions, sessions.c.session_id == PresentationSession.id) \
        .order_by(PresentationSession.date.asc(), PresentationSession.session_type.asc())


def BuildScheduleSessionLabel(session):
    return session.date_as_string + ' ' + session.session_type_string


def GetMaskableRoles(user_id):
    user = db.session.query(User).filter_by(id=user_id).one()

    return user.roles.filter(Role.name != 'faculty', Role.name != 'student', Role.name != 'office')


def GetDestinationProjects(user_id, project_id):
    return db.session.query(Project).filter(Project.owner_id == user_id,
                                            Project.id != project_id) \
        .order_by(Project.name.asc())


def GetDestinationProjectsPClass(user_id, project_id, pclass_id):
    return db.session.query(Project).filter(Project.owner_id == user_id,
                                            Project.id != project_id,
                                            Project.project_classes.any(id=pclass_id)) \
        .order_by(Project.name.asc())
