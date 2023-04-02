#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import re
from datetime import timedelta, datetime
from email.utils import parseaddr

from app import create_app, db
from app.models import PresentationAssessment, \
    AssessorAttendanceData, SubmitterAttendanceData, ScheduleAttempt, StudentData, User, ProjectClass, \
    SelectingStudent, ProjectDescription, Project, WorkflowMixin, EnrollmentRecord, StudentDataWorkflowHistory, \
    ProjectDescriptionWorkflowHistory, MainConfig, AssetLicense, EmailLog, ProjectTag, LiveProject, SubmissionRecord, \
    SubmissionRole, PresentationFeedback, MatchingRecord, MatchingRole, FacultyData
from app.shared.sqlalchemy import get_count


def migrate_availability_data():
    """
    Migrate old-style attendance data (for PresentationAssessment/PresentationSession) to new style,
    with individual records for each attendee
    :return:
    """
    assessments = db.session.query(PresentationAssessment).all()

    for assessment in assessments:
        for assessor in assessment.assessors.all():
            new_record = AssessorAttendanceData(faculty_id=assessor.id,
                                                assessment_id=assessment.id,
                                                comment=None)

            for session in assessment.sessions.all():
                if session.faculty_available(assessor.id):
                    new_record.available.append(session)
                else:
                    new_record.unavailable.append(session)

            db.session.add(new_record)

        for submitter in assessment.submitters.all():
            new_record = SubmitterAttendanceData(submitter_id=submitter.id,
                                                 assessment_id=assessment.id,
                                                 attending=not assessment.not_attending(submitter.id))

            for session in assessment.sessions.all():
                if session.submitter_available(submitter.id):
                    new_record.available.append(session)
                else:
                    new_record.unavailable.append(session)

            db.session.add(new_record)

    db.session.commit()


def migrate_confirmation_data():
    """
    Migrate old-style confirmation data for PresentationAssessment (held in a separate association table)
    to new-style (held as part of the AssessorAttendanceData record)
    :return:
    """
    assessments = db.session.query(PresentationAssessment).all()

    for assessment in assessments:
        for record in assessment.assessor_list:
            if record.faculty in assessment.availability_outstanding:
                record.confirmed = False
                record.confirmed_timestamp = None
            else:
                record.confirmed = True
                record.confirmed_timestamp = None

    db.session.commit()


def populate_student_validation_data():
    """
    Populate validation state in StudentData table
    :return:
    """
    students = db.session.query(StudentData).all()

    for student in students:
        if student.workflow_state is None:
            student.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
            student.validator_id = None
            student.validated_timestamp = None

    db.session.commit()


def populate_project_validation_data():
    """
    Populate validation state in Projects table
    :return:
    """
    descriptions = db.session.query(ProjectDescription).all()

    for desc in descriptions:
        if desc.workflow_state is None:
            desc.workflow_state = WorkflowMixin.WORKFLOW_APPROVAL_QUEUED
            desc.validator_id = None
            desc.validated_timestamp = None

    db.session.commit()


def populate_email_options():
    users = db.session.query(User).all()

    for user in users:
        user.group_summaries = True
        user.summary_frequency = 1

    db.session.commit()


def populate_schedule_tags():
    schedules = db.session.query(ScheduleAttempt).all()

    for s in schedules:
        if s.tag is None:
            s.tag = 'schedule_{n}'.format(n=s.id)

    db.session.commit()


def populate_new_fields():
    pclasses = db.session.query(ProjectClass).all()

    for pcl in pclasses:
        if pcl.auto_enroll_years is None:
            pcl.auto_enroll_years = ProjectClass.AUTO_ENROLL_FIRST_YEAR

    selectors = db.session.query(SelectingStudent).all()
    for sel in selectors:
        if sel.convert_to_submitter is None:
            sel.convert_to_submitter = True

    db.session.commit()


def attach_JRA_projects():
    rp_pclass = db.session.query(ProjectClass).filter_by(id=2).one()
    JRA_pclass = db.session.query(ProjectClass).filter_by(id=6).one()

    projects = db.session.query(Project).all()
    for p in projects:
        if rp_pclass in p.project_classes:
            if JRA_pclass not in p.project_classes:
                p.project_classes.append(JRA_pclass)

    db.session.flush()

    descriptions = db.session.query(ProjectDescription).all()
    for d in descriptions:
        if rp_pclass in d.project_classes:
            if JRA_pclass not in d.project_classes:
                d.project_classes.append(JRA_pclass)

    db.session.commit()


