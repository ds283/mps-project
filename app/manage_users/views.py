#
# Created by David Seery on 2019-04-17.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime, date, timedelta
from functools import partial
from pathlib import Path

from celery import chain, group
from flask import render_template, redirect, url_for, flash, request, current_app, session
from flask_security import current_user, roles_required, roles_accepted
from flask_security.confirmable import generate_confirmation_link
from flask_security.signals import user_registered
from flask_security.utils import config_value, get_message, do_flash, send_mail
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql import cast
from sqlalchemy.types import String
from werkzeug.local import LocalProxy

import app.ajax as ajax
from . import manage_users
from .actions import register_user
from .forms import UserTypeSelectForm, ConfirmRegisterOfficeForm, ConfirmRegisterFacultyForm, \
    ConfirmRegisterStudentForm, EditOfficeForm, EditFacultyForm, EditStudentForm, \
    UploadBatchCreateForm, EditStudentBatchItemFormFactory, EnrollmentRecordForm, \
    AddRoleForm, EditRoleForm
from ..database import db
from ..limiter import limiter
from ..models import User, FacultyData, StudentData, StudentBatch, StudentBatchItem, EnrollmentRecord, \
    DegreeProgramme, DegreeType, ProjectClass, ResearchGroup, Role, TemporaryAsset, TaskRecord, BackupRecord, \
    AssetLicense, WorkflowMixin, faculty_affiliations
from ..shared.asset_tools import make_temporary_asset_filename
from ..shared.conversions import is_integer
from ..shared.sqlalchemy import func
from ..shared.utils import get_current_year, get_main_config, home_dashboard_url, redirect_url
from ..shared.validators import validate_is_convenor
from ..task_queue import register_task, progress_update
from ..tools import ServerSideHandler
from ..uploads import batch_user_files

_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


