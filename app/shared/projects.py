#
# Created by David Seery on 12/12/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime
from itertools import chain
from typing import List

from flask import flash, current_app
from flask_security import current_user
from sqlalchemy.exc import SQLAlchemyError

from app import db, ajax
from app.models import ProjectTagGroup, ProjectTag, ResearchGroup, TransferableSkill, SkillGroup, ProjectClass, Project, \
    ProjectClassConfig
from app.shared.sqlalchemy import get_count
from app.tools import ServerSideInMemoryHandler


def create_new_tags(form):
    matched, unmatched = form.tags.data

    if len(unmatched) > 0:
        default_group = db.session.query(ProjectTagGroup).filter_by(default=True).first()
        if default_group is None:

            default_group = db.session.query(ProjectTagGroup).first()
            if default_group is not None:
                flash('No default tag group has been set. Appending newly defined tags to the '
                      'group "{group}".'.format(group=default_group.name), 'warning')
            else:
                flash('No default tag group has been set. Newly defined tags have been '
                      'discarded.', 'error')

        if default_group is not None:
            for label in unmatched:
                new_tag = ProjectTag(name=label,
                                     group=default_group,
                                     colour=None,
                                     active=True,
                                     creator_id=current_user.id,
                                     creation_timestamp=datetime.now())
                try:
                    db.session.add(new_tag)
                    matched.append(new_tag)
                except SQLAlchemyError as e:
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    flash('Could not add newly defined tag "{tag}" due to a database error. '
                          'Please contact a system administrator'.format(tag=label), 'error')

    return matched


def get_filter_list_for_groups_and_skills(pclass: ProjectClass):
    if pclass.advertise_research_group:
        groups = db.session.query(ResearchGroup) \
            .filter_by(active=True).order_by(ResearchGroup.name.asc()).all()
    else:
        groups = None

    skills = db.session.query(TransferableSkill) \
        .join(SkillGroup, SkillGroup.id == TransferableSkill.group_id) \
        .filter(TransferableSkill.active == True, SkillGroup.active == True) \
        .order_by(SkillGroup.name.asc(), TransferableSkill.name.asc()).all()

    skill_list = {}

    for skill in skills:
        if skill_list.get(skill.group.name, None) is None:
            skill_list[skill.group.name] = []
        skill_list[skill.group.name].append(skill)

    return groups, skill_list


def apply_group_and_skills_filters(project: Project, groups: List[ResearchGroup], skills: List[TransferableSkill]):
    if groups is not None and len(groups) > 0:
        # check if any of the items in the filter list matches this project's group affiliation
        match = False

        for group in groups:
            if project.group_id == group.id:
                match = True
                break

        # nothing matched, kill append
        if not match:
            return False

    if skills is not None and len(skills) > 0:
        # check if any of the items in the skill list matches one of this project's transferable skills
        match = False

        for skill in skills:
            inner_match = False

            for sk in project.skills:
                if sk.id == skill.id:
                    inner_match = True
                    break

            if inner_match:
                match = True
                break

        if not match:
            return False

    return True


def project_list_ajax_handler(request, base_query, row_filter=None,
                              current_user_id: int=None,
                              config: ProjectClassConfig=None,
                              menu_template: str=None,
                              name_labels: bool=None,
                              text: str=None, url: str=None,
                              show_approvals: bool=False,
                              show_errors: bool=True):

    def search_name(row: Project):
        return row.name

    def sort_name(row: Project):
        return row.name

    def search_owner(row: Project):
        if not row.generic and row.owner is not None:
            return row.owner.user.name

        return 'generic'

    def sort_owner(row: Project):
        if row.generic or row.owner is None:
            return ['generic', 'generic']

        return [row.owner.user.last_name, row.owner.user.first_name]

    def sort_status(row: Project):
        if row.is_offerable:
            if row.active:
                return 2
            return 1
        return 0

    def search_group(row: Project):
        search_values = []

        if row.group is not None:
            search_values.append(row.group.name)

        for tag in row.forced_group_tags:
            search_values.append(tag.name)

        return search_values

    def sort_group(row: Project):
        sort_value = str()

        if row.group is not None:
            sort_value += row.group.name

        for tag in row.forced_group_tags:
            sort_value += tag.name

        return sort_value

    def search_pclasses(row: Project):
        search_values = [(pcl.name, pcl.abbreviation) for pcl in row.project_classes]

        # flatten list before returning it
        return set(chain.from_iterable(search_values))

    def sort_pclasses(row: Project):
        return get_count(row.project_classes)

    def sort_meeting(row: Project):
        return row.meeting_reqd

    def search_prefer(row: Project):
        search_values = [(p.full_name, p.short_name) for p in row.programmes]

        # flatten list before returning it
        return set(chain.from_iterable(search_values))

    def sort_prefer(row: Project):
        return get_count(row.programmes)

    def search_skills(row: Project):
        search_values = [(s.name, s.group.name) for s in row.skills]

        # flatten list before returning it
        return set(chain.from_iterable(search_values))

    def sort_skills(row: Project):
        return get_count(row.skills)

    name = {'search': search_name,
            'order': sort_name}
    owner = {'search': search_owner,
             'order': sort_owner}
    group = {'search': search_group,
             'order': sort_group}
    status = {'order': sort_status}
    pclasses= {'search': search_pclasses,
               'order': sort_pclasses}
    meeting = {'order': sort_meeting}
    prefer = {'search': search_prefer,
              'order': sort_prefer}
    skills = {'search': search_skills,
              'order': sort_skills}

    columns = {'name': name,
               'owner': owner,
               'group': group,
               'status': status,
               'pclasses': pclasses,
               'meeting': meeting,
               'prefer': prefer,
               'skills': skills}

    with ServerSideInMemoryHandler(request, base_query, columns,
                                   row_filter=row_filter) as handler:
        def row_formatter(projects):
            # convert project list back into a list of primary keys, so that we can
            # use cached outcomes
            return ajax.project.build_data([p.id for p in projects], config=config, current_user_id=current_user_id,
                                           menu_template=menu_template, name_labels=name_labels,
                                           text=text, url=url,
                                           show_approvals=show_approvals,
                                           show_errors=show_errors)

        return handler.build_payload(row_formatter)
