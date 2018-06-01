#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template, redirect, url_for, flash, request, jsonify
from werkzeug.local import LocalProxy
from flask_security import login_required, roles_required, roles_accepted, current_user, logout_user, login_user
from flask_security.utils import config_value, get_url, find_redirect, validate_redirect_url, get_message, do_flash, \
    send_mail
from flask_security.confirmable import generate_confirmation_link
from flask_security.signals import user_registered

from .actions import register_user
from .forms import RoleSelectForm, \
    ConfirmRegisterOfficeForm, ConfirmRegisterFacultyForm, ConfirmRegisterStudentForm, \
    EditOfficeForm, EditFacultyForm, EditStudentForm, \
    AddResearchGroupForm, EditResearchGroupForm, \
    AddDegreeTypeForm, EditDegreeTypeForm, \
    AddDegreeProgrammeForm, EditDegreeProgrammeForm, \
    AddTransferrableSkillForm, EditTransferableSkillForm, \
    AddProjectClassForm, EditProjectClassForm, \
    AddSupervisorForm, EditSupervisorForm, \
    FacultySettingsForm, EmailLogForm, \
    AddMessageForm, EditMessageForm, \
    ScheduleTypeForm, AddIntervalScheduledTask, AddCrontabScheduledTask, \
    EditIntervalScheduledTask, EditCrontabScheduledTask

from ..models import db, MainConfig, User, FacultyData, StudentData, ResearchGroup, DegreeType, DegreeProgramme, \
    TransferableSkill, ProjectClass, ProjectClassConfig, Supervisor, Project, EmailLog, MessageOfTheDay, \
    DatabaseSchedulerEntry, IntervalSchedule, CrontabSchedule

from ..utils import get_main_config, get_current_year, home_dashboard

from . import admin

from datetime import date, datetime, timedelta

from celery import schedules

_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


def _check_admin_or_convenor():
    if current_user.has_role('admin') or current_user.has_role('root'):
        return True

    if current_user.has_role('faculty') and current_user.convenor_for and current_user.convenor_for.first() is not Null:
        return True

    flash('This operation is only available to administrative users and project class convenors')
    return False


@admin.route('/create_user', methods=['GET', 'POST'])
@roles_required('admin')
def create_user():
    """
    View function that handles creation of a user account
    """

    # check whether any active degree programmes exist, and raise an error if not
    if not DegreeProgramme.query.filter_by(active=True).first():
        flash(
            'No degree programmes are available. Set up at least one active degree programme before adding new users.')
        return redirect(request.referrer)

    # first task is to capture the user role
    form = RoleSelectForm(request.form)

    if form.validate_on_submit():

        # get role and redirect to appropriate form
        role = form.roles.data

        if role == 'office':

            return redirect(url_for('admin.create_office', role=role))

        elif role == 'faculty':

            return redirect(url_for('admin.create_faculty', role=role))

        elif role == 'student':

            return redirect(url_for('admin.create_student', role=role))

        else:

            flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
            return redirect(url_for('admin.edit_users'))

    return render_template('security/register_role.html', role_form=form, title='Select new account role')


@admin.route('/create_office/<string:role>', methods=['GET', 'POST'])
@roles_required('admin')
def create_office(role):
    """
    Create an 'office' user
    :param role:
    :return:
    """

    # check whether role is ok
    if not (role == 'office'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('admin.edit_users'))

    form = ConfirmRegisterOfficeForm(request.form)

    if form.validate_on_submit():
        # convert field values to a dictionary
        field_data = form.to_dict()
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        db.session.commit()

        return redirect(url_for('admin.edit_users'))

    return render_template('security/register_user.html', user_form=form, role=role,
                           title='Register a new {r} user account'.format(r=role))


@admin.route('/create_faculty/<string:role>', methods=['GET', 'POST'])
@roles_required('admin')
def create_faculty(role):
    """
    Create a 'faculty' user
    :param role:
    :return:
    """

    # check whether role is ok
    if not (role == 'faculty'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('admin.edit_users'))

    form = ConfirmRegisterFacultyForm(request.form)

    if form.validate_on_submit():
        # convert field values to a dictionary
        field_data = form.to_dict()
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        # insert extra data for faculty accounts

        data = FacultyData(id=user.id,
                           academic_title=form.academic_title.data,
                           use_academic_title=form.use_academic_title.data,
                           sign_off_students=form.sign_off_students.data,
                           office=form.office.data,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())
        db.session.add(data)

        db.session.commit()

        return redirect(url_for('admin.edit_users'))

    return render_template('security/register_user.html', user_form=form, role=role,
                           title='Register a new {r} user account'.format(r=role))


