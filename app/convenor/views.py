#
# Created by David Seery on 24/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_security import roles_accepted, current_user

from ..models import db, User, FacultyData, StudentData, TransferableSkill, ProjectClass, ProjectClassConfig, LiveProject, SelectingStudent, SubmittingStudent, \
    Project

from ..shared.utils import get_current_year, home_dashboard
from ..shared.validators import validate_convenor, validate_administrator, validate_user, validate_open
from ..shared.actions import render_live_project, do_confirm, do_cancel_confirm, do_deconfirm, do_deconfirm_to_pending

from ..task_queue import register_task

import app.ajax as ajax

from . import convenor

from ..faculty.forms import AddProjectForm, EditProjectForm, GoLiveForm, IssueFacultyConfirmRequestForm

from datetime import date, datetime, timedelta

from sqlalchemy import func


_project_menu = \
"""
<div class="dropdown">
    <button class="btn btn-success btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('convenor.edit_project', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Edit project
            </a>
        </li>
        <li>
            <a href="{{ url_for('faculty.project_preview', id=project.id) }}">
                Preview web page
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_skills', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Transferable skills
            </a>
        </li>

        <li>
            <a href="{{ url_for('convenor.attach_programmes', id=project.id, pclass_id=0) }}">
                <i class="fa fa-pencil"></i> Degree programmes
            </a>
        </li>

        <li>
        {% if project.active %}
            <a href="{{ url_for('faculty.deactivate_project', id=project.id) }}">
                Make inactive
            </a>
        {% else %}
            <a href="{{ url_for('faculty.activate_project', id=project.id) }}">
                Make active
            </a>
        {% endif %}
        </li>
    </ul>
</div>
"""


def _dashboard_data(pclass, config):
    """
    Efficiently retrieve statistics needed to render the convenor dashboard
    :param pclass:
    :param config:
    :return:
    """

    fac_query = db.session.query(func.count(User.id)). \
        filter(User.active).join(FacultyData, FacultyData.id == User.id)

    fac_total = fac_query.scalar()
    fac_count = fac_query.filter(FacultyData.enrollments.any(id=pclass.id)).scalar()

    proj_count = db.session.query(func.count(Project.id)). \
        filter(Project.active, Project.project_classes.any(id=pclass.id)).scalar()

    sel_count = db.session.query(func.count(SelectingStudent.id)). \
        filter(~SelectingStudent.retired, SelectingStudent.config_id == config.id).scalar()

    sub_count = db.session.query(func.count(SelectingStudent.id)). \
        filter(~SelectingStudent.retired, SelectingStudent.config_id == config.id).scalar()

    live_count = db.session.query(func.count(LiveProject.id)). \
        filter(LiveProject.config_id == config.id).scalar()

    return (fac_count, fac_total), live_count, proj_count, sel_count, sub_count


