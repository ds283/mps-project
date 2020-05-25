#
# Created by David Seery on 2018-11-01.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template, redirect, url_for, flash, request, session
from flask_security import login_required, roles_required, roles_accepted, current_user

from ..database import db
from ..models import User, FacultyData, ResearchGroup, SkillGroup, ProjectClass, ProjectClassConfig,\
    Project, LiveProject

from ..shared.conversions import is_integer

import app.ajax as ajax

from bokeh.plotting import figure
from bokeh.models.ranges import Range1d
from bokeh.embed import components

from . import reports


@reports.route('/workload')
@roles_required('reports')
def workload():
    """
    Basic workload report
    :return:
    """
    group_filter = request.args.get('group_filter')
    detail = request.args.get('detail')

    # if no group filter supplied, check if one is stored in session
    if group_filter is None and session.get('reports_workload_group_filter'):
        group_filter = session['reports_workload_group_filter']

    # write group filter into session if it is not empty
    if group_filter is not None:
        session['reports_workload_group_filter'] = group_filter

    # if no detail level supplied, check if one is stored in session
    if detail is None and session.get('reports_workload_detail'):
        detail = session['reports_workload_detail']

    # write detail level into session if it is not empty
    if detail is not None:
        session['reports_workload_detail'] = detail

    groups = db.session.query(ResearchGroup).filter_by(active=True).all()

    return render_template('reports/workload.html', groups=groups, group_filter=group_filter, detail=detail)


@reports.route('/workload_ajax')
@roles_required('reports')
def workload_ajax():
    """
    AJAX data point for workload report
    :return:
    """
    group_filter = request.args.get('group_filter')
    detail = request.args.get('detail')

    fac_query = db.session.query(FacultyData.id) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active)

    flag, group_value = is_integer(group_filter)
    if flag:
        fac_query = fac_query.filter(FacultyData.affiliations.any(id=group_value))

    faculty_ids = [f[0] for f in fac_query.all()]

    return ajax.reports.workload_data(faculty_ids, detail == 'simple')


@reports.route('/all_projects')
@roles_required('reports')
def all_projects():
    pclass_filter = request.args.get('pclass_filter')

    # if no pclass filter supplied, check if one is stored in session
    if pclass_filter is None and session.get('reports_projects_pclass_filter'):
        pclass_filter = session['reports_projects_pclass_filter']

    # write pclass filter into session if it is not empty
    if pclass_filter is not None:
        session['reports_projects_pclass_filter'] = pclass_filter

    valid_filter = request.args.get('valid_filter')

    if valid_filter is None and session.get('reports_projects_valid_filter'):
        valid_filter = session['reports_projects_valid_filter']

    if valid_filter is not None:
        session['reports_projects_valid_filter'] = valid_filter

    state_filter = request.args.get('state_filter')

    if state_filter is None and session.get('reports_projects_state_filter'):
        state_filter = session['reports_projects_state_filter']

    if state_filter is not None:
        session['reports_projects_state_filter'] = state_filter

    active_filter = request.args.get('active_filter')

    if active_filter is None and session.get('reports_projects_active_filter'):
        active_filter = session['reports_projects_active_filter']

    if active_filter is not None:
        session['reports_projects_active_filter'] = active_filter

    groups = SkillGroup.query.filter_by(active=True).order_by(SkillGroup.name.asc()).all()
    pclasses = ProjectClass.query.order_by(ProjectClass.name.asc()).all()

    return render_template('reports/all_projects.html', groups=groups, pclasses=pclasses, pclass_filter=pclass_filter,
                           valid_filter=valid_filter, state_filter=state_filter, active_filter=active_filter)


@reports.route('/all_projects_ajax')
@roles_required('reports')
def all_projects_ajax():
    """
    Ajax data point for All Projects report
    :return:
    """
    pclass_filter = request.args.get('pclass_filter')
    valid_filter = request.args.get('valid_filter')
    state_filter = request.args.get('state_filter')
    active_filter = request.args.get('active_filter')

    flag, pclass_value = is_integer(pclass_filter)

    pq = db.session.query(Project) \
        .join(FacultyData, FacultyData.id == Project.owner_id) \
        .join(User, User.id == FacultyData.id) \
        .filter(User.active == True)
    if flag:
        pq = pq.filter(Project.project_classes.any(id=pclass_value))

    if state_filter == 'active':
        pq = pq.filter(Project.project_classes.any(active=True))
    elif state_filter == 'inactive':
        pq = pq.filter(~Project.project_classes.any(active=True))
    elif state_filter == 'published':
        pq = pq.filter(Project.project_classes.any(active=True, publish=True))
    elif state_filter == 'unpublished':
        pq = pq.filter(~Project.project_classes.any(active=True, publish=True))

    if active_filter == 'active':
        pq = pq.filter(Project.active == True)
    elif active_filter == 'inactive':
        pq = pq.filter(Project.active == False)

    data = pq.all()

    if valid_filter == 'valid':
        data = [(x.id, None) for x in data if x.approval_state == Project.DESCRIPTIONS_APPROVED]
    elif valid_filter == 'not-valid':
        data = [(x.id, None) for x in data if x.approval_state == Project.SOME_DESCRIPTIONS_QUEUED]
    elif valid_filter == 'reject':
        data = [(x.id, None) for x in data if x.approval_state == Project.SOME_DESCRIPTIONS_REJECTED]
    elif valid_filter == 'pending':
        data = [(x.id, None) for x in data if x.approval_state == Project.SOME_DESCRIPTIONS_UNCONFIRMED]
    else:
        data = [(x.id, None) for x in data]

    return ajax.project.build_data(data, current_user.id)