@manage_users.route('/create_user', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def create_user():
    """
    View function that handles creation of a user account
    """

    # check whether any active degree programmes exist, and raise an error if not
    if not DegreeProgramme.query.filter_by(active=True).first():
        flash('No degree programmes are available. '
              'Set up at least one active degree programme before adding new users.')
        return redirect(redirect_url())

    # first task is to capture the user role
    form = UserTypeSelectForm(request.form)

    if form.validate_on_submit():
        # get role and redirect to appropriate form
        role = form.roles.data

        if role == 'office':
            return redirect(url_for('manage_users.create_office', role=role))

        elif role == 'faculty':
            return redirect(url_for('manage_users.create_faculty', role=role))

        elif role == 'student':
            return redirect(url_for('manage_users.create_student', role=role))

        else:
            flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
            return redirect(url_for('manage_users.edit_users'))

    return render_template('security/register_role.html', role_form=form, title='Select new account role')


@manage_users.route('/create_office/<string:role>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def create_office(role):
    """
    Create an 'office' user
    :param role:
    :return:
    """

    # check whether role is ok
    if not (role == 'office'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('manage_users.edit_users'))

    form = ConfirmRegisterOfficeForm(request.form)

    if form.validate_on_submit():
        # convert field values to a dictionary
        field_data = form.to_dict(True)
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        db.session.commit()

        return redirect(url_for('manage_users.edit_users'))
    else:
        if request.method == 'GET':
            form.random_password.data = True

            license = db.session.query(AssetLicense).filter_by(
                abbreviation=current_app.config['OFFICE_DEFAULT_LICENSE']).first()
            form.default_license.data = license

    return render_template('security/register_user.html', user_form=form, role=role,
                           title='Register a new {r} user account'.format(r=role))


@manage_users.route('/create_faculty/<string:role>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def create_faculty(role):
    """
    Create a 'faculty' user
    :param role:
    :return:
    """

    # check whether role is ok
    if not (role == 'faculty'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('manage_users.edit_users'))

    form = ConfirmRegisterFacultyForm(request.form)

    pane = request.args.get('pane', None)

    if form.validate_on_submit():
        # convert field values to a dictionary
        field_data = form.to_dict(True)
        field_data['roles'] = [role]

        user = register_user(**field_data)

        # insert extra data for faculty accounts
        data = FacultyData(id=user.id,
                           academic_title=form.academic_title.data,
                           use_academic_title=form.use_academic_title.data,
                           sign_off_students=form.sign_off_students.data,
                           project_capacity=form.project_capacity.data if form.enforce_capacity.data else None,
                           enforce_capacity=form.enforce_capacity.data,
                           show_popularity=form.show_popularity.data,
                           dont_clash_presentations=form.dont_clash_presentations.data,
                           CATS_supervision=form.CATS_supervision.data,
                           CATS_marking=form.CATS_marking.data,
                           CATS_presentation=form.CATS_presentation.data,
                           office=form.office.data,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        if form.submit.data:
            return redirect(url_for('manage_users.edit_affiliations', id=data.id, create=1, pane=pane))
        elif form.save_and_exit.data:
            if pane is None or pane == 'accounts':
                return redirect(url_for('manage_users.edit_users'))
            elif pane == 'faculty':
                return redirect(url_for('manage_users.edit_users_faculty'))
            elif pane == 'students':
                return redirect(url_for('manage_users.edit_users_students'))
            else:
                raise RuntimeError('Unknown user pane "{pane}"'.format(pane=pane))
        else:
            raise RuntimeError('Unknown submit button in create_faculty')

    else:

        if request.method == 'GET':
            # dynamically set default project capacity
            form.project_capacity.data = current_app.config['DEFAULT_PROJECT_CAPACITY']

            form.sign_off_students.data = current_app.config['DEFAULT_SIGN_OFF_STUDENTS']
            form.enforce_capacity.data = current_app.config['DEFAULT_ENFORCE_CAPACITY']
            form.show_popularity.data = current_app.config['DEFAULT_SHOW_POPULARITY']
            form.dont_clash_presentations.data = current_app.config['DEFAULT_DONT_CLASH_PRESENTATIONS']

            form.use_academic_title.data = current_app.config['DEFAULT_USE_ACADEMIC_TITLE']

            form.random_password.data = True

            license = db.session.query(AssetLicense).filter_by(
                abbreviation=current_app.config['FACULTY_DEFAULT_LICENSE']).first()
            form.default_license.data = license

    return render_template('security/register_user.html', user_form=form, role=role, pane=pane,
                           title='Register a new {r} user account'.format(r=role))


@manage_users.route('/create_student/<string:role>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def create_student(role):
    # check whether role is ok
    if not (role == 'student'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('manage_users.edit_users'))

    form = ConfirmRegisterStudentForm(request.form)

    pane = request.args.get('pane', None)

    if form.validate_on_submit():
        # convert field values to a dictionary
        field_data = form.to_dict(True)
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        # insert extra data for student accounts

        rep_years = form.repeated_years.data
        ry = rep_years if rep_years is not None and rep_years >= 0 else 0
        data = StudentData(id=user.id,
                           exam_number=form.exam_number.data,
                           registration_number=form.registration_number.data,
                           intermitting=form.intermitting.data,
                           cohort=form.cohort.data,
                           programme_id=form.programme.data.id,
                           foundation_year=form.foundation_year.data,
                           repeated_years=ry,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())

        db.session.add(data)
        db.session.commit()

        if pane is None or pane == 'accounts':
            return redirect(url_for('manage_users.edit_users'))
        elif pane == 'faculty':
            return redirect(url_for('manage_users.edit_users_faculty'))
        elif pane == 'students':
            return redirect(url_for('manage_users.edit_users_students'))
        else:
            raise RuntimeError('Unknown user pane "{pane}"'.format(pane=pane))

    else:
        if request.method == 'GET':
            # populate cohort with default value on first load
            config = get_main_config()

            if config:
                form.cohort.data = config.year

            else:
                form.cohort.data = date.today().year

            form.random_password.data = True

            license = db.session.query(AssetLicense) \
                .filter_by(abbreviation=current_app.config['STUDENT_DEFAULT_LICENSE']).first()
            form.default_license.data = license

    return render_template('security/register_user.html', user_form=form, role=role, pane=pane,
                           title='Register a new {r} user account'.format(r=role))


@manage_users.route('/edit_users')
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def edit_users():
    """
    View function that handles listing of all registered users
    :return: HTML string
    """

    filter = request.args.get('filter')

    if filter is None and session.get('accounts_role_filter'):
        filter = session['accounts_role_filter']

    if filter is not None:
        session['accounts_role_filter'] = filter

    return render_template("manage_users/users_dashboard/accounts.html", filter=filter, pane='accounts')


@manage_users.route('/edit_users_students')
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def edit_users_students():
    """
    View function that handles listing of all registered students
    :return: HTML string
    """
    prog_filter = request.args.get('prog_filter')

    if prog_filter is None and session.get('accounts_prog_filter'):
        prog_filter = session['accounts_prog_filter']

    if prog_filter is not None:
        session['accounts_prog_filter'] = prog_filter

    cohort_filter = request.args.get('cohort_filter')

    if cohort_filter is None and session.get('accounts_cohort_filter'):
        cohort_filter = session['accounts_cohort_filter']

    if cohort_filter is not None:
        session['accounts_cohort_filter'] = cohort_filter

    year_filter = request.args.get('year_filter')

    if year_filter is None and session.get('accounts_year_filter'):
        year_filter = session['accounts_year_filter']

    if year_filter is not None:
        session['accounts_year_filter'] = year_filter

    valid_filter = request.args.get('valid_filter')

    if valid_filter is None and session.get('accounts_valid_filter'):
        valid_filter = session['accounts_valid_filter']

    if valid_filter is not None:
        session['accounts_valid_filter'] = valid_filter

    prog_query = db.session.query(StudentData.programme_id).distinct().subquery()
    programmes = db.session.query(DegreeProgramme) \
        .join(prog_query, prog_query.c.programme_id == DegreeProgramme.id) \
        .filter(DegreeProgramme.active == True) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id) \
        .order_by(DegreeType.name.asc(),
                  DegreeProgramme.name.asc()).all()

    cohort_data = db.session.query(StudentData.cohort) \
        .join(User, User.id == StudentData.id) \
        .filter(User.active == True).distinct().all()
    cohorts = [c[0] for c in cohort_data]

    return render_template("manage_users/users_dashboard/students.html", filter=prog_filter, pane='students',
                           prog_filter=prog_filter, cohort_filter=cohort_filter, year_filter=year_filter,
                           valid_filter=valid_filter, programmes=programmes, cohorts=sorted(cohorts))


@manage_users.route('/edit_users_faculty')
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def edit_users_faculty():
    """
    View function that handles listing of all registered faculty
    :return: HTML string
    """
    group_filter = request.args.get('group_filter')

    if group_filter is None and session.get('accounts_group_filter'):
        group_filter = session['accounts_group_filter']

    if group_filter is not None:
        session['accounts_group_filter'] = group_filter

    pclass_filter = request.args.get('pclass_filter')

    if pclass_filter is None and session.get('accounts_pclass_filter'):
        pclass_filter = session['accounts_pclass_filter']

    if pclass_filter is not None:
        session['accounts_pclass_filter'] = pclass_filter

    groups_ids = db.session.query(faculty_affiliations.c.group_id).distinct().subquery()
    groups = db.session.query(ResearchGroup) \
        .join(groups_ids, groups_ids.c.group_id == ResearchGroup.id) \
        .filter(ResearchGroup.active == True) \
        .order_by(ResearchGroup.name.asc()).all()

    pclass_ids = db.session.query(EnrollmentRecord.pclass_id).distinct().subquery()
    pclasses = db.session.query(ProjectClass) \
        .join(pclass_ids, pclass_ids.c.pclass_id == ProjectClass.id) \
        .filter(ProjectClass.active == True) \
        .order_by(ProjectClass.name.asc()).all()

    return render_template("manage_users/users_dashboard/faculty.html", pane='faculty',
                           group_filter=group_filter, pclass_filter=pclass_filter,
                           groups=groups, pclasses=pclasses)


@manage_users.route('/users_ajax', methods=['POST'])
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def users_ajax():
    """
    Return JSON structure representing users table
    :return:
    """
    filter = request.args.get('filter')

    if filter == 'active':
        base_query = db.session.query(User.id).filter_by(active=True)
    elif filter == 'inactive':
        base_query = db.session.query(User.id).filter_by(active=False)
    elif filter == 'student':
        base_query = db.session.query(User.id).filter(User.roles.any(Role.name == 'student'))
    elif filter == 'faculty':
        base_query = db.session.query(User.id).filter(User.roles.any(Role.name == 'faculty'))
    elif filter == 'office':
        base_query = db.session.query(User.id).filter(User.roles.any(Role.name == 'office'))
    elif filter == 'reports':
        base_query = db.session.query(User.id).filter(User.roles.any(Role.name == 'reports'))
    elif filter == 'admin':
        base_query = db.session.query(User.id).filter(User.roles.any(Role.name == 'admin'))
    elif filter == 'root':
        base_query = db.session.query(User.id).filter(User.roles.any(Role.name == 'root'))
    else:
        base_query = db.session.query(User.id)

    name = {'search': func.concat(User.first_name, ' ', User.last_name),
            'order': [User.last_name, User.first_name],
            'search_collation': 'utf8_general_ci'}
    user = {'search': User.username,
            'order': User.username,
            'search_collation': 'utf8_general_ci'}
    email = {'search': User.email,
             'order': User.email,
             'search_collation': 'utf8_general_ci'}
    confirm = {'search': func.date_format(User.confirmed_at, "%a %d %b %Y %H:%M:%S"),
               'order': User.confirmed_at,
               'search_collation': 'utf8_general_ci'}
    active = {'order': User.active}
    details = {'order': [User.last_active, User.current_login_at, User.last_login_at]}

    columns = {'name': name,
               'user': user,
               'email': email,
               'confirm': confirm,
               'active': active,
               'details': details}

    with ServerSideHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.users.build_accounts_data, current_user.id))


@manage_users.route('/users_students_ajax', methods=['POST'])
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def users_students_ajax():
    prog_filter = request.args.get('prog_filter')
    cohort_filter = request.args.get('cohort_filter')
    year_filter = request.args.get('year_filter')
    valid_filter = request.args.get('valid_filter')

    base_query = db.session.query(StudentData.id) \
        .join(User, User.id == StudentData.id) \
        .join(DegreeProgramme, DegreeProgramme.id == StudentData.programme_id) \
        .join(DegreeType, DegreeType.id == DegreeProgramme.type_id)

    flag, prog_value = is_integer(prog_filter)
    if flag:
        base_query = base_query.filter(StudentData.programme_id == prog_value)

    flag, cohort_value = is_integer(cohort_filter)
    if flag:
        base_query = base_query.filter(StudentData.cohort == cohort_value)

    if valid_filter == 'valid':
        base_query = base_query.filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_VALIDATED)
    elif valid_filter == 'not-valid':
        base_query = base_query.filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_QUEUED)
    elif valid_filter == 'reject':
        base_query = base_query.filter(StudentData.workflow_state == WorkflowMixin.WORKFLOW_APPROVAL_REJECTED)

    flag, year_value = is_integer(year_filter)
    if flag:
        base_query = base_query.filter(StudentData.academic_year <= DegreeType.duration,
                                       StudentData.academic_year == year_value)
    elif year_filter == 'grad':
        base_query = base_query.filter(StudentData.academic_year > DegreeType.duration)

    name = {'search': func.concat(User.first_name, ' ', User.last_name),
            'order': [User.last_name, User.first_name],
            'search_collation': 'utf8_general_ci'}
    active = {'order': User.active}
    programme = {'search': DegreeProgramme.name,
                 'order': DegreeProgramme.name,
                 'search_collation': 'utf8_general_ci'}
    cohort = {'search': cast(StudentData.cohort, String),
              'order': StudentData.cohort,
              'search_collation': 'utf8_general_ci'}
    acadyear = {'search': cast(StudentData.academic_year, String),
                'order': StudentData.academic_year,
                'search_collation': 'utf8_general_ci'}

    columns = {'name': name,
               'active': active,
               'programme': programme,
               'cohort': cohort,
               'acadyear': acadyear}

    with ServerSideHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.users.build_student_data, current_user.id))