@convenor.route('/overview/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def overview(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build forms
    golive_form = GoLiveForm(request.form)
    issue_form = IssueFacultyConfirmRequestForm(request.form)

    if config.requests_issued:

        issue_form.requests_issued.label.text = 'Save changes'

    if request.method == 'GET':

        if config.request_deadline is not None:
            issue_form.request_deadline.data = config.request_deadline
        else:
            issue_form.request_deadline.data = date.today() + timedelta(weeks=6)

        if config.live_deadline is not None:
            golive_form.live_deadline.data = config.live_deadline
        else:
            golive_form.live_deadline.data = date.today() + timedelta(weeks=6)

    fac_data, live_count, proj_count, sel_count, sub_count = _dashboard_data(pclass, config)

    return render_template('convenor/dashboard/overview.html', pane='overview',
                           golive_form=golive_form, issue_form=issue_form,
                           pclass=pclass, config=config, current_year=current_year,
                           fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


@convenor.route('/attached/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def attached(id):

    if id == 0:
        return redirect(url_for('convenor.show_unattached'))

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    fac_data, live_count, proj_count, sel_count, sub_count = _dashboard_data(pclass, config)

    return render_template('convenor/dashboard/attached.html', pane='attached',
                           pclass=pclass, config=config, current_year=current_year,
                           fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


@convenor.route('/attached_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def attached_ajax(id):
    """
    Ajax data point for attached projects view
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return jsonify({})

    return ajax.project.build_data(pclass.projects, _project_menu)


@convenor.route('/faculty/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def faculty(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    fac_data, live_count, proj_count, sel_count, sub_count = _dashboard_data(pclass, config)

    return render_template('convenor/dashboard/faculty.html', pane='faculty',
                           pclass=pclass, config=config, current_year=current_year,
                           faculty=faculty, fac_data=fac_data, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


@convenor.route('faculty_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def faculty_ajax(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build list of all active faculty, together with their FacultyData records
    faculty = db.session.query(User, FacultyData).filter(User.active).join(FacultyData, FacultyData.id==User.id)

    return ajax.convenor.faculty_data(faculty, pclass, config)


@convenor.route('/selectors/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def selectors(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    fac_data, live_count, proj_count, sel_count, sub_count = _dashboard_data(pclass, config)

    return render_template('convenor/dashboard/selectors.html', pane='selectors',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


@convenor.route('/selectors_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def selectors_ajax(id):
    """
    Ajax data point for selectors view
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build a list of live students selecting from this project class
    selectors = config.selecting_students.filter_by(retired=False)

    return ajax.convenor.selectors_data(selectors, config)


@convenor.route('/submitters/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def submitters(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    fac_data, live_count, proj_count, sel_count, sub_count = _dashboard_data(pclass, config)

    return render_template('convenor/dashboard/submitters.html', pane='submitters',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


@convenor.route('/submitters_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def submitters_ajax(id):
    """
    Ajax data point for submitters view
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    # build a list of live students submitting work for evaluation in this project class
    submitters = config.submitting_students.filter_by(retired=False)

    return ajax.convenor.submitters_data(submitters, config)


@convenor.route('/liveprojects/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def liveprojects(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current academic year
    current_year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    fac_data, live_count, proj_count, sel_count, sub_count = _dashboard_data(pclass, config)

    return render_template('convenor/dashboard/liveprojects.html', pane='live',
                           pclass=pclass, config=config, fac_data=fac_data,
                           current_year=current_year, sel_count=sel_count, sub_count=sub_count,
                           live_count=live_count, proj_count=proj_count)


@convenor.route('/liveprojects_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def liveprojects_ajax(id):
    """
    Ajax data point for liveprojects fiew
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return jsonify({})

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    return ajax.convenor.liveprojects_data(config)


@convenor.route('/add_project/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def add_project(pclass_id):

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_convenor(pclass):
            return redirect(request.referrer)

    # set up form
    form = AddProjectForm(request.form, convenor_editing=True)

    if form.validate_on_submit():

        data = Project(name=form.name.data,
                       keywords=form.keywords.data,
                       active=True,
                       owner=form.owner.data,
                       group=form.group.data,
                       project_classes=form.project_classes.data,
                       skills=[],
                       programmes=[],
                       meeting_reqd=form.meeting.data,
                       capacity=form.capacity.data,
                       enforce_capacity=form.enforce_capacity.data,
                       team=form.team.data,
                       description=form.description.data,
                       reading=form.reading.data,
                       creator_id=current_user.id,
                       creation_timestamp=datetime.now())

        # ensure that list of preferred degree programmes is consistent
        data.validate_programmes()

        # auto-enroll if implied by current project class associations
        owner = data.owner.faculty_data
        for pclass in data.project_classes:

            if owner not in pclass.enrolled_faculty.all():

                owner.enrollments.append(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.build_name(), pclass=pclass.name))

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('convenor.attached', id=pclass_id))

    return render_template('faculty/edit_project.html', project_form=form, pclass_id=pclass_id, title='Add new project')


@convenor.route('/edit_project/<int:id>/<int:pclass_id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_project(id, pclass_id):

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_convenor(pclass):
            return redirect(request.referrer)

    # set up form
    data = Project.query.get_or_404(id)

    form = EditProjectForm(obj=data, convenor_editing=True)
    form.project = data

    if form.validate_on_submit():

        data.name = form.name.data
        data.owner = form.owner.data
        data.keywords = form.keywords.data
        data.group = form.group.data
        data.project_classes = form.project_classes.data
        data.meeting_reqd = form.meeting.data
        data.capacity = form.capacity.data
        data.enforce_capacity = form.enforce_capacity.data
        data.team = form.team.data
        data.description = form.description.data
        data.reading = form.reading.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        # ensure that list of preferred degree programmes is now consistent
        data.validate_programmes()

        # auto-enroll if implied by current project class associations
        owner = data.owner.faculty_data
        for pclass in data.project_classes:

            if owner not in pclass.enrolled_faculty.all():

                owner.enrollments.append(pclass)
                flash('Auto-enrolled {name} in {pclass}'.format(name=data.owner.build_name(), pclass=pclass.name))

        db.session.commit()

        return redirect(url_for('convenor.attached', id=pclass_id))

    return render_template('faculty/edit_project.html', project_form=form, project=data, pclass_id=pclass_id, title='Edit project details')


@convenor.route('/activate_project/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def activate_project(id, pclass_id):

    # get project details
    data = Project.query.get_or_404(id)

    # get project class details
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # if logged in user is not a suitable convenor, or an administrator, object
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/deactivate_project/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def deactivate_project(id, pclass_id):

    # get project details
    data = Project.query.get_or_404(id)

    # get project class details
    pclass = ProjectClass.query.get_or_404(pclass_id)

    # if logged in user is not a suitable convenor, or an administrator, object
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/attach_skills/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_skills(id, pclass_id):

    # get project details
    data = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_convenor(pclass):
            return redirect(request.referrer)

    # get list of active skills
    skills = TransferableSkill.query.filter_by(active=True).order_by(TransferableSkill.name)

    return render_template('convenor/attach_skills.html', data=data, skills=skills, pclass_id=pclass_id)


@convenor.route('/attach_programmes/<int:id>/<int:pclass_id>')
@roles_accepted('faculty', 'admin', 'root')
def attach_programmes(id, pclass_id):

    # get project details
    data = Project.query.get_or_404(id)

    if pclass_id == 0:

        # got here from unattached projects view; reject if user is not administrator
        if not validate_administrator():
            return redirect(request.referrer)

    else:

        # get project class details
        pclass = ProjectClass.query.get_or_404(pclass_id)

        # if logged in user is not a suitable convenor, or an administrator, object
        if not validate_convenor(pclass):
            return redirect(request.referrer)

    q = data.available_degree_programmes

    return render_template('convenor/attach_programmes.html', data=data, programmes=q.all(), pclass_id=pclass_id)


@convenor.route('/issue_confirm_requests/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def issue_confirm_requests(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    issue_form = IssueFacultyConfirmRequestForm(request.form)

    if issue_form.is_submitted() and issue_form.requests_issued.data is True:

        # set request deadline and issue requests if needed

        # only generate requests if they haven't been issued; subsequent clicks might be changes to deadline
        if not config.requests_issued:

            config.generate_golive_requests()
            requests = config.golive_required.count()
            plural = 's'
            if requests == 0:
                plural = ''

            flash('{n} confirmation request{plural} have been issued'.format(n=requests, plural=plural))

        config.requests_issued = True
        config.request_deadline = issue_form.request_deadline.data

        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/golive_ajax/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def golive_ajax(id):
    """
    Ajax data point for waiting-to-go-live faculty list on dashboard
    :param id:
    :return:
    """

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to view this dashboard
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    return ajax.convenor.golive_data(config)


@convenor.route('/show_unattached')
@roles_accepted('faculty', 'admin', 'root')
def show_unattached():

    # special-case of unattached projects; reject user if not administrator
    if not validate_administrator():
        return redirect(request.referrer)

    return render_template('convenor/unattached.html')


@convenor.route('/unattached_ajax')
@roles_accepted('faculty', 'admin', 'root')
def unattached_ajax():
    """
    Ajax data point for show-unattached view
    :return:
    """

    if not validate_administrator():
        return jsonify({})

    projects = [proj for proj in Project.query.all() if not proj.offerable]

    return ajax.project.build_data(projects, _project_menu)



@convenor.route('/force_confirm_all/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def force_confirm_all(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    for item in config.golive_required.all():

        config.golive_required.remove(item)

    db.session.commit()

    flash('All outstanding confirmation requests have been removed.', 'success')

    return redirect(request.referrer)


@convenor.route('/go_live/<pid>/<int:configid>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'route')
def go_live(pid, configid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pid)

    # reject user if not entitled to perform dashboard functions
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    year = get_current_year()

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=pid).order_by(ProjectClassConfig.year.desc()).first()

    if config.id != configid or config.year != year:
        flash('A "Go Live" request was ignored. If you are attempting to go live with this project class, '
              'please contact a system administrator.', 'error')
        return redirect(url_for('convenor.overview', id=pid))

    form = GoLiveForm(request.form)

    if form.is_submitted():

        # get rollover instance
        celery = current_app.extensions['celery']
        golive = celery.tasks['app.tasks.go_live.pclass_golive']
        golive_fail = celery.tasks['app.tasks.go_live.golive_fail']

        # register Go Live as a new background task and push it to the celery scheduler
        task_id = register_task('Go Live for "{proj}" {yra}-{yrb}'.format(proj=pclass.name, yra=year, yrb=year+1),
                                owner=current_user,
                                description='Perform Go Live of "{proj}"'.format(proj=pclass.name))
        golive.apply_async((task_id, pid, configid, current_user.id, form.live_deadline.data),
                           link_error=golive_fail.si(task_id, current_user.id))

    return redirect(request.referrer)


@convenor.route('/close_selections/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'route')
def close_selections(id):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(id)

    # reject user if not entitled to perform dashboard functions
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    # get current configuration record for this project class
    config = ProjectClassConfig.query.filter_by(pclass_id=id).order_by(ProjectClassConfig.year.desc()).first()

    config.closed = True
    config.closed_id = current_user.id
    config.closed_timestamp = datetime.now()

    db.session.commit()

    flash('Student selections for{name} {yeara}-{yearb} have now been closed'.format(name=pclass.name, yeara=config.year, yearb=config.year+1), 'success')

    return redirect(request.referrer)


@convenor.route('/enroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def enroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.add_enrollment(pclass)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/unenroll/<int:userid>/<int:pclassid>')
@roles_accepted('faculty', 'admin', 'root')
def unenroll(userid, pclassid):

    # get details for project class
    pclass = ProjectClass.query.get_or_404(pclassid)

    # reject user if not a suitable convenor or administrator
    if not validate_convenor(pclass):
        return redirect(request.referrer)

    data = FacultyData.query.get_or_404(userid)
    data.remove_enrollment(pclass)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/confirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def confirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    if do_confirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/deconfirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def deconfirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    if do_deconfirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/deconfirm_to_pending/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def deconfirm_to_pending(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    if do_deconfirm_to_pending(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/cancel_confirm/<int:sid>/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def cancel_confirm(sid, pid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    if do_cancel_confirm(sel, project):
        db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_confirm_all/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_confirm_all(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_open(project.config):
        return redirect(request.referrer)

    for item in project.confirm_waiting:
        if item not in project.confirmed_students:
            project.confirmed_students.append(item)
        project.confirm_waiting.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_clear_requests/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_clear_requests(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_open(project.config):
        return redirect(request.referrer)

    for item in project.confirm_waiting:
        project.confirm_waiting.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_remove_confirms/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_remove_confirms(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_open(project.config):
        return redirect(request.referrer)

    for item in project.confirmed_students:
        project.confirmed_students.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/project_make_all_confirms_pending/<int:pid>')
@roles_accepted('faculty', 'admin', 'route')
def project_make_all_confirms_pending(pid):

    # pid is a LiveProject
    project = LiveProject.query.get_or_404(pid)

    pclass = project.config.project_class

    # validate that logged-in user is allowed to edit this LiveProject
    if not validate_convenor(pclass):
        return home_dashboard()

    # validate that project is open
    if not validate_open(project.config):
        return redirect(request.referrer)

    for item in project.confirmed_students:
        if item not in project.confirm_waiting:
            project.confirm_waiting.append(item)
        project.confirmed_students.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_confirm_all/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_confirm_all(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_convenor(sel.config.project_class):
        return redirect(request.referrer)

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    for item in sel.confirm_requests:
        if item not in sel.confirmed:
            sel.confirmed.append(item)
        sel.confirm_requests.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_remove_confirms/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_remove_confirms(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    for item in sel.confirmed:
        sel.confirmed.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_clear_requests/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_clear_requests(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    for item in sel.confirm_requests:
        sel.confirm_requests.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_make_all_confirms_pending/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_make_all_confirms_pending(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    for item in sel.confirmed:
        if item not in sel.confirm_requests:
            sel.confirm_requests.append(item)
        sel.confirmed.remove(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/student_clear_bookmarks/<int:sid>')
@roles_accepted('faculty', 'admin', 'route')
def student_clear_bookmarks(sid):

    # sid is a SelectingStudent
    sel = SelectingStudent.query.get_or_404(sid)

    # validate that logged-in user is allowed to edit this SelectingStudent
    if not validate_convenor(sel.config.project_class):
        return home_dashboard()

    # validate that project is open
    if not validate_open(sel.config):
        return redirect(request.referrer)

    for item in sel.bookmarks:
        db.session.delete(item)
    db.session.commit()

    return redirect(request.referrer)


@convenor.route('/live_project/<int:pid>/<int:classid>')
@roles_accepted('faculty', 'admin', 'root')
def live_project(pid):
    """
    View a specific project on the live system
    :param tabid:
    :param classid:
    :param pid:
    :return:
    """

    # pid is the id for a LiveProject
    data = LiveProject.query.get_or_404(pid)

    # verify the logged-in user is allowed to view this live project
    if not validate_user(data):
        return redirect(request.referrer)

    return render_live_project(data)


@convenor.route('/confirm_rollover/<int:pid>/<int:configid>')
@roles_accepted('faculty', 'admin', 'route')
def confirm_rollover(pid, configid):

    year = get_current_year()

    # do nothing if a rollover has already been performed (try to make action idempotent in case
    # accidentally invoked twice)
    config = ProjectClassConfig.query.filter_by(pclass_id=pid).order_by(ProjectClassConfig.year.desc()).first()

    title = 'Rollover of "{proj}" to {yeara}&ndash;{yearb}'.format(proj=config.project_class.name,
                                                                   yeara=year, yearb=year + 1)
    action_url = url_for('convenor.rollover', pid=pid, configid=configid)
    message = 'Please confirm that you wish to rollover project class "{proj}" to ' \
              '{yeara}&ndash;{yearb}'.format(proj=config.project_class.name,
                                             yeara=year, yearb=year + 1)
    submit_label = 'Rollover to {yr}'.format(yr=year)

    return render_template('admin/danger_confirm.html', title=title, panel_title=title, action_url=action_url,
                           message=message, submit_label=submit_label)


@convenor.route('/rollover/<int:pid>/<int:configid>')
@roles_accepted('faculty', 'admin', 'route')
def rollover(pid, configid):

    # pid is a ProjectClass
    pclass = ProjectClass.query.get_or_404(pid)

    if not pclass.active:
        flash('{name} is not an active project class'.format(name=pclass.name), 'error')
        return home_dashboard()

    # validate that logged-in user is a convenor or suitable admin for this project class
    if not validate_convenor(pclass):
        return home_dashboard()

    year = get_current_year()

    # do nothing if a rollover has already been performed (try to make action idempotent in case
    # accidentally invoked twice)
    config = ProjectClassConfig.query.filter_by(pclass_id=pid).order_by(ProjectClassConfig.year.desc()).first()

    if config.id != configid or config.year == year:
        flash('A rollover request was ignored. If you are attempting to rollover the academic year and '
              'have not managed to do so, please contact a system administrator', 'error')
        return redirect(url_for('convenor.overview', id=pid))

    # get rollover instance
    celery = current_app.extensions['celery']
    rollover = celery.tasks['app.tasks.rollover.pclass_rollover']
    rollover_fail = celery.tasks['app.tasks.rollover.rollover_fail']

    # register rollover as a new background task and push it to the celery scheduler
    task_id = register_task('Rollover "{proj}" to {yra}-{yrb}'.format(proj=pclass.name, yra=year, yrb=year+1),
                            owner=current_user,
                            description='Perform rollover of "{proj}" to new academic year'.format(proj=pclass.name))
    rollover.apply_async((task_id, pid, configid, current_user.id),
                         link_error=rollover_fail.si(task_id, current_user.id))

    return redirect(url_for('convenor.overview', id=pid))
