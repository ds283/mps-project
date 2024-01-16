#
# Created by David Seery on 11/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import current_app

from ..shared.utils import get_current_year
from ..database import db
from ..models import Project, LiveProject, StudentData, SelectingStudent, SubmittingStudent, ProjectClassConfig, SubmissionRecord, ProjectDescription


def add_liveproject(number, project, config_id, desc=None, autocommit=False):
    # extract this project; input 'project' is allowed to be a Project instance, or else
    # the database id of an instance
    item: Project
    if isinstance(project, Project):
        item = project
    elif isinstance(project, int):
        item = Project.query.filter_by(id=project).first()
    else:
        raise RuntimeError("Cannot interpret project id parameter")

    if item is None:
        raise KeyError("Missing database record for Project id={id}".format(id=project))

    config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
    if config is None:
        raise KeyError("Missing database record for ProjectClassConfig id={id}".format(id=config_id))

    if desc is None:
        description: ProjectDescription = item.get_description(config.project_class)
        if description is None:
            raise KeyError("Missing description for Project id={id}, ProjectClass id={pid}".format(id=item.id, pid=config.pclass_id))
    else:
        description = desc

    # check whether an existing LiveProject for this config_id already exists
    existing_record = db.session.query(LiveProject).filter_by(config_id=config_id, parent_id=item.id).first()
    if existing_record:
        # nothing to do
        return

    # notice that this generates a LiveProject record ONLY FOR THIS PROJECT CLASS;
    # all project classes need their own LiveProject record
    live_item = LiveProject(
        config_id=config_id,
        parent_id=item.id,
        number=number,
        name=item.name,
        owner_id=item.owner_id,
        generic=item.generic,
        tags=item.tags,
        group_id=item.group_id,
        skills=item.skills,
        programmes=item.programmes,
        meeting_reqd=item.meeting_reqd,
        enforce_capacity=item.enforce_capacity,
        capacity=description.capacity,
        assessors=item.get_assessor_list(config.project_class) if config.uses_marker else [],
        supervisors=item.get_supervisor_list(config.project_class) if config.uses_supervisor else [],
        modules=[m for m in description.modules if m.active],
        description=description.description,
        reading=description.reading,
        aims=description.aims,
        team=description.team,
        review_only=description.review_only,
        show_popularity=item.show_popularity,
        show_bookmarks=item.show_bookmarks,
        show_selections=item.show_selections,
        dont_clash_presentations=item.dont_clash_presentations,
        hidden=False,
        page_views=0,
        last_view=None,
    )

    # no need to wrap these in a try ... except block
    # the client code is supposed to do this, so it can be informed about what kind of errors occurred
    db.session.add(live_item)

    if autocommit:
        # can expect exceptions to be caught by the client code
        db.session.commit()


def add_selector(student, config_id, convert=True, autocommit=False):
    # get StudentData instance
    if isinstance(student, StudentData):
        item = student
    else:
        item = StudentData.query.filter_by(id=student).first()

        if item is None:
            raise KeyError("Missing database record for StudentData id={id}".format(id=student))

    selector = SelectingStudent(
        config_id=config_id, student_id=item.id, retired=False, convert_to_submitter=convert, submission_time=None, submission_IP=None
    )
    db.session.add(selector)
    db.session.flush()

    generated_id = selector.id

    if autocommit:
        # can expect exceptions to be caught by the client code
        db.session.commit()

    return generated_id


def add_blank_submitter(student, selecting_config_id, submitting_config_id, autocommit=False, linked_selector_id=None):
    # get StudentData instance
    if isinstance(student, StudentData):
        item = student
    else:
        item = StudentData.query.filter_by(id=student).first()

        if item is None:
            raise KeyError("Missing database record for StudentData id={id}".format(id=student))

    config = ProjectClassConfig.query.filter_by(id=submitting_config_id).one()
    if config is None:
        raise LookupError("Missing database record for ProjectClassConfig id={id}".format(id=submitting_config_id))

    # generate new SubmittingStudent instance
    submitter = SubmittingStudent(config_id=submitting_config_id, student_id=item.id, selector_id=linked_selector_id, published=False, retired=False)

    # can expect exceptions to be caught by the client code
    db.session.add(submitter)
    db.session.flush()

    for i in range(0, config.submissions):
        period = config.get_period(i + 1)
        record = SubmissionRecord(
            period_id=period.id,
            retired=False,
            owner_id=submitter.id,
            project_id=None,
            marker_id=None,
            selection_config_id=selecting_config_id,
            matching_record_id=None,
            use_project_hub=None,
            report_id=None,
            processed_report_id=None,
            celery_started=None,
            celery_finished=None,
            timestamp=None,
            report_exemplar=False,
            canvas_submission_available=None,
            turnitin_outcome=None,
            turnitin_score=None,
            turnitin_web_overlap=None,
            turnitin_publication_overlap=None,
            turnitin_student_overlap=None,
            student_engaged=False,
            student_feedback=None,
            student_feedback_submitted=False,
            student_feedback_timestamp=None,
        )
        db.session.add(record)

        # no roles are generated as part of this process

    if autocommit:
        # can expect exceptions to be caught by the client code
        db.session.commit()

    celery = current_app.extensions["celery"]
    adjust_task = celery.tasks["app.tasks.assessment.adjust_submitter"]

    adjust_task.apply_async(args=(submitter.id, get_current_year()))