def migrate_description_confirmations():
    descriptions = db.session.query(ProjectDescription).all()

    for d in descriptions:
        project = d.parent
        owner = project.owner

        # assume not confirmed unless evidence to contrary
        d.confirmed = False

        # if project is not active, this description is not confirmed
        if not project.active:
            continue

        for p in d.project_classes:
            # if project class doesn't use confirmations, move on
            if not p.require_confirm:
                continue

            record = owner.get_enrollment_record(p)

            # if supervisor not normally enrolled, this pclass changes nothing
            if record.supervisor_state != EnrollmentRecord.SUPERVISOR_ENROLLED:
                continue

            # any description with a nontrivial workflow state is automatically assumed to be confirmed
            if d.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED or \
                    d.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED:
                d.confirmed = True
                break

            # otherwise, check whether user is in confirmations_required list
            config = p.most_recent_config

            if config is None:
                continue

            if owner not in config.confirmation_required:
                d.confirmed = True
                break

    db.session.commit()


def populate_workflow_history():
    rec = db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()
    current_year = rec.year

    shistory = db.session.query(StudentDataWorkflowHistory).all()

    for item in shistory:
        if item.year is None:
            item.year = current_year

    phistory = db.session.query(ProjectDescriptionWorkflowHistory).all()

    for item in phistory:
        if item.year is None:
            item.year = current_year

    db.session.commit()


def populate_default_licenses(app):
    users = db.session.query(User).all()

    faculty_lic = app.config['FACULTY_DEFAULT_LICENSE']
    student_lic = app.config['STUDENT_DEFAULT_LICENSE']
    office_lic = app.config['OFFICE_DEFAULT_LICENSE']

    if faculty_lic is None:
        print('!! Default faculty license is unset')
    else:
        print('== Default faculty license is "{name}"'.format(name=faculty_lic))

    if student_lic is None:
        print('!! Default student license is unset')
    else:
        print('== Default student license is "{name}"'.format(name=student_lic))

    if office_lic is None:
        print('!! Default office license is unset')
    else:
        print('== Default office license is "{name}"'.format(name=office_lic))

    faculty_default = db.session.query(AssetLicense) \
        .filter_by(abbreviation=faculty_lic).first()
    student_default = db.session.query(AssetLicense) \
        .filter_by(abbreviation=student_lic).first()
    office_default = db.session.query(AssetLicense) \
        .filter_by(abbreviation=office_lic).first()

    for user in users:
        if user.default_license is None:
            if user.has_role('faculty'):
                user.default_license = faculty_default
                if faculty_default is not None:
                    print('== Set faculty user "{name}" to have default license '
                          '"{lic}"'.format(name=user.name, lic=faculty_default.name))
                else:
                    print('!! Set faculty user "{name}" to have unset default '
                          'license'.format(name=user.name))
            elif user.has_role('student'):
                user.default_license = student_default
                if student_default is not None:
                    print('== Set student user "{name}" to have default license '
                          '"{lic}"'.format(name=user.name, lic=student_default.name))
                else:
                    print('!! Set student user "{name}" to have unset default '
                          'license'.format(name=user.name))
            elif user.has_role('office'):
                user.default_license = office_default
                if office_default is not None:
                    print('== Set office user "{name}" to have default license '
                          '"{lic}"'.format(name=user.name, lic=office_default.name))
                else:
                    print('!! Set office user "{name}" to have unset default '
                          'license'.format(name=user.name))
            else:
                print('!! Did not set default license for user "{name}"'.format(name=user.name))

    db.session.commit()


def migrate_lifetime_data(AssetRecord):
    records = db.session.query(AssetRecord).all()

    for record in records:
        if record.lifetime is None or record.timestamp is None:
            record.expiry = None
        else:
            record.expiry = record.lifetime + timedelta(seconds=record.lifetime)

    db.session.commit()


# used to fix any issues with User models having null passwords before switch to make password field not nullable
def fix_null_passwords():
    users = db.session.query(User).all()

    from flask_security import hash_password
    from app.manage_users.actions import _randompassword

    for user in users:
        if user.password is None:
            user.password = hash_password(_randompassword())

    db.session.commit()


# migrate exam numbers to temporary field
def migrate_temporary_exam_numbers():
    students = db.session.query(StudentData).all()

    for s in students:
        s.exam_number_temp = s.exam_number

    db.session.commit()


# migrate exam numbers back from temporary field to main (encrypted) field
def migrate_exam_numbers_back():
    students = db.session.query(StudentData).all()

    for s in students:
        s.exam_number = s.exam_number_temp

    db.session.commit()


# migrate email recipients from old-style (allows only a single recipient) to new style (allows list of recipients)
def migrate_email_recipients():
    emails = db.session.query(EmailLog).all()

    for email in emails:
        email: EmailLog
        email.recipients = []

        subject = email.subject
        if subject is None:
            subject = ""

        if len(subject) > 35:
            subject = subject[:35] + '...'
        print('** Email, subject "{subj}"'.format(subj=subject))

        if email.user is not None:
            email.recipients.append(email.user)
            print('**  added single recipient "{usr}"'.format(usr=email.user.name))

        elif email.recipient is not None:
            recipient_string = str(email.recipient)
            print('**  has recipient string "{str}"'.format(str=recipient_string))
            addrs = [x.strip() for x in recipient_string.split(',') if len(x) > 0]

            for addr in addrs:
                pair = parseaddr(addr)
                user = User.query.filter_by(email=pair[1]).first()

                if user is not None:
                    email.recipients.append(user)
                    print('**  added multiple recipient "{usr}"'.format(usr=user.name))

    db.session.commit()


