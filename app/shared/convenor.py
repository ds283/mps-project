#
# Created by David Seery on 11/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from ..models import db, Project, LiveProject, StudentData, SelectingStudent, SubmittingStudent


def add_liveproject(number, project, config_id, autocommit=False):

    # extract this project; input 'project' is allowed to be a Project instance, or else
    # the database id of an instance
    if isinstance(project, Project):
        item = project
    else:
        item = Project.query.filter_by(id=project).first()

        if item is None:
            raise KeyError('Missing database record for Project id={id}'.format(id=project))

    # notice that this generates a LiveProject record ONLY FOR THIS PROJECT CLASS;
    # all project classes need their own LiveProject record
    live_item = LiveProject(config_id=config_id,
                            number=number,
                            name=item.name,
                            keywords=item.keywords,
                            owner_id=item.owner_id,
                            group_id=item.group_id,
                            skills=item.skills,
                            capacity=item.capacity,
                            enforce_capacity=item.enforce_capacity,
                            meeting_reqd=item.meeting_reqd,
                            team=item.team,
                            description=item.description,
                            reading=item.reading,
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
                                user_id=item.user.id,
                                retired=False)
    db.session.add(selector)

    if autocommit:
        db.session.commit()


def add_submitter(student, config_id, autocommit=False):

    # get StudentData instance
    if isinstance(student, StudentData):
        item = student
    else:
        item = StudentData.query.filter_by(id=student).first()

        if item is None:
            raise KeyError('Missing database record for StudentData id={id}'.format(id=student))

    submitter = SubmittingStudent(config_id=config_id,
                                  user_id=item.user.id,
                                  retired=False)
    db.session.add(submitter)

    if autocommit:
        db.session.commit()