@admin.route('/create_student/<string:role>', methods=['GET', 'POST'])
@roles_required('admin')
def create_student(role):

    # check whether role is ok
    if not (role == 'student'):
        flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
        return redirect(url_for('admin.edit_users'))

    form = ConfirmRegisterStudentForm(request.form)

    if form.validate_on_submit():

        # convert field values to a dictionary
        field_data = form.to_dict()
        field_data['roles'] = [role]

        user = register_user(**field_data)
        form.user = user

        # insert extra data for student accounts

        data = StudentData(id=user.id,
                           exam_number=form.exam_number.data,
                           cohort=form.cohort.data,
                           programme=form.programme.data,
                           creator_id=current_user.id,
                           creation_timestamp=datetime.now())
        db.session.add(data)

        db.session.commit()

        return redirect(url_for('admin.edit_users'))

    else:

        if request.method == 'GET':

            # populate cohort with default value on first load
            config = get_main_config()

            if config:

                form.cohort.data = config.year

            else:

                form.cohort.data = date.today().year

    return render_template('security/register_user.html', user_form=form, role=role,
                           title='Register a new {r} user account'.format(r=role))


@admin.route('/edit_users')
@roles_required('admin')
def edit_users():
    """
    View function that handles listing of all registered users
    :return: HTML string
    """

    users = User.query.all()

    return render_template("admin/edit_users.html", users=users)