_analyse_labels = {'popularity': ('Popularity rank', 'Popularity score'),
                   'views': ('Page views rank', 'Page views'),
                   'bookmarks': ('Bookmarks rank', 'Bookmarks'),
                   'selections': ('Selections rank', 'Selections')}

_analyse_colours = {'popularity': 'blue',
                    'views': 'red',
                    'bookmarks': 'green',
                    'selections': 'cornflowerblue'}


@reports.route('/liveproject_popularity/<int:proj_id>')
@roles_accepted('faculty', 'admin', 'root', 'reports')
def liveproject_analytics(proj_id):
    project: LiveProject = LiveProject.query.get_or_404(proj_id)
    config: ProjectClassConfig = project.config

    sel_lifecycle = config.selector_lifecycle
    require_live = (sel_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN)

    authorized = False

    # LiveProject owner is always authorized to view, as is root and admin users and anyone with a reports role
    if current_user.has_role('root') or current_user.has_role('admin') \
            or current_user.has_role('reports') or project.owner_id == current_user.id:
        authorized = True

    # if current user is convenor for the project class, then they are authorized
    if config.project_class.is_convenor(current_user.id):
        authorized = True

    if not authorized:
        flash('You are not authorized to view the analytics page for the project "{proj}"'.format(proj=project.name),
              'info')
        return redirect(request.referrer)

    url = request.args.get('url', None)
    text = request.args.get('text', None)

    if url is None:
        url = request.referrer

    if text is None and url is not None:
        text = 'previous page'

    pane = request.args.get('pane', 'popularity')

    if pane == 'views':
        rank_dates, rank_values = project.views_rank_history
        ranks = [x[0] for x in rank_values]

        score_dates, scores = project.views_history

    elif pane == 'bookmarks':
        rank_dates, rank_values = project.bookmarks_rank_history
        ranks = [x[0] for x in rank_values]

        score_dates, scores = project.bookmarks_history

    elif pane == 'selections':
        rank_dates, rank_values = project.selections_rank_history
        ranks = [x[0] for x in rank_values]

        score_dates, scores = project.selections_history

    else: # analyse == 'popularity':
        rank_dates, rank_values = project.popularity_rank_history
        ranks = [x[0] for x in rank_values]

        score_dates, scores = project.popularity_score_history

    rank_script = None
    rank_div = None

    score_script = None
    score_div = None

    labels = _analyse_labels[pane]
    colour = _analyse_colours[pane]

    if len(rank_values) > 0:
        total = rank_values[0][1]
        rank_div, rank_script = _build_rank_plot(rank_dates, ranks, total, labels[0], colour)

    if len(scores) > 0:
        score_div, score_script = _build_score_plot(score_dates, scores, labels[1], colour)

    return render_template('reports/liveproject_analytics/graph.html', project=project,
                           config=config, require_live=require_live, text=text, url=url,
                           pane=pane, rank_script=rank_script, rank_div=rank_div,
                           score_script=score_script, score_div=score_div)


def _build_score_plot(pop_score_dates, pop_scores, title, colour):
    plot = figure(title=title,
                  x_axis_label='Date', x_axis_type='datetime', plot_width=800, plot_height=300)
    plot.sizing_mode = 'scale_width'
    plot.line(pop_score_dates, pop_scores, legend=title.lower(), line_color=colour, line_width=2)
    plot.toolbar.logo = None
    plot.border_fill_color = None
    plot.background_fill_color = 'lightgrey'
    plot.legend.location = 'bottom_right'

    script, div = components(plot)

    return div, script


def _build_rank_plot(pop_rank_dates, pop_ranks, total, title, colour):
    y_range = Range1d(total, -5)

    plot = figure(title=title,
                  x_axis_label='Date', x_axis_type='datetime', plot_width=800, plot_height=300)
    plot.sizing_mode = 'scale_width'
    plot.line(pop_rank_dates, pop_ranks, legend=title.lower(), line_color=colour, line_width=2)
    plot.toolbar.logo = None
    plot.border_fill_color = None
    plot.background_fill_color = 'lightgrey'
    plot.legend.location = 'bottom_right'
    plot.y_range = y_range

    script, div = components(plot)

    return div, script
