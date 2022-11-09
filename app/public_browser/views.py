#
# Created by David Seery on 14/10/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
import re
from functools import partial

from flask import render_template, request, jsonify, url_for
from sqlalchemy import and_, func

from . import public_browser
from .forms import PublicBrowserSelectorForm
from ..ajax.public_browser.project_list_data import public_browser_project_list
from ..database import db
from ..models import ProjectClass, Project, FacultyData, User, ResearchGroup
from ..shared.conversions import is_integer
from ..tools import ServerSideSQLHandler


@public_browser.route('/browse', methods=['GET', 'POST'])
def browse():
    form = PublicBrowserSelectorForm(request.form)

    pclass_arg = request.args.get('pclass_id')
    flag, pclass_request = is_integer(pclass_arg)

    pclass_id = None
    if form.selector.data is None:
        if flag:
            pclass = db.session.query(ProjectClass).filter_by(id=pclass_request).first()
            if pclass is not None:
                form.selector.data = pclass
                pclass_id = pclass.id

    else:
        pclass_id = form.selector.data.id

    return render_template("public_browser/browser.html", form=form, pclass_id=pclass_id)


@public_browser.route('/browse_ajax', methods=['POST'])
def browse_ajax():
    pclass_arg = request.args.get('pclass_id')
    flag, pclass_id = is_integer(pclass_arg)

    if not flag:
        return jsonify({})

    # build base query of all active projects that are attached to the specified
    # project class; this is the full set of projects for which we allow browsing
    base_query = db.session.query(Project) \
        .filter(and_(Project.active == True,
                     Project.project_classes.any(ProjectClass.id == pclass_id))) \
        .join(FacultyData, FacultyData.id == Project.owner_id) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active == True) \
        .join(ResearchGroup, ResearchGroup.id == Project.group_id)

    name = {'search': Project.name,
             'order': Project.name,
             'search_collation': 'utf8_general_ci'}
    supervisor = {'search': func.concat(User.first_name, ' ', User.last_name),
                  'order': [User.last_name, User.first_name],
                  'search_collation': 'utf8_general_ci'}
    group = {'search': ResearchGroup.name,
             'order': ResearchGroup.name,
             'search_collation': 'utf8_general_ci'}

    columns = {'name': name,
               'supervisor': supervisor,
               'group': group}

    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(public_browser_project_list, pclass_id))


@public_browser.route('/project/<int:pclass_id>/<int:proj_id>')
def project(pclass_id, proj_id):
    """
    View a specific project
    :param pid:
    :return:
    """
    # pclass_id is a ProjectClass instance
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    # proj_id is a Project instance
    project: Project = Project.query.get_or_404(proj_id)

    desc = project.get_description(pclass.id)

    if project.keywords is not None:
        keywords = [kw.strip() for kw in re.split("[;,]", project.keywords)]
        keywords = [w for w in keywords if len(w) > 0]
    else:
        keywords = []

    text = 'browse projects view'
    url = url_for('public_browser.browse', pclass_id=pclass.id)

    return render_template("public_browser/project.html", title=project.name, project=project,
                           desc=desc, keywords=keywords, text=text, url=url)
