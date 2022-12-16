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
from sqlalchemy import func
from sqlalchemy.exc import SQLAlchemyError

from app import db, ajax
from app.models import ProjectTagGroup, ProjectTag, ResearchGroup, TransferableSkill, SkillGroup, ProjectClass, Project, \
    ProjectClassConfig, User
from app.tools import ServerSideSQLHandler, ServerSideInMemoryHandler


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


def project_list_SQL_handler(request, base_query,
                             current_user_id: int=None,
                             config: ProjectClassConfig=None,
                             menu_template: str=None,
                             name_labels: bool=None,
                             text: str=None, url: str=None,
                             show_approvals: bool=False,
                             show_errors: bool=True):

    name = {'search': Project.name,
            'order': Project.name,
            'search_collation': 'utf8_general_ci'}
    owner = {'search': func.concat(User.first_name, ' ', User.last_name),
             'order': [User.last_name, User.first_name],
             'search_collation': 'utf8_general_ci'}

    columns = {'name': name,
               'owner': owner}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        def row_formatter(projects):
            # convert project list back into a list of primary keys, so that we can
            # use cached outcomes
            return ajax.project.build_data([p.id for p in projects], config=config, current_user_id=current_user_id,
                                           menu_template=menu_template, name_labels=name_labels,
                                           text=text, url=url,
                                           show_approvals=show_approvals,
                                           show_errors=show_errors)

        return handler.build_payload(row_formatter)


def project_list_in_memory_handler(request, base_query, row_filter=None,
                                   current_user_id: int = None,
                                   config: ProjectClassConfig = None,
                                   menu_template: str = None,
                                   name_labels: bool = None,
                                   text: str = None, url: str = None,
                                   show_approvals: bool = False,
                                   show_errors: bool = True):

    def search_name(row: Project):
        return row.name

    def sort_name(row: Project):
        return row.name

    def search_owner(row: Project):
        if not row.generic and row.owner is not None:
            return row.owner.user.name

        return 'generic'

    def sort_owner(row: Project):
        if not row.generic and row.owner is not None:
            return [row.owner.user.last_name, row.owner.user.first_name]

        return ['generic', 'generic']

    name = {'search': search_name,
            'order': sort_name}
    owner = {'search': search_owner,
             'order': sort_owner}

    columns = {'name': name,
               'owner': owner}

    with ServerSideInMemoryHandler(request, base_query, columns, row_filter=row_filter) as handler:
        def row_formatter(projects):
            # convert project list back into a list of primary keys, so that we can
            # use cached outcomes
            return ajax.project.build_data([p.id for p in projects], config=config, current_user_id=current_user_id,
                                           menu_template=menu_template, name_labels=name_labels,
                                           text=text, url=url,
                                           show_approvals=show_approvals,
                                           show_errors=show_errors)

        return handler.build_payload(row_formatter)