@admin.route('/make_admin/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
def make_admin(id):
    """
    View function to add admin role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if not user.is_active:
        flash('Inactive users cannot be given admin privileges.')
        return redirect(request.referrer)

    _datastore.add_role_to_user(user, 'admin')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/remove_admin/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
def remove_admin(id):
    """
    View function to remove admin role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if user.has_role('root'):
        flash('Administration privileges cannot be removed from a system administrator.')
        return redirect(request.referrer)

    _datastore.remove_role_from_user(user, 'admin')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/make_root/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def make_root(id):
    """
    View function to add sysadmin=root role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if not user.is_active:
        flash('Inactive users cannot be given sysadmin privileges.')
        return redirect(request.referrer)

    _datastore.add_role_to_user(user, 'admin')
    _datastore.add_role_to_user(user, 'root')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/remove_root/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def remove_root(id):
    """
    View function to remove sysadmin=root role
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    _datastore.remove_role_from_user(user, 'root')
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/activate_user/<int:id>')
@roles_required('admin')
def activate_user(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    _datastore.activate_user(user)
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_user/<int:id>')
@roles_required('admin')
def deactivate_user(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if user.has_role('admin') or user.has_role('root'):
        flash('Administrative users cannot be made inactive. '
              'Remove administration status before marking the user as inactive.')
        return redirect(request.referrer)

    _datastore.deactivate_user(user)
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
def edit_user(id):
    """
    View function to edit an individual user account
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if user.has_role('office'):

        return redirect(url_for('admin.edit_office', id=id))

    elif user.has_role('faculty'):

        return redirect(url_for('admin.edit_faculty', id=id))

    elif user.has_role('student'):

        return redirect(url_for('admin.edit_student', id=id))

    flash('Requested role was not recognized. If this error persists, please contact the system administrator.')
    return redirect(url_for('admin.edit_users'))


def _resend_confirm_email(user):
    confirmation_link, token = generate_confirmation_link(user)
    do_flash(*get_message('CONFIRM_REGISTRATION', email=user.email))

    user_registered.send(current_app._get_current_object(),
                         user=user, confirm_token=token)

    if config_value('SEND_REGISTER_EMAIL'):
        send_mail(config_value('EMAIL_SUBJECT_REGISTER'), user.email,
                  'welcome', user=user, confirmation_link=confirmation_link)


@admin.route('/edit_office/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
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

        _datastore.commit()

        flash('All changes saved')

        if resend_confirmation:
            _resend_confirm_email(user)

        return redirect(url_for('admin.edit_users'))

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account')


@admin.route('/edit_faculty/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
def edit_faculty(id):

    user = User.query.get_or_404(id)
    form = EditFacultyForm(obj=user)

    form.user = user

    data = FacultyData.query.get_or_404(id)

    if form.validate_on_submit():

        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data
        data.office = form.office.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        _datastore.commit()

        flash('All changes saved')

        if resend_confirmation:
            _resend_confirm_email(user)

        return redirect(url_for('admin.edit_users'))

    else:

        # populate default values if this is the first time we are rendering the form,
        # distinguished by the method being 'GET' rather than 'POST'
        if request.method == 'GET':

            form.academic_title.data = data.academic_title
            form.use_academic_title.data = data.use_academic_title
            form.sign_off_students.data = data.sign_off_students
            form.office.data = data.office

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account')


@admin.route('/edit_student/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
def edit_student(id):

    user = User.query.get_or_404(id)
    form = EditStudentForm(obj=user)

    form.user = user

    data = StudentData.query.get_or_404(id)

    if form.validate_on_submit():

        resend_confirmation = False
        if form.email.data != user.email and form.ask_confirm.data is True:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data

        data.exam_number = form.exam_number.data
        data.cohort = form.cohort.data
        data.programme_id = form.programme.data.id
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        _datastore.commit()

        flash('All changes saved')

        if resend_confirmation:
            _resend_confirm_email(user)

        return redirect(url_for('admin.edit_users'))

    else:

        # populate default values if this is the first time we are rendering the form,
        # distinguished by the method being 'GET' rather than 'POST'
        if request.method == 'GET':

            form.exam_number.data = data.exam_number
            form.cohort.data = data.cohort
            form.programme.data = data.programme

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account')


@admin.route('/edit_affiliations/<int:id>')
@roles_required('admin')
def edit_affiliations(id):
    """
    View to edit research group affiliations for a faculty member
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    data = FacultyData.query.get_or_404(id)
    research_groups = ResearchGroup.query.filter_by(active=True)

    return render_template('admin/edit_affiliations.html', user=user, data=data, research_groups=research_groups)


@admin.route('/edit_enrollments/<int:id>')
@roles_required('admin')
def edit_enrollments(id):
    """
    View to edit project class enrollments for a faculty member
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    data = FacultyData.query.get_or_404(id)
    project_classes = ProjectClass.query.filter_by(active=True)

    return render_template('admin/edit_enrollments.html', user=user, data=data, project_classes=project_classes)


@admin.route('/add_affiliation/<int:userid>/<int:groupid>')
@roles_required('admin')
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
        data.add_affiliation(group)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/remove_affiliation/<int:userid>/<int:groupid>')
@roles_required('admin')
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
        data.remove_affiliation(group)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/add_enrollment/<int:userid>/<int:pclassid>')
@roles_required('admin')
def add_enrollment(userid, pclassid):
    """
    View to add a project class enrollment to a faculty member
    :param userid:
    :param pclassid:
    :return:
    """

    data = FacultyData.query.get_or_404(userid)
    pclass = ProjectClass.query.get_or_404(pclassid)

    if pclass not in data.enrollments:
        data.add_enrollment(pclass)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/remove_enrollment/<int:userid>/<int:pclassid>')
@roles_required('admin')
def remove_enrollment(userid, pclassid):
    """
    View to remove a project class enrollment from a faculty member
    :param userid:
    :param pclassid:
    :return:
    """

    data = FacultyData.query.get_or_404(userid)
    pclass = ProjectClass.query.get_or_404(pclassid)

    if pclass in data.enrollments:
        data.remove_enrollment(pclass)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/my_affiliations')
@roles_required('faculty')
def my_affiliations():
    """
    Allow a faculty member to adjust their own affiliations without admin privileges
    :return:
    """

    data = FacultyData.query.get_or_404(current_user.id)
    research_groups = ResearchGroup.query.all()

    return render_template('admin/my_affiliations.html', user=current_user, data=data, research_groups=research_groups)


@admin.route('/add_my_affiliation/<int:groupid>')
@roles_required('faculty')
def add_my_affiliation(groupid):
    data = FacultyData.query.get_or_404(current_user.id)
    group = ResearchGroup.query.get_or_404(groupid)

    if group not in data.affiliations:
        data.add_affiliation(group)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/remove_my_affiliation/<int:groupid>')
@roles_required('faculty')
def remove_my_affiliation(groupid):
    data = FacultyData.query.get_or_404(current_user.id)
    group = ResearchGroup.query.get_or_404(groupid)

    if group in data.affiliations:
        data.remove_affiliation(group)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_groups')
@roles_required('root')
def edit_groups():
    """
    View function that handles listing of all registered research groups
    :return:
    """

    groups = ResearchGroup.query.filter_by(active=True)

    return render_template('admin/edit_groups.html', groups=groups)


@admin.route('/add_group', methods=['GET', 'POST'])
@roles_required('root')
def add_group():
    """
    View function to add a new research group
    :return:
    """

    form = AddResearchGroupForm(request.form)

    if form.validate_on_submit():
        group = ResearchGroup(abbreviation=form.abbreviation.data,
                              name=form.name.data,
                              website=form.website.data,
                              active=True,
                              creator_id=current_user.id,
                              creation_timestamp=datetime.now());
        db.session.add(group)
        db.session.commit()

        return redirect(url_for('admin.edit_groups'))

    return render_template('admin/edit_group.html', group_form=form, title='Add new research group')


@admin.route('/edit_group/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_group(id):
    """
    View function to edit an existing research group
    :param id:
    :return:
    """

    group = ResearchGroup.query.get_or_404(id)
    form = EditResearchGroupForm(obj=group)

    form.group = group

    if form.validate_on_submit():
        group.abbreviation = form.abbreviation.data
        group.name = form.name.data
        group.website = form.website.data
        group.last_edit_id = current_user.id
        group.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_groups'))

    return render_template('admin/edit_group.html', group_form=form, group=group, title='Edit research group')


@admin.route('/activate_group/<int:id>')
@roles_required('root')
def activate_group(id):
    """
    View to make a research group active
    :param id:
    :return:
    """

    group = ResearchGroup.query.get_or_404(id)
    group.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_group/<int:id>')
@roles_required('root')
def deactivate_group(id):
    """
    View to make a research group inactive
    :param id:
    :return:
    """

    group = ResearchGroup.query.get_or_404(id)
    group.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_programmes')
@roles_required('root')
def edit_degree_programmes():
    """
    View for edit programmes
    :return:
    """

    types = DegreeType.query.all()
    programmes = DegreeProgramme.query.all()

    return render_template('admin/edit_programmes.html', types=types, programmes=programmes)


@admin.route('/add_type', methods=['GET', 'POST'])
@roles_required('root')
def add_degree_type():
    """
    View to create a new degree type
    :return:
    """

    form = AddDegreeTypeForm(request.form)

    if form.validate_on_submit():
        degree_type = DegreeType(name=form.name.data,
                                 active=True,
                                 creator_id=current_user.id,
                                 creation_timestamp=datetime.now())
        db.session.add(degree_type)
        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/edit_type.html', type_form=form, title='Add new degree type')


@admin.route('/edit_type/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_degree_type(id):
    """
    View to edit a degree type
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    form = EditDegreeTypeForm(obj=degree_type)

    form.degree_type = degree_type

    if form.validate_on_submit():
        degree_type.name = form.name.data
        degree_type.last_edit_id = current_user.id
        degree_type.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/edit_type.html', type_form=form, type=degree_type, title='Edit degree type')


@admin.route('/make_type_active/<int:id>')
@roles_required('root')
def activate_degree_type(id):
    """
    Make a degree type active
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_type_inactive/<int:id>')
@roles_required('root')
def deactivate_degree_type(id):
    """
    Make a degree type inactive
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/add_programme', methods=['GET', 'POST'])
@roles_required('root')
def add_degree_programme():
    """
    View to create a new degree programme
    :return:
    """

    # check whether any active degree types exist, and raise an error if not
    if not DegreeType.query.filter_by(active=True).first():
        flash('No degree types are available. Set up at least one active degree type before adding a degree programme.')
        return redirect(request.referrer)

    form = AddDegreeProgrammeForm(request.form)

    if form.validate_on_submit():
        degree_type = form.degree_type.data
        programme = DegreeProgramme(name=form.name.data,
                                    active=True,
                                    type_id=degree_type.id,
                                    creator_id=current_user.id,
                                    creation_timestamp=datetime.now())
        db.session.add(programme)
        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/edit_programme.html', programme_form=form, title='Add new degree programme')


@admin.route('/edit_programme/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_degree_programme(id):
    """
    View to edit a degree programme
    :param id:
    :return:
    """

    programme = DegreeProgramme.query.get_or_404(id)
    form = EditDegreeProgrammeForm(obj=programme)

    form.programme = programme

    if form.validate_on_submit():
        programme.name = form.name.data
        programme.type_id = form.degree_type.data.id
        programme.last_edit_id = current_user.id
        programme.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/edit_programme.html', programme_form=form, programme=programme,
                           title='Edit degree programme')


@admin.route('/activate_programme/<int:id>')
@roles_required('root')
def activate_degree_programme(id):
    """
    Make a degree programme active
    :param id:
    :return:
    """

    programme = DegreeProgramme.query.get_or_404(id)
    programme.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_programme/<int:id>')
@roles_required('root')
def deactivate_degree_programme(id):
    """
    Make a degree programme inactive
    :param id:
    :return:
    """

    programme = DegreeProgramme.query.get_or_404(id)
    programme.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_skills')
@roles_accepted('admin', 'root', 'faculty')
def edit_skills():
    """
    View for edit skills
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    skills = TransferableSkill.query.all()

    return render_template('admin/edit_skills.html', skills=skills)


@admin.route('/add_skill', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def add_skill():
    """
    View to create a new transferable skill
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    form = AddTransferrableSkillForm(request.form)

    if form.validate_on_submit():
        skill = TransferableSkill(name=form.name.data,
                                  active=True,
                                  creator_id=current_user.id,
                                  creation_timestamp=datetime.now())
        db.session.add(skill)
        db.session.commit()

        return redirect(url_for('admin.edit_skills'))

    return render_template('admin/edit_skill.html', skill_form=form, title='Add new transferable skill')


@admin.route('/edit_skill/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def edit_skill(id):
    """
    View to edit a transferable skill
    :param id:
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    form = EditTransferableSkillForm(obj=skill)

    form.skill = skill

    if form.validate_on_submit():
        skill.name = form.name.data
        skill.last_edit_id = current_user.id
        skill.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_skills'))

    return render_template('admin/edit_skill.html', skill_form=form, skill=skill, title='Edit transferable skill')


@admin.route('/activate_skill/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def activate_skill(id):
    """
    Make a transferable active
    :param id:
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    skill.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_skill/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def deactivate_skill(id):
    """
    Make a transferable inactive
    :param id:
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    skill = TransferableSkill.query.get_or_404(id)
    skill.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_project_classes')
@roles_required('root')
def edit_project_classes():
    """
    Provide list and edit view for project classes
    :return:
    """

    classes = ProjectClass.query.all()

    return render_template('admin/edit_project_classes.html', classes=classes)


@admin.route('/add_pclass', methods=['GET', 'POST'])
@roles_required('root')
def add_pclass():
    """
    Create a new project class
    :return:
    """

    # check whether any active degree types exist, and raise an error if not
    if not DegreeType.query.filter_by(active=True).first():
        flash('No degree types are available. Set up at least one active degree type before adding a project class.')
        return redirect(request.referrer)

    form = AddProjectClassForm(request.form)

    if form.validate_on_submit():

        # insert a record for this project class
        data = ProjectClass(name=form.name.data,
                            abbreviation=form.abbreviation.data,
                            year=form.year.data,
                            extent=form.extent.data,
                            require_confirm=form.require_confirm.data,
                            supervisor_carryover=form.supervisor_carryover.data,
                            submissions=form.submissions.data,
                            convenor=form.convenor.data,
                            selection_open_to_all=form.selection_open_to_all.data,
                            programmes=form.programmes.data,
                            initial_choices=form.initial_choices.data,
                            switch_choices=form.switch_choices.data,
                            active=True,
                            creator_id=current_user.id,
                            creation_timestamp=datetime.now())
        db.session.add(data)
        db.session.flush()

        # generate a corresponding configuration record for the current academic year
        current_year = get_current_year()

        config = ProjectClassConfig(year=current_year,
                                    pclass_id=data.id,
                                    requests_issued=False,
                                    live=False,
                                    closed=False,
                                    creator_id=current_user.id,
                                    creation_timestamp=datetime.now(),
                                    submission_period=1)

        data.convenor.add_convenorship(data)

        db.session.add(config)

        # don't generate any go-live requests here; this is done explicitly by user action

        db.session.commit()

        return redirect(url_for('admin.edit_project_classes'))

    return render_template('admin/edit_project_class.html', project_form=form, title='Add new project class')


@admin.route('/edit_pclass/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_pclass(id):
    """
    Edit properties for an existing project class
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    form = EditProjectClassForm(obj=data)

    form.project_class = data

    # remember old convenor
    old_convenor = data.convenor

    if form.validate_on_submit():

        data.name = form.name.data
        data.year = form.year.data
        data.extent = form.extent.data
        data.require_confirm = form.require_confirm.data
        data.supervisor_carryover = form.supervisor_carryover.data
        data.submissions = form.submissions.data
        data.convenor = form.convenor.data
        data.selection_open_to_all = form.selection_open_to_all.data
        data.programmes = form.programmes.data
        data.initial_choices = form.initial_choices.data
        data.switch_choices = form.switch_choices.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        if data.convenor.id != old_convenor.id:

            old_convenor.remove_convenorship(data)
            data.convenor.add_convenorship(data)

        db.session.commit()

        return redirect(url_for('admin.edit_project_classes'))

    return render_template('admin/edit_project_class.html', project_form=form, project_class=data,
                           title='Edit project class')


@admin.route('/activate_pclass/<int:id>')
@roles_required('root')
def activate_pclass(id):
    """
    Make a project class active
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_pclass/<int:id>')
@roles_required('root')
def deactivate_pclass(id):
    """
    Make a project class inactive
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_supervisors', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def edit_supervisors():
    """
    View to list and edit supervisory roles
    :return:
    """

    roles = Supervisor.query.all()

    return render_template('admin/edit_supervisors.html', roles=roles)


@admin.route('/add_supervisor', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def add_supervisor():
    """
    Create a new supervisory role
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    form = AddSupervisorForm(request.form)

    if form.validate_on_submit():
        data = Supervisor(name=form.name.data,
                          active=True,
                          creator_id=current_user.id,
                          creation_timestamp=datetime.now())
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_supervisors'))

    return render_template('admin/edit_supervisor.html', supervisor_form=form, title='Add new supervisory role')


@admin.route('/edit_supervisor/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root', 'faculty')
def edit_supervisor(id):
    """
    Edit a supervisory role
    :param id:
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    form = EditSupervisorForm(obj=data)

    form.supervisor = data

    if form.validate_on_submit():
        data.name = form.name.data
        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.edit_supervisors'))

    return render_template('admin/edit_supervisor.html', supervisor_form=form, role=data,
                           title='Edit supervisory role')


@admin.route('/activate_supervisor/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def activate_supervisor(id):
    """
    Make a supervisor active
    :param id:
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_supervisor/<int:id>')
@roles_accepted('admin', 'root', 'faculty')
def deactivate_supervisor(id):
    """
    Make a supervisor inactive
    :param id:
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    data = Supervisor.query.get_or_404(id)
    data.disable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/faculty_settings', methods=['GET', 'POST'])
@roles_required('faculty')
def faculty_settings():
    """
    Edit settings for a faculty member
    :return:
    """

    user = User.query.get_or_404(current_user.id)
    data = FacultyData.query.get_or_404(current_user.id)

    form = FacultySettingsForm(obj=data)
    form.user = user

    if form.validate_on_submit():

        user.first_name = form.first_name.data
        user.last_name = form.last_name.data
        user.username = form.username.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data
        data.office = form.office.data

        data.last_edit_id = current_user.id
        data.last_edit_timestamp = datetime.now()

        flash('All changes saved')

        db.session.commit()

        return home_dashboard()

    else:

        if request.method == 'GET':

            form.first_name.data = user.first_name
            form.last_name.data = user.last_name
            form.username.data = user.username

    return render_template('admin/faculty_settings.html', settings_form=form, data=data,
                           project_classes=ProjectClass.query.filter_by(active=True))


@admin.route('/confirm_global_rollover')
@roles_required('root')
def confirm_global_rollover():
    """
    Show confirmation box for global advance of academic year
    :return:
    """

    next_year = get_current_year() + 1

    title = 'Global rollover to {yeara}&ndash;{yearb}'.format(yeara=next_year, yearb=next_year + 1)
    panel_title = 'Global rollover of academic year to {yeara}&ndash;{yearb}'.format(yeara=next_year,
                                                                                     yearb=next_year + 1)
    action_url = url_for('admin.perform_global_rollover')
    message = 'Please confirm that you wish to advance the global academic year to ' \
              '{yeara}&ndash;{yearb}'.format(yeara=next_year, yearb=next_year + 1)
    submit_label = 'Rollover to {yr}'.format(yr=next_year)

    return render_template('admin/danger_confirm.html', title=title, panel_title=panel_title, action_url=action_url,
                           message=message, submit_label=submit_label)


@admin.route('/perform_global_rollover')
@roles_required('root')
def perform_global_rollover():
    """
    Globally advance the academic year
    (doesn't actually do anything directly; each project class must be advanced
    independently by its convenor or an administrator)
    :return:
    """

    next_year = get_current_year() + 1

    new_year = MainConfig(year=next_year)
    db.session.add(new_year)
    db.session.commit()

    return redirect(url_for('home.homepage'))


@admin.route('/email_log', methods=['GET', 'POST'])
@roles_required('root')
def email_log():
    """
    Display a log of sent emails
    :return: 
    """

    form = EmailLogForm(request.form)

    if form.validate_on_submit():

        if form.delete_age.data is True:
            cutoff = form.days.data

            now = datetime.now()
            delta = timedelta(days=cutoff)
            limit = now - delta

            EmailLog.query.filter(EmailLog.send_date < limit).delete()
            db.session.commit()

    emails = db.session.query(EmailLog)

    return render_template('admin/email_log.html', form=form, emails=emails)


@admin.route('/display_email/<int:id>')
@roles_required('root')
def display_email(id):
    """
    Display a specific email
    :param id:
    :return:
    """

    email = EmailLog.query.get_or_404(id)

    return render_template('admin/display_email.html', email=email)


@admin.route('/delete_email/<int:id>')
@roles_required('root')
def delete_email(id):
    """
    Delete an email
    :param id:
    :return:
    """

    email = EmailLog.query.get_or_404(id)
    db.session.delete(email)
    db.session.commit()

    return redirect(url_for('admin.email_log'))


@admin.route('/delete_all_emails')
@roles_required('root')
def delete_all_emails():
    """
    Delete all emails stored in the log
    :return:
    """

    db.session.query(EmailLog).delete()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_messages')
@roles_accepted('faculty', 'admin', 'root')
def edit_messages():
    """
    Edit message-of-the-day type messages
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    if current_user.has_role('admin') or current_user.has_role('root'):

        # admin users can edit all messages
        messages = MessageOfTheDay.query.all()

    else:

        # convenors can only see their own messages
        messages = MessageOfTheDay.query.filter_by(user_id=current_user.id).all()

    return render_template('admin/edit_messages.html', messages=messages)


@admin.route('/add_message', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def add_message():
    """
    Add a new message-of-the-day message
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    # convenors can't show login-screen messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):
        form = AddMessageForm(request.form, convenor_editing=True)
        del form.show_login
    else:
        form = AddMessageForm(request.form)

    if form.validate_on_submit():

        if 'show_login' in form._fields:
            show_login = form._fields.get('show_login').data
        else:
            show_login = False

        data = MessageOfTheDay(user_id=current_user.id,
                               issue_date=datetime.now(),
                               show_students=form.show_students.data,
                               show_faculty=form.show_faculty.data,
                               show_login=show_login,
                               dismissible=form.dismissible.data,
                               title=form.title.data,
                               body=form.body.data,
                               project_classes=form.project_classes.data)
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_messages'))

    return render_template('admin/edit_message.html', form=form, title='Add new broadcast message')


@admin.route('/edit_message/<int:id>', methods=['GET', 'POST'])
@roles_accepted('faculty', 'admin', 'root')
def edit_message(id):
    """
    Edit a message-of-the-day message
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    data = MessageOfTheDay.query.get_or_404(id)

    # convenors can't show login-screen messages and can only edit their own messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):

        if data.user_id != current_user.id:
            flash('Only administrative users can edit messages that they do not own')
            return home_dashboard()

        form = EditMessageForm(obj=data, convenor_editing=True)
        del form.show_login

    else:

        form = EditMessageForm(obj=data)

    if form.validate_on_submit():

        if 'show_login' in form._fields:
            show_login = form._fields.get('show_login').data
        else:
            show_login = False

        data.show_students = form.show_students.data
        data.show_faculty = form.show_faculty.data
        data.show_login = show_login
        data.dismissible = form.dismissible.data
        data.title = form.title.data
        data.body = form.body.data
        data.project_classes = form.project_classes.data

        db.session.commit()

        return redirect(url_for('admin.edit_messages'))

    return render_template('admin/edit_message.html', message=data, form=form, title='Edit broadcast message')


@admin.route('/delete_message/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def delete_message(id):
    """
    Delete message-of-the-day message
    :return:
    """

    if not _check_admin_or_convenor():
        return home_dashboard()

    data = MessageOfTheDay.query.get_or_404(id)

    # convenors can only delete their own messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):

        if data.user_id != current_user.id:
            flash('Only administrative users can edit messages that are not their own.')
            return home_dashboard()

    db.session.delete(data)
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/dismiss_message/<int:id>')
@login_required
def dismiss_message(id):
    """
    Record that the current user has dismissed a particular message
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    if current_user not in message.dismissed_by:

        message.dismissed_by.append(current_user)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/reset_dismissals/<int:id>')
@roles_accepted('faculty', 'admin', 'root')
def reset_dismissals(id):
    """
    Remove dismissals from a message (eg. we might want to do this after updating the text)
    :param id:
    :return:
    """

    message = MessageOfTheDay.query.get_or_404(id)

    # convenors can only reset their own messages
    if not current_user.has_role('admin') and not current_user.has_role('root'):

        if message.user_id != current_user.id:
            flash('Only administrative users can reset dismissals for messages that are not their own.')
            return home_dashboard()

    message.dismissed_by = []
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/scheduled_tasks')
@roles_required('root')
def scheduled_tasks():
    """
    UI for scheduling period tasks (database backup, prune email log, etc.)
    :return:
    """

    tasks = db.session.query(DatabaseSchedulerEntry)

    return render_template('admin/scheduled_tasks.html', tasks=tasks)


@admin.route('/add_scheduled_task', methods=['GET', 'POST'])
@roles_required('root')
def add_scheduled_task():
    """
    Add a new scheduled task
    :return:
    """

    form = ScheduleTypeForm(request.form)

    if form.validate_on_submit():

        if form.type.data == 'interval':

            return redirect(url_for('admin.add_interval_task'))

        elif form.type.data == 'crontab':

            return redirect(url_for('admin.add_crontab_task'))

        else:

            flash('The task type was not recognized. If this error persists, please contact '
                  'the system administrator.')

            return redirect(url_for('admin.scheduled_tasks'))

    return render_template('admin/scheduled_type.html', form=form, title='Select schedule type')


@admin.route('/add_interval_task', methods=['GET', 'POST'])
@roles_required('root')
def add_interval_task():
    """
    Add a new task specified by a simple interval
    :return:
    """

    form = AddIntervalScheduledTask(request.form)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(every=form.every.data, period=form.period.data).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data,
                                   period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        data = DatabaseSchedulerEntry(name=form.name.data,
                                      owner_id=form.owner.data.id,
                                      task=form.task.data,
                                      interval_id=sch.id,
                                      crontab_id=None,
                                      arguments=_maybe_null(form.arguments.data),
                                      keyword_arguments=_maybe_null(form.keyword_arguments.data),
                                      queue=None,
                                      exchange=None,
                                      routing_key=None,
                                      expires=form.expires.data,
                                      enabled=True,
                                      last_run_at=datetime.now(),
                                      total_run_count=0,
                                      date_changed=datetime.now())

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    return render_template('admin/edit_scheduled_task.html', form=form, title='Add new fixed-interval task')


@admin.route('/add_crontab_task', methods=['GET', 'POST'])
@roles_required('root')
def add_crontab_task():
    """
    Add a new task specified by a crontab
    :return:
    """

    form = AddCrontabScheduledTask(request.form)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(minute=form.minute.data,
                                              hour=form.hour.data,
                                              day_of_week=form.day_of_week.data,
                                              day_of_month=form.day_of_month.data,
                                              month_of_year=form.month_of_year.data).first()

        if sch is None:
            sch = CrontabSchedule(minute=form.minute.data,
                                  hour=form.hour.data,
                                  day_of_week=form.day_of_week.data,
                                  day_of_month=form.day_of_month.data,
                                  month_of_year=form.month_of_year.data)
            db.session.add(sch)
            db.session.flush()

        data = DatabaseSchedulerEntry(name=form.name.data,
                                      owner_id=form.owner.data.id,
                                      task=form.task.data,
                                      interval_id=None,
                                      crontab_id=sch.id,
                                      arguments=_maybe_null(form.arguments.data),
                                      keyword_arguments=_maybe_null(form.keyword_arguments.data),
                                      queue=None,
                                      exchange=None,
                                      routing_key=None,
                                      expires=form.expires.data,
                                      enabled=True,
                                      last_run_at=datetime.now(),
                                      total_run_count=0,
                                      date_changed=datetime.now())

        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    return render_template('admin/edit_scheduled_task.html', form=form, title='Add new crontab task')


@admin.route('/edit_interval_task/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_interval_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditIntervalScheduledTask(obj=data)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = IntervalSchedule.query.filter_by(every=form.every.data, period=form.period.data).first()

        if sch is None:
            sch = IntervalSchedule(every=form.every.data,
                                   period=form.period.data)
            db.session.add(sch)
            db.session.flush()

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.interval_id = sch.id
        data.crontab_id = None
        data.arguments = _maybe_null(form.arguments.data)
        data.keyword_arguments = _maybe_null(form.keyword_arguments.data)
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    else:

        if request.method == 'GET':

            form.every.data = data.interval.every
            form.period.data = data.interval.period

    return render_template('admin/edit_scheduled_task.html', task=data, form=form, title='Edit fixed-interval task')


@admin.route('/edit_interval_task/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_crontab_task(id):
    """
    Edit an existing fixed-interval task
    :return:
    """

    data = DatabaseSchedulerEntry.query.get_or_404(id)
    form = EditCrontabScheduledTask(obj=data)

    if form.validate_on_submit():

        # build or lookup an appropriate IntervalSchedule record from the database
        sch = CrontabSchedule.query.filter_by(minute=form.minute.data,
                                              hour=form.hour.data,
                                              day_of_week=form.day_of_week.data,
                                              day_of_month=form.day_of_month.data,
                                              month_of_year=form.month_of_year.data).first()

        if sch is None:
            sch = CrontabSchedule(minute=form.minute.data,
                                  hour=form.hour.data,
                                  day_of_week=form.day_of_week.data,
                                  day_of_month=form.day_of_month.data,
                                  month_of_year=form.month_of_year.data)
            db.session.add(sch)
            db.session.flush()

        data.name = form.name.data
        data.owner_id = form.owner.data.id
        data.task = form.task.data
        data.interval_id = None
        data.crontab_id = sch.id
        data.arguments = _maybe_null(form.arguments.data)
        data.keyword_arguments = _maybe_null(form.keyword_arguments.data)
        data.expires = form.expires.data
        data.date_changed = datetime.now()

        db.session.commit()

        return redirect(url_for('admin.scheduled_tasks'))

    else:

        if request.method == 'GET':

            form.minute.data = data.crontab.minute
            form.hour.data = data.crontab.hour
            form.day_of_week.data = data.crontab.day_of_week
            form.day_of_month = data.crontab.day_of_month
            form.month_of_year = data.crontab.month_of_year

    return render_template('admin/edit_scheduled_task.html', task=data, form=form, title='Add new crontab task')



@admin.route('/delete_scheduled_task/<int:id>')
@roles_required('root')
def delete_scheduled_task(id):
    """
    Remove an existing scheduled task
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    db.session.delete(task)
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/activate_scheduled_task/<int:id>')
@roles_required('root')
def activate_scheduled_task(id):
    """
    Mark a scheduled task as active
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/deactivate_scheduled_task/<int:id>')
@roles_required('root')
def deactivate_scheduled_task(id):
    """
    Mark a scheduled task as inactive
    :return:
    """

    task = DatabaseSchedulerEntry.query.get_or_404(id)

    task.enabled = False
    db.session.commit()

    return redirect(request.referrer)


def _maybe_null(str):
    """
    Convert a null or empty string to JSON null object
    :param str:
    :return:
    """

    if str is None or len(str) == 0:
        return 'null'

    return str