def migrate_project_tags():
    projects = db.session.query(Project).all()

    for p in projects:
        p: Project

        keywords = p.keywords
        if keywords is not None:
            keywords = [kw.strip() for kw in re.split("[;,]", keywords)]
            keywords = [w for w in keywords if len(w) > 0]

            for kw in keywords:
                tag = db.session.query(ProjectTag).filter_by(name=kw).first()

                if tag is not None:
                    if tag not in p.tags:
                        p.add_tag(tag)
                else:
                    tag = ProjectTag(name=kw,
                                     colour=None,
                                     creator_id=p.owner.user.id,
                                     creation_timestamp=datetime.now())
                    db.session.add(tag)
                    db.session.flush()
                    p.add_tag(tag)

    db.session.commit()


def migrate_liveproject_tags():
    projects = db.session.query(LiveProject).all()

    for p in projects:
        p: LiveProject

        keywords = p.keywords
        if keywords is not None:
            keywords = [kw.strip() for kw in re.split("[;,]", keywords)]
            keywords = [w for w in keywords if len(w) > 0]

            for kw in keywords:
                tag = db.session.query(ProjectTag).filter_by(name=kw).first()

                if tag is not None:
                    if tag not in p.tags:
                        p.tags.append(tag)
                else:
                    print('Did not find tag "{tag}" for LiveProject "{name}" id={pid}'.format(tag=kw, name=p.name, pid=p.id))

    db.session.commit()


def migrate_submission_roles():
    records = db.session.query(SubmissionRecord).all()

    for r in records:
        r: SubmissionRecord

        if r.project is not None and r.project.owner is not None:
            sr = r.roles.filter(SubmissionRole.role == SubmissionRole.ROLE_SUPERVISOR,
                                SubmissionRole.user_id == r.project.owner_id).first()
            if sr is None:
                # have not yet migrated supervisor
                sr = SubmissionRole(submission_id=r.id,
                                    user_id=r.project.owner_id,
                                    role=SubmissionRole.ROLE_SUPERVISOR,
                                    marking_email=r.email_to_supervisor,
                                    positive_feedback=r.supervisor_positive,
                                    improvements_feedback=r.supervisor_negative,
                                    submitted_feedback=r.supervisor_submitted,
                                    feedback_timestamp=r.supervisor_timestamp,
                                    acknowledge_student=r.acknowledge_feedback,
                                    response=r.faculty_response,
                                    submitted_response=r.faculty_response_submitted,
                                    response_timestamp=r.faculty_response_timestamp)
                db.session.add(sr)
                db.session.flush()

        if r.marker is not None:
            mr = r.roles.filter(SubmissionRole.role == SubmissionRole.ROLE_MARKER,
                                SubmissionRole.user_id == r.marker_id).first()
            if mr is None:
                # have not yet migrated marker
                mr = SubmissionRole(submission_id=r.id,
                                    user_id=r.marker_id,
                                    role=SubmissionRole.ROLE_MARKER,
                                    marking_email=r.email_to_marker,
                                    positive_feedback=r.marker_positive,
                                    improvements_feedback=r.marker_negative,
                                    submitted_feedback=r.marker_submitted,
                                    feedback_timestamp=r.marker_timestamp,
                                    acknowledge_student=None,
                                    response=None,
                                    submitted_response=None,
                                    response_timestamp=None)
                db.session.add(mr)
                db.session.flush()

        for pf in r.presentation_feedback:
            pf: PresentationFeedback

            pr = r.roles.filter(SubmissionRole.role == SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
                                SubmissionRole.user_id == pf.assessor_id).first()

            if pr is None:
                # have not yet migrated this presentation assessor item
                pr = SubmissionRole(submission_id=r.id,
                                    user_id=pf.assessor_id,
                                    role=SubmissionRole.ROLE_PRESENTATION_ASSESSOR,
                                    marking_email=None,
                                    positive_feedback=pf.positive,
                                    improvements_feedback=pf.negative,
                                    submitted_feedback=pf.submitted,
                                    feedback_timestamp=pf.timestamp,
                                    acknowledge_student=None,
                                    response=None,
                                    submitted_response=None,
                                    response_timestamp=None)
                db.session.add(pr)
                db.session.flush()

    db.session.commit()