@manage_users.route('/users_faculty_ajax', methods=['POST'])
@roles_accepted('manage_users', 'root')
@limiter.limit('1000/day')
def users_faculty_ajax():
    group_filter = request.args.get('group_filter')
    pclass_filter = request.args.get('pclass_filter')

    base_query = db.session.query(FacultyData.id) \
        .join(User, User.id == FacultyData.id)

    flag, group_value = is_integer(group_filter)
    if flag:
        base_query = base_query.filter(FacultyData.affiliations.any(id=group_value))

    flag, pclass_value = is_integer(pclass_filter)
    if flag:
        base_query = base_query.filter(FacultyData.enrollments.any(pclass_id=pclass_value))

    name = {'search': func.concat(User.first_name, ' ', User.last_name),
            'order': [User.last_name, User.first_name],
            'search_collation': 'utf8_general_ci'}
    active = {'order': User.active}
    office = {'search': FacultyData.office,
              'order': FacultyData.office,
              'search_collation': 'utf8_general_ci'}

    columns = {'name': name,
               'active': active,
               'office': office}

    with ServerSideHandler(request, base_query, columns) as handler:
        return handler.build_payload(partial(ajax.users.build_faculty_data, current_user.id))


@manage_users.route('/batch_create_users', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
def batch_create_users():
    form = UploadBatchCreateForm(request.form)

    if form.validate_on_submit():
        if 'batch_list' in request.files:
            batch_file = request.files['batch_list']

            trust_cohort = form.trust_cohort.data
            trust_exams = form.trust_exams.data
            trust_registration = form.trust_registration.data
            current_year = form.current_year.data
            ignore_Y0 = form.ignore_Y0.data

            # generate new filename for upload
            incoming_filename = Path(batch_file.filename)
            extension = incoming_filename.suffix.lower()

            if extension in ('.csv'):
                filename, abs_path = make_temporary_asset_filename(ext=extension)
                batch_user_files.save(batch_file, name=str(filename))

                now = datetime.now()
                asset = TemporaryAsset(timestamp=now,
                                       expiry=now + timedelta(days=1),
                                       filename=str(filename))
                asset.grant_user(current_user)

                tk_name = "Process batch user list '{name}'".format(name=incoming_filename)
                tk_description = 'Batch create students from a CSV file'
                uuid = register_task(tk_name, owner=current_user, description=tk_description)

                record = StudentBatch(name=batch_file.filename,
                                      celery_id=uuid,
                                      celery_finished=False,
                                      success=False,
                                      converted=False,
                                      timestamp=datetime.now(),
                                      total_lines=None,
                                      interpreted_lines=None,
                                      trust_cohort=trust_cohort,
                                      trust_exams=trust_exams,
                                      trust_registration=trust_registration,
                                      ignore_Y0=ignore_Y0,
                                      academic_year=current_year)

                try:
                    db.session.add(asset)
                    db.session.add(record)
                    db.session.commit()
                except SQLAlchemyError as e:
                    flash('Could not upload batch user list due to a database issue. '
                          'Please contact an administrator.', 'error')
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    return redirect(url_for('manage_users.batch_create_users'))

                celery = current_app.extensions['celery']

                init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
                final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
                error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

                batch_task = celery.tasks['app.tasks.batch_create.students']

                work = batch_task.si(record.id, asset.id, current_user.id, record.academic_year)

                seq = chain(init.si(uuid, tk_name), work,
                            final.si(uuid, tk_name, current_user.id)).on_error(error.si(uuid, tk_name, current_user.id))
                seq.apply_async(task_id=uuid)

                return redirect(url_for('manage_users.batch_create_users'))

            else:
                flash('Expected batch list to have extension .csv', 'error')

    else:
        if request.method == 'GET':
            form.trust_cohort.data = False
            form.trust_exams.data = False
            form.trust_registration.data = False
            form.ignore_Y0.data = True
            form.current_year.data = get_current_year()

    batches = db.session.query(StudentBatch).all()

    return render_template("manage_users/users_dashboard/batch_create.html", form=form, pane='batch', batches=batches)


@manage_users.route('/terminate_batch/<int:batch_id>')
@roles_accepted('manage_users', 'root')
def terminate_batch(batch_id):
    """
    Terminate read-in of a batch student file
    :param batch_id:
    :return:
    """
    record = StudentBatch.query.get_or_404(batch_id)

    if record.celery_finished:
        flash('Can not terminate batch read-in for "{name}" because it has finished'.format(name=record.name),
              'error')
        return redirect(redirect_url())

    title = 'Terminate batch user creation'
    panel_title = 'Terminate batch user creation for <strong>{name}</strong>'.format(name=record.name)

    action_url = url_for('manage_users.perform_terminate_batch', batch_id=batch_id, url=request.referrer)
    message = '<p>Please confirm that you wish to terminate the batch user creation task ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>' \
        .format(name=record.name)
    submit_label = 'Terminate batch create'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@manage_users.route('/perform_terminate_batch/<int:batch_id>')
@roles_accepted('manage_users', 'root')
def perform_terminate_batch(batch_id):
    record = StudentBatch.query.get_or_404(batch_id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('manage_users.batch_create_users')

    if record.celery_finished:
        flash('Can not terminate batch read-in for "{name}" because it has finished'.format(name=record.name),
              'error')
        return redirect(redirect_url())

    celery = current_app.extensions['celery']
    celery.control.revoke(record.celery_id, terminate=True, signal='SIGUSR1')

    try:
        if not record.celery_finished:
            progress_update(record.celery_id, TaskRecord.TERMINATED, 100, "Task terminated by user", autocommit=False)

        db.session.query(StudentBatchItem).filter_by(parent_id=record.id).delete()

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Can not terminate batch user creation task "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@manage_users.route('/delete_batch/<int:batch_id>')
@roles_accepted('manage_users', 'root')
def delete_batch(batch_id):
    """
    Delete a batch student create job
    :param batch_id:
    :return:
    """
    record = StudentBatch.query.get_or_404(batch_id)

    if not record.celery_finished:
        flash('Can not delete batch creation task for "{name}" because it has not yet '
              'finished'.format(name=record.name), 'error')
        return redirect(redirect_url())

    title = 'Delete batch user creation task'
    panel_title = 'Delete batch user creation for <strong>{name}</strong>'.format(name=record.name)

    action_url = url_for('manage_users.perform_delete_batch', batch_id=batch_id, url=request.referrer)
    message = '<p>Please confirm that you wish to delete the batch user creation task ' \
              '<strong>{name}</strong>.</p>' \
              '<p>This action cannot be undone.</p>' \
        .format(name=record.name)
    submit_label = 'Delete batch data'

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@manage_users.route('/perform_delete_batch/<int:batch_id>')
@roles_accepted('manage_users', 'root')
def perform_delete_batch(batch_id):
    record = StudentBatch.query.get_or_404(batch_id)

    url = request.args.get('url', None)
    if url is None:
        url = url_for('manage_users.batch_create_users')

    if not record.celery_finished:
        flash('Can not delete batch creation task for "{name}" because it has not yet '
              'finished'.format(name=record.name), 'error')
        return redirect(redirect_url())

    try:
        db.session.query(StudentBatchItem).filter_by(parent_id=record.id).delete()

        db.session.delete(record)
        db.session.commit()

    except SQLAlchemyError as e:
        db.session.rollback()
        flash('Can not delete batch user creation task "{name}" due to a database error. '
              'Please contact a system administrator.'.format(name=record.name),
              'error')
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)

    return redirect(url)


@manage_users.route('/view_batch_data/<int:batch_id>')
@roles_accepted('manage_users', 'root')
def view_batch_data(batch_id):
    record = StudentBatch.query.get_or_404(batch_id)

    filter = request.args.get('filter')

    if filter is None and session.get('manage_users_batch_view_filter'):
        filter = session['manage_users_batch_view_filter']

    if filter not in ['all', 'new', 'modified', 'both']:
        filter = 'all'

    if filter is not None:
        session['manage_users_batch_view_filter'] = filter

    return render_template('manage_users/users_dashboard/view_batch.html', record=record, batch_id=batch_id,
                           filter=filter)


@manage_users.route('/view_batch_data_ajax/<int:batch_id>')
@roles_accepted('manage_users', 'root')
def view_batch_data_ajax(batch_id):
    record = StudentBatch.query.get_or_404(batch_id)

    filter = request.args.get('filter')

    items = db.session.query(StudentBatchItem).filter_by(parent_id=record.id).all()

    if filter == 'new':
        items = [x.id for x in items if x.existing_record is None]
    elif filter == 'modified':
        items = [x.id for x in items if len(x.warnings) > 0 and x.existing_record is not None]
    elif filter == 'both':
        items = [x.id for x in items if (len(x.warnings) > 0 and x.existing_record is not None)
                 or x.existing_record is None]
    else:
        items = [x.id for x in items]

    return ajax.users.build_view_batch_data(items)


@manage_users.route('/edit_batch_item/<int:item_id>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
def edit_batch_item(item_id):
    record: StudentBatchItem = StudentBatchItem.query.get_or_404(item_id)

    EditStudentBatchItemForm = EditStudentBatchItemFormFactory(record)
    form = EditStudentBatchItemForm(obj=record)
    form.batch_item = record

    if form.validate_on_submit():
        record.user_id = form.user_id.data
        record.email = form.email.data
        record.last_name = form.last_name.data
        record.first_name = form.first_name.data
        record.exam_number = form.exam_number.data
        record.registration_number = form.registration_number.data
        record.cohort = form.cohort.data
        record.programme_id = form.programme.data.id
        record.foundation_year = form.foundation_year.data
        record.repeated_years = form.repeated_years.data
        record.intermitting = form.intermitting.data

        existing_record = db.session.query(User) \
            .join(StudentData, StudentData.id == User.id) \
            .filter(or_(func.lower(User.email) == func.lower(record.email),
                        func.lower(User.username) == func.lower(record.user_id),
                        StudentData.exam_number == record.exam_number,
                        StudentData.registration_number == record.registration_number)).first()

        record.existing_id = existing_record.id if existing_record is not None else None

        if existing_record.email.lower() != record.email.lower():
            record.dont_convert = True

        db.session.commit()

        return redirect(url_for('manage_users.view_batch_data', batch_id=record.parent.id))

    return render_template('manage_users/users_dashboard/edit_batch_item.html', form=form, record=record,
                           title='Edit batch item')


@manage_users.route('/mark_batch_item_convert/<int:item_id>')
@roles_accepted('manage_users', 'root')
def mark_batch_item_convert(item_id):
    item = StudentBatchItem.query.get_or_404(item_id)

    item.dont_convert = False
    db.session.commit()

    return redirect(redirect_url())


@manage_users.route('/mark_batch_item_dont_convert/<int:item_id>')
@roles_accepted('manage_users', 'root')
def mark_batch_item_dont_convert(item_id):
    item = StudentBatchItem.query.get_or_404(item_id)

    item.dont_convert = True
    db.session.commit()

    return redirect(redirect_url())


@manage_users.route('/import_batch/<int:batch_id>')
@roles_accepted('manage_users', 'root')
def import_batch(batch_id):
    record = StudentBatch.query.get_or_404(batch_id)

    tk_name = 'Import batch user list "{name}"'.format(name=record.name)
    tk_description = 'Batch create students from a CSV file'
    uuid = register_task(tk_name, owner=current_user, description=tk_description)

    celery = current_app.extensions['celery']

    init = celery.tasks['app.tasks.user_launch.mark_user_task_started']
    final = celery.tasks['app.tasks.user_launch.mark_user_task_ended']
    error = celery.tasks['app.tasks.user_launch.mark_user_task_failed']

    import_batch_item = celery.tasks['app.tasks.batch_create.import_batch_item']
    import_finalize = celery.tasks['app.tasks.batch_create.import_finalize']
    import_error = celery.tasks['app.tasks.batch_create.import_error']
    backup = celery.tasks['app.tasks.backup.backup']

    work_group = group(import_batch_item.si(item.id, current_user.id) for item in record.items)
    work = chain(backup.si(current_user.id, type=BackupRecord.BATCH_IMPORT_FALLBACK, tag='batch_import',
                           description='Rollback snapshot for batch import '
                                       '"{name}"'.format(name=record.name)),
                 work_group,
                 import_finalize.s(record.id, current_user.id)).on_error(import_error.si(current_user.id))

    seq = chain(init.si(uuid, tk_name), work,
                final.si(uuid, tk_name, current_user.id)).on_error(error.si(uuid, tk_name, current_user.id))
    seq.apply_async(task_id=uuid)

    return redirect(redirect_url())


@manage_users.route('/make_admin/<int:id>')
@roles_accepted('manage_users', 'root')
def make_admin(id):
    """
    View function to add admin role
    :param id:
    :return:
    """
    current_app.logger.info('Arrived in make_admin(); request.referrer = {req}'.format(req=request.referrer))

    user = User.query.get_or_404(id)

    if not user.is_active:
        flash('Inactive users cannot be given admin privileges.')
        return redirect(redirect_url())

    current_app.logger.info('Preparing to add admin role in make_admin(); request.referrer = {req}'.format(req=request.referrer))

    _datastore.add_role_to_user(user, 'admin')
    _datastore.commit()

    current_app.logger.info('Preparing to redirect in make_admin(); request.referrer = {req}'.format(req=request.referrer))

    return redirect(redirect_url())


@manage_users.route('/remove_admin/<int:id>')
@roles_accepted('manage_users', 'root')
def remove_admin(id):
    """
    View function to remove admin role
    :param id:
    :return:
    """
    current_app.logger.info('Arrived in remove_admin(); request.referrer = {req}'.format(req=request.referrer))

    user = User.query.get_or_404(id)

    if user.has_role('root'):
        flash('Administration privileges cannot be removed from a system administrator.')
        return redirect(redirect_url())

    current_app.logger.info('Preparing to remove admin role in remove_admin(); request.referrer = {req}'.format(req=request.referrer))

    _datastore.remove_role_from_user(user, 'admin')
    _datastore.commit()

    current_app.logger.info('Preparing to redirect in remove_admin(); request.referrer = {req}'.format(req=request.referrer))

    return redirect(redirect_url())


@manage_users.route('/make_root/<int:id>')
@roles_required('root')
def make_root(id):
    """
    View function to add sysadmin=root role
    :param id:
    :return:
    """
    current_app.logger.info('Arrived in make_root(); request.referrer = {req}'.format(req=request.referrer))

    user = User.query.get_or_404(id)

    if not user.is_active:
        flash('Inactive users cannot be given sysadmin privileges.')
        return redirect(redirect_url())

    current_app.logger.info('Preparing to add root role in make_root(); request.referrer = {req}'.format(req=request.referrer))

    _datastore.add_role_to_user(user, 'admin')
    _datastore.add_role_to_user(user, 'root')
    _datastore.commit()

    current_app.logger.info('Preparing to redirect in make_root(); request.referrer = {req}'.format(req=request.referrer))

    return redirect(redirect_url())


@manage_users.route('/remove_root/<int:id>')
@roles_required('root')
def remove_root(id):
    """
    View function to remove sysadmin=root role
    :param id:
    :return:
    """
    current_app.logger.info('Arrived in remove_root(); request.referrer = {req}'.format(req=request.referrer))

    user = User.query.get_or_404(id)

    current_app.logger.info('Preparing to remove root role in make_root(); request.referrer = {req}'.format(req=request.referrer))

    _datastore.remove_role_from_user(user, 'root')
    _datastore.commit()

    current_app.logger.info('Preparing to redirect in remove_root(); request.referrer = {req}'.format(req=request.referrer))

    return redirect(redirect_url())


@manage_users.route('/activate_user/<int:id>')
@roles_accepted('manage_users', 'root')
def activate_user(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    _datastore.activate_user(user)
    _datastore.commit()

    return redirect(redirect_url())


@manage_users.route('/deactivate_user/<int:id>')
@roles_accepted('manage_users', 'root')
def deactivate_user(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if user.has_role('manage_users') or user.has_role('root'):
        flash('Administrative users cannot be made inactive. '
              'Remove administration status before marking the user as inactive.')
        return redirect(redirect_url())

    _datastore.deactivate_user(user)
    _datastore.commit()

    return redirect(redirect_url())


@manage_users.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
def edit_user(id):
    """
    View function to edit an individual user account
    :param id:
    :return:
    """
    user = User.query.get_or_404(id)

    pane = request.args.get('pane', None)

    if user.has_role('office'):
        return redirect(url_for('manage_users.edit_office', id=id, pane=pane))

    elif user.has_role('faculty'):
        return redirect(url_for('manage_users.edit_faculty', id=id, pane=pane))

    elif user.has_role('student'):
        return redirect(url_for('manage_users.edit_student', id=id, pane=pane))

    flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
    return redirect(url_for('manage_users.edit_users'))


def _resend_confirm_email(user):
    confirmation_link, token = generate_confirmation_link(user)
    do_flash(*get_message('CONFIRM_REGISTRATION', email=user.email))

    user_registered.send(current_app._get_current_object(),
                         user=user, confirm_token=token)

    if config_value('SEND_REGISTER_EMAIL'):
        send_mail(config_value('EMAIL_SUBJECT_REGISTER'), user.email,
                  'welcome', user=user, confirmation_link=confirmation_link)


@manage_users.route('/edit_office/<int:id>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
def edit_office(id):

    user = User.query.get_or_404(id)
    form = EditOfficeForm(obj=user)

    form.user = user

    if form.validate_on_submit():

        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.theme = form.theme.data

        _datastore.commit()

        if resend_confirmation:
            _resend_confirm_email(user)

        return redirect(url_for('manage_users.edit_users'))

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account')


@manage_users.route('/edit_faculty/<int:id>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
def edit_faculty(id):

    user = User.query.get_or_404(id)
    form = EditFacultyForm(obj=user)

    form.user = user

    data = FacultyData.query.get_or_404(id)

    pane = request.args.get('pane', default=None)

    if form.validate_on_submit():
        # determine whether to resend confirmation email
        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.theme = form.theme.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data
        data.project_capacity = form.project_capacity.data if form.enforce_capacity.data else None
        data.enforce_capacity = form.enforce_capacity.data
        data.show_popularity = form.show_popularity.data
        data.dont_clash_presentations = form.dont_clash_presentations.data
        data.office = form.office.data

        data.CATS_supervision = form.CATS_supervision.data
        data.CATS_marking = form.CATS_marking.data
        data.CATS_presentation = form.CATS_presentation.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        _datastore.commit()

        if resend_confirmation:
            _resend_confirm_email(user)

        if pane is None or pane == 'accounts':
            return redirect(url_for('manage_users.edit_users'))
        elif pane == 'faculty':
            return redirect(url_for('manage_users.edit_users_faculty'))
        elif pane == 'students':
            return redirect(url_for('manage_users.edit_users_students'))
        else:
            raise RuntimeWarning('Unknown user dashboard pane')

    else:
        # populate default values if this is the first time we are rendering the form,
        # distinguished by the method being 'GET' rather than 'POST'
        if request.method == 'GET':
            form.academic_title.data = data.academic_title
            form.use_academic_title.data = data.use_academic_title
            form.sign_off_students.data = data.sign_off_students
            form.project_capacity.data = data.project_capacity
            form.enforce_capacity.data = data.enforce_capacity
            form.show_popularity.data = data.show_popularity
            form.dont_clash_presentations.data = data.dont_clash_presentations
            form.office.data = data.office

            form.CATS_supervision.data = data.CATS_supervision
            form.CATS_marking.data = data.CATS_marking
            form.CATS_presentation.data = data.CATS_presentation

            if form.project_capacity.data is None and form.enforce_capacity.data:
                form.project_capacity.data = current_app.config['DEFAULT_PROJECT_CAPACITY']

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account',
                           pane=pane)


@manage_users.route('/edit_student/<int:id>', methods=['GET', 'POST'])
@roles_accepted('manage_users', 'root')
def edit_student(id):

    user: User = User.query.get_or_404(id)
    form: EditStudentForm = EditStudentForm(obj=user)

    form.user = user

    data: StudentData = StudentData.query.get_or_404(id)

    pane = request.args.get('pane', default=None)
    url = request.args.get('url', default=None)

    if form.validate_on_submit():
        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.theme = form.theme.data

        rep_years = form.repeated_years.data
        ry = rep_years if rep_years is not None and rep_years >= 0 else 0

        data.foundation_year = form.foundation_year.data
        data.intermitting = form.intermitting.data
        data.exam_number = form.exam_number.data
        data.registration_number = form.registration_number.data
        data.cohort = form.cohort.data
        data.repeated_years = ry
        data.programme_id = form.programme.data.id

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        # validation workflow fields are handled by SQLAlchemy listeners
        # see models.py

        _datastore.commit()

        if resend_confirmation:
            _resend_confirm_email(user)

        # if a return URL is supplied, it takes precedence over a named pane
        if url is not None:
            return redirect(url)
        elif pane is None or pane == 'accounts':
            return redirect(url_for('manage_users.edit_users'))
        elif pane == 'faculty':
            return redirect(url_for('manage_users.edit_users_faculty'))
        elif pane == 'students':
            return redirect(url_for('manage_users.edit_users_students'))
        else:
            raise RuntimeWarning('Unknown user dashboard pane')

    else:

        # populate default values if this is the first time we are rendering the form,
        # distinguished by the method being 'GET' rather than 'POST'
        if request.method == 'GET':
            form.foundation_year.data = data.foundation_year
            form.intermitting.data = data.intermitting
            form.exam_number.data = data.exam_number
            form.registration_number.data = data.registration_number
            form.cohort.data = data.cohort
            form.repeated_years.data = data.repeated_years
            form.programme.data = data.programme

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account',
                           pane=pane, url=url)


@manage_users.route('/edit_affiliations/<int:id>')
@roles_accepted('manage_users', 'root')
def edit_affiliations(id):
    """
    View to edit research group affiliations for a faculty member
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    data = FacultyData.query.get_or_404(id)
    research_groups = ResearchGroup.query.filter_by(active=True)

    create = request.args.get('create', default=None)
    pane = request.args.get('pane', default=None)

    return render_template('manage_users/edit_affiliations.html', user=user, data=data, research_groups=research_groups,
                           create=create, pane=pane)


@manage_users.route('/edit_enrollments/<int:id>')
@roles_accepted('manage_users', 'root')
def edit_enrollments(id):
    """
    View to edit project class enrollments for a faculty member
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    data = FacultyData.query.get_or_404(id)
    project_classes = ProjectClass.query.filter_by(active=True)

    create = request.args.get('create', default=None)
    pane = request.args.get('pane', default=None)

    return render_template('manage_users/edit_enrollments.html', user=user, data=data, project_classes=project_classes,
                           create=create, pane=pane)


@manage_users.route('/edit_enrollment/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'manage_users', 'root')
def edit_enrollment(id):
    """
    Edit enrollment details
    :param id:
    :return:
    """
    # check logged-in user is administrator or a convenor for the project
    record = EnrollmentRecord.query.get_or_404(id)

    if not validate_is_convenor(record.pclass):
        return redirect(redirect_url())

    form = EnrollmentRecordForm(obj=record)

    url = request.args.get('url')
    if url is None:
        url = home_dashboard_url()

    if form.validate_on_submit():
        old_supervisor_state = record.supervisor_state
        old_presentations_state = record.presentations_state

        record.supervisor_state = form.supervisor_state.data
        record.supervisor_reenroll = None if record.supervisor_state != EnrollmentRecord.SUPERVISOR_SABBATICAL \
            else form.supervisor_reenroll.data
        record.supervisor_comment = form.supervisor_comment.data

        record.marker_state = form.marker_state.data
        record.marker_reenroll = None if record.marker_state != EnrollmentRecord.MARKER_SABBATICAL \
            else form.marker_reenroll.data
        record.marker_comment = form.marker_comment.data

        record.presentations_state = form.presentations_state.data
        record.presentations_reenroll = None if record.presentations_state != EnrollmentRecord.PRESENTATIONS_SABBATICAL \
            else form.presentations_reenroll.data
        record.presentations_comment = form.presentations_comment.data

        record.last_edit_id = current_user.id
        record.last_edit_timestamp = datetime.now()

        db.session.commit()

        celery = current_app.extensions['celery']

        # if supervisor enrollment state has changed, check whether we need to adjust our
        # project confirmation state
        if old_supervisor_state != record.supervisor_state:
            adjust_task = celery.tasks['app.tasks.issue_confirm.enroll_adjust']
            adjust_task.apply_async(args=(record.id, old_supervisor_state, get_current_year()))

        # if presentation enrollment state has changed, check whether we need to adjust our
        # availability status for any presentation assessment events.
        # To do that we kick off a background task via celery.
        if old_presentations_state != record.presentations_state:
            adjust_task = celery.tasks['app.tasks.availability.adjust']
            adjust_task.apply_async(args=(record.id, get_current_year()))

        return redirect(url)

    return render_template('manage_users/edit_enrollment.html', record=record, form=form, url=url)


@manage_users.route('/enroll_projects_assessor/<int:id>/<int:pclassid>')
@roles_accepted('manage_users', 'root')
def enroll_projects_assessor(id, pclassid):
    celery = current_app.extensions['celery']
    subscribe_task = celery.tasks['app.tasks.assessors.projects']

    subscribe_task.apply_async(args=(id, pclassid, current_user.id))

    return redirect(redirect_url())


@manage_users.route('/enroll_liveprojects_assessor/<int:id>/<int:pclassid>')
@roles_accepted('manage_users', 'root')
def enroll_liveprojects_assessor(id, pclassid):
    celery = current_app.extensions['celery']
    subscribe_task = celery.tasks['app.tasks.assessors.live_projects']
    adjust_task = celery.tasks['app.tasks.availability.adjust']

    # for live projects we follow the subscription with use of availability.adjust, which will
    # check whether the change in assessor status means that an attendance request should be
    # generated for any active assessments
    current_year = get_current_year()
    tasks = chain(subscribe_task.si(id, pclassid, current_year, current_user.id),
                  adjust_task.si(id, current_year))
    tasks.apply_async()

    return redirect(redirect_url())


@manage_users.route('/add_affiliation/<int:userid>/<int:groupid>')
@roles_accepted('manage_users', 'root')
def add_affiliation(userid, groupid):
    """
    View to add a research group affiliation to a faculty member
    :param userid:
    :param groupid:
    :return:
    """
    data = FacultyData.query.get_or_404(userid)
    group = ResearchGroup.query.get_or_404(groupid)

    if group not in data.affiliations:
        data.add_affiliation(group, autocommit=True)

    return redirect(redirect_url())


@manage_users.route('/remove_affiliation/<int:userid>/<int:groupid>')
@roles_accepted('manage_users', 'root')
def remove_affiliation(userid, groupid):
    """
    View to remove a research group affiliation to a faculty member
    :param userid:
    :param groupid:
    :return:
    """
    data = FacultyData.query.get_or_404(userid)
    group = ResearchGroup.query.get_or_404(groupid)

    if group in data.affiliations:
        data.remove_affiliation(group, autocommit=True)

    return redirect(redirect_url())


@manage_users.route('/add_enrollment/<int:userid>/<int:pclassid>')
@roles_accepted('manage_users', 'root')
def add_enrollment(userid, pclassid):
    """
    View to add a project class enrollment to a faculty member
    :param userid:
    :param pclassid:
    :return:
    """
    data = FacultyData.query.get_or_404(userid)
    pclass = ProjectClass.query.get_or_404(pclassid)

    if not data.is_enrolled(pclass):
        data.add_enrollment(pclass)

    return redirect(redirect_url())


@manage_users.route('/remove_enrollment/<int:userid>/<int:pclassid>')
@roles_accepted('manage_users', 'root')
def remove_enrollment(userid, pclassid):
    """
    View to remove a project class enrollment from a faculty member
    :param userid:
    :param pclassid:
    :return:
    """
    data = FacultyData.query.get_or_404(userid)
    pclass = ProjectClass.query.get_or_404(pclassid)

    if data.is_enrolled(pclass):
        data.remove_enrollment(pclass)

    return redirect(redirect_url())


@manage_users.route('/edit_roles')
@roles_required('root')
def edit_roles():
    """
    Display list of roles
    :return:
    """
    return render_template('manage_users/edit_roles.html')


@manage_users.route('/edit_roles_ajax')
@roles_required('root')
def edit_roles_ajax():
    """
    Ajax data point for roles list
    :return:
    """
    roles = db.session.query(Role).all()
    return ajax.admin.roles_data(roles)


@manage_users.route('/add_role', methods=['GET', 'POST'])
@roles_required('root')
def add_role():
    """
    Add a new user role
    :return:
    """
    form = AddRoleForm(request.form)

    if form.validate_on_submit():
        data = Role(name=form.name.data,
                    description=form.description.data,
                    colour=form.colour.data,)
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('manage_users.edit_roles'))

    return render_template('manage_users/edit_role.html', title='Edit role', role_form=form)


@manage_users.route('/edit_role/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_role(id):
    """
    Edit an existing role
    :param id:
    :return:
    """
    data = Role.query.get_or_404(id)

    form = EditRoleForm(obj=data)
    form.role = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.description = form.description.data
        data.colour = form.colour.data
        db.session.commit()

        return redirect(url_for('manage_users.edit_roles'))

    return render_template('manage_users/edit_role.html', role=data, title='Edit role', role_form=form)


@manage_users.route('/assign_roles/<int:id>')
@roles_required('root')
def assign_roles(id):
    """
    Assign roles to a user
    :param id:
    :return:
    """
    data = User.query.get_or_404(id)

    pane = request.args.get('pane', default=None)

    roles = db.session.query(Role) \
        .filter(Role.name != 'root', Role.name != 'admin',
                Role.name != 'faculty', Role.name != 'student', Role.name != 'office').all()

    return render_template('manage_users/users_dashboard/assign_roles.html', roles=roles, user=data, pane=pane)


@manage_users.route('/attach_role/<int:user_id>/<int:role_id>')
@roles_required('root')
def attach_role(user_id, role_id):
    """
    Attach a role to a user
    :param user_id:
    :param role_id:
    :return:
    """
    data = User.query.get_or_404(user_id)
    role = Role.query.get_or_404(role_id)

    if role.name == 'root' or role.name == 'admin':
        flash('Admin roles cannot be assigned through the API', 'error')
        return redirect(redirect_url())

    if role.name == 'faculty' or role.name == 'office' or role.name == 'student':
        flash('Account types cannot be assigned through the API', 'error')
        return redirect(redirect_url())

    _datastore.add_role_to_user(data, role.name)
    _datastore.commit()

    return redirect(redirect_url())


@manage_users.route('/remove_role/<int:user_id>/<int:role_id>')
@roles_required('root')
def remove_role(user_id, role_id):
    """
    Remove a role from a user
    :param user_id:
    :param role_id:
    :return:
    """
    data = User.query.get_or_404(user_id)
    role = Role.query.get_or_404(role_id)

    if role.name == 'root' or role.name == 'admin':
        flash('Admin roles cannot be assigned through the API', 'error')
        return redirect(redirect_url())

    if role.name == 'faculty' or role.name == 'office' or role.name == 'student':
        flash('Account types cannot be assigned through the API', 'error')
        return redirect(redirect_url())

    _datastore.remove_role_from_user(data, role.name)
    _datastore.commit()

    return redirect(redirect_url())
