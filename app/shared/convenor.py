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
from ..models import Project, LiveProject, StudentData, SelectingStudent, SubmittingStudent, \
    ProjectClassConfig, SubmissionRecord


def add_liveproject(number, project, config_id, autocommit=False):

    # extract this project; input 'project' is allowed to be a Project instance, or else
    # the database id of an instance
    if isinstance(project, Project):
        item = project
    else:
        item = Project.query.filter_by(id=project).first()

        if item is None:
            raise KeyError('Missing database record for Project id={id}'.format(id=project))

    config = ProjectClassConfig.query.filter_by(id=config_id).first()
    if config is None:
        raise KeyError('Missing database record for ProjectClassConfig id={id}'.format(id=config_id))

    description = item.get_description(config.project_class)
    if description is None:
        raise KeyError('Missing description for Project id={id}, ProjectClass id={pid}'.format(id=item.id,
                                                                                               pid=config.pclass_id))

    # notice that this generates a LiveProject record ONLY FOR THIS PROJECT CLASS;
    # all project classes need their own LiveProject record
    live_item = LiveProject(config_id=config_id,
                            parent_id=item.id,
                            number=number,
                            name=item.name,
                            owner_id=item.owner_id,
                            keywords=item.keywords,
                            group_id=item.group_id,
                            skills=item.skills,
                            programmes=item.programmes,
                            meeting_reqd=item.meeting_reqd,
                            enforce_capacity=item.enforce_capacity,
                            capacity=description.capacity,
                            assessors=item.get_assessor_list(config.project_class)
                                if config.uses_marker else [],
                            modules=[m for m in description.modules if m.active],
                            description=description.description,
                            reading=description.reading,
                            team=description.team,
                            show_popularity=item.show_popularity,
                            show_bookmarks=item.show_bookmarks,
                            show_selections=item.show_selections,
                            dont_clash_presentations=item.dont_clash_presentations,
                            page_views=0,
                            last_view=None)

    db.session.add(live_item)

    if autocommit:
        db.session.commit()


def add_selector(student, config_id, autocommit=False):

    # get StudentData instance
    if isinstance(student, StudentData):
        item = student
    else:
        item = StudentData.query.filter_by(id=student).first()

        if item is None:
            raise KeyError('Missing database record for StudentData id={id}'.format(id=student))

    selector = SelectingStudent(config_id=config_id,
                                student_id=item.id,
                                retired=False)
    db.session.add(selector)

    if autocommit:
        db.session.commit()


def add_blank_submitter(student, old_config_id, new_config_id, autocommit=False):

    # get StudentData instance
    if isinstance(student, StudentData):
        item = student
    else:
        item = StudentData.query.filter_by(id=student).first()

        if item is None:
            raise KeyError('Missing database record for StudentData id={id}'.format(id=student))

    config = ProjectClassConfig.query.filter_by(id=new_config_id).one()

    # generate new SubmittingStudent instance
    submitter = SubmittingStudent(config_id=new_config_id,
                                  student_id=item.id,
                                  selector_id=None,  # this record not generated from a selector
                                  published=False,
                                  retired=False)
    db.session.add(submitter)
    db.session.flush()

    for i in range(0, config.submissions):
        period = config.get_period(i+1)
        record = SubmissionRecord(period_id=period.id,
                                  retired=False,
                                  owner_id=submitter.id,
                                  project_id=None,
                                  marker_id=None,
                                  selection_config_id=old_config_id,
                                  matching_record_id=None,
                                  student_engaged=False,
                                  supervisor_positive=None,
                                  supervisor_negative=None,
                                  supervisor_submitted=False,
                                  supervisor_timestamp=None,
                                  marker_positive=None,
                                  marker_negative=None,
                                  marker_submitted=False,
                                  marker_timestamp=None,
                                  student_feedback=None,
                                  student_feedback_submitted=False,
                                  student_feedback_timestamp=None,
                                  acknowledge_feedback=False,
                                  faculty_response=None,
                                  faculty_response_submitted=False,
                                  faculty_response_timestamp=None)
        db.session.add(record)

    if autocommit:
        db.session.commit()

    celery = current_app.extensions['celery']
    adjust_task = celery.tasks['app.tasks.assessment.adjust_submitter']

    adjust_task.apply_async(args=(submitter.id, get_current_year()))