def migrate_matching_roles():
    records = db.session.query(MatchingRecord).all()

    for r in records:
        r: MatchingRecord

        if r.project is not None and r.project.owner is not None:
            mr = r.roles.filter(MatchingRole.role == MatchingRole.ROLE_SUPERVISOR,
                                MatchingRole.user_id == r.project.owner_id).first()
            if mr is None:
                # have not yet migrated finally assigned supervisor
                mr = MatchingRole(user_id=r.project.owner_id,
                                  role=MatchingRole.ROLE_SUPERVISOR)
                r.roles.append(mr)
                db.session.flush()

        if r.original_project_id is not None:
            op = db.session.query(LiveProject).filter_by(id=r.original_project_id).first()

            if op is not None and op.owner is not None:
                mr = r.original_roles.filter(MatchingRole.role == MatchingRole.ROLE_SUPERVISOR,
                                             MatchingRole.user_id == op.owner_id).first()
                if mr is None:
                    # have not yet migrated originally assigned supervisor
                    mr = MatchingRole(user_id=op.owner_id,
                                      role=MatchingRole.ROLE_SUPERVISOR)
                    r.original_roles.append(mr)
                    db.session.flush()

        if r.marker is not None:
            mr = r.roles.filter(MatchingRole.role == MatchingRole.ROLE_MARKER,
                                MatchingRole.user_id == r.marker_id).first()
            if mr is None:
                # have not yet migrated finally assigned marker
                mr = MatchingRole(user_id=r.marker_id,
                                  role=MatchingRole.ROLE_MARKER)
                r.roles.append(mr)
                db.session.flush()

        if r.original_marker_id is not None:
            om = db.session.query(FacultyData).filter_by(id=r.original_marker_id).first()

            if om is not None:
                mr = r.original_roles.filter(MatchingRole.role == MatchingRole.ROLE_MARKER,
                                             MatchingRole.user_id == om.id).first()
                if mr is None:
                    # have not yet migrated originally assigned marker
                    mr = MatchingRole(user_id=om.id,
                                      role=MatchingRole.ROLE_MARKER)
                    r.original_roles.append(mr)
                    db.session.flush()

    db.session.commit()


def _write_supervisor_pool_data(items):
    for item in items:
        names = []
        if get_count(item.tags.filter_by(id=535)):
            # computer sciences
            names += ['Mitchell', 'Barrett', 'Roseboom', 'Sherman', 'Weeds', 'Weir', 'Olugbade',
                      'Simpson', 'Evans', 'Ashby', 'Raman', 'Rosas De Andraca', 'Romer', 'Shaw', 'Loveday',
                      'Iliev', 'Lewis', 'Salvatore']

        if get_count(item.tags.filter_by(id=536)):
            # life sciences
            pass

        if get_count(item.tags.filter_by(id=537)):
            # mathematics
            names += ['Blyuss', 'Cagnetti', 'Dahlqvist', 'Dashti', 'Koch', 'Koumatos', 'Scalas']

        if get_count(item.tags.filter_by(id=538)):
            # physics & astronomy
            names += ['Romer', 'Shaw', 'Loveday', 'Iliev', 'Lewis', 'Salvatore']

        for name in names:
            obj = db.session.query(User) \
                    .join(FacultyData, FacultyData.id == User.id) \
                    .filter(User.last_name == name,
                            User.roles.any(id=3)).one()

            if obj is not None and obj.faculty_data is not None:
                fd: FacultyData = obj.faculty_data
                if fd not in item.supervisors:
                    item.supervisors.append(fd)
            else:
                print('Failed to append FacultyData object for supervisor "{name}"'.format(name=name))


def add_supervisor_pool_data():
    ps = db.session.query(Project).filter(Project.generic == True).all()
    _write_supervisor_pool_data(ps)

    lps = db.session.query(LiveProject).filter(LiveProject.generic == True).all()
    _write_supervisor_pool_data(lps)

    db.session.commit()

app = create_app()

# with app.app_context():
    # migrate_availability_data()
    # migrate_confirmation_data()
    # populate_email_options()
    # populate_schedule_tags()
    # populate_new_fields()
    # attach_JRA_projects()
    # populate_student_validation_data()
    # populate_project_validation_data()
    # migrate_description_confirmations()
    # populate_workflow_history()
    # populate_default_licenses(app)
    # migrate_lifetime_data(GeneratedAsset)
    # migrate_lifetime_data(TemporaryAsset)
    # migrate_lifetime_data(SubmittedAsset)
    # fix_null_passwords()
    # migrate_temporary_exam_numbers()
    # migrate_exam_numbers_back()
    # migrate_email_recipients()
    # migrate_project_tags()
    # migrate_liveproject_tags()
    # migrate_submission_roles()
    # migrate_matching_roles()
    # add_supervisor_pool_data()

# pass control to application entry point if we are the controlling script
if __name__ == '__main__':

    app.run()
