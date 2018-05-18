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
from flask_security.utils import config_value, get_url, find_redirect, validate_redirect_url, get_message, do_flash, send_mail
from flask_security.confirmable import generate_confirmation_link
from flask_security.signals import user_registered

from .actions import register_user
from .forms import GlobalRolloverForm, RoleSelectForm, \
    ConfirmRegisterOfficeForm, ConfirmRegisterFacultyForm, ConfirmRegisterStudentForm, \
    EditOfficeForm, EditFacultyForm, EditStudentForm, \
    AddResearchGroupForm, EditResearchGroupForm, \
    AddDegreeTypeForm, EditDegreeTypeForm, \
    AddDegreeProgrammeForm, EditDegreeProgrammeForm, \
    AddTransferrableSkillForm, EditTransferableSkillForm, \
    AddProjectClassForm, EditProjectClassForm, \
    AddSupervisorForm, EditSupervisorForm, \
    FacultySettingsForm
from ..models import db, MainConfig, User, FacultyData, StudentData, ResearchGroup, DegreeType, DegreeProgramme, \
    TransferableSkill, ProjectClass, ProjectClassConfig, Supervisor, Project

from . import admin

from datetime import date


_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


@admin.route('/create_user', methods=['GET', 'POST'])
@roles_required('admin')
def create_user():
    """
    View function that handles creation of a user account
    """

    # check whether any active degree programmes exist, and raise an error if not
    if not DegreeProgramme.query.filter_by(active=True).first():

        flash('No degree programmes are available. Set up at least one active degree programme before adding new users.')
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

    return render_template('security/register_user.html', user_form=form, role=role, title='Register a new {r} user account'.format(r=role))


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
                           sign_off_students=form.sign_off_students.data)
        db.session.add(data)

        db.session.commit()

        return redirect(url_for('admin.edit_users'))

    return render_template('security/register_user.html', user_form=form, role=role, title='Register a new {r} user account'.format(r=role))


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

        data = StudentData(id=user.id, exam_number=form.exam_number.data,
                           cohort=form.cohort.data, programme=form.programme.data)
        db.session.add(data)

        db.session.commit()

        return redirect(url_for('admin.edit_users'))

    else:

        if request.method == 'GET':

            # populate cohort with default value on first load
            query_year = MainConfig.query.first()

            if query_year:

                form.cohort.data = query_year.year

            else:

                form.cohort.data = date.today().year

    return render_template('security/register_user.html', user_form=form, role=role, title='Register a new {r} user account'.format(r=role))


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


@admin.route('/make_active/<int:id>')
@roles_required('admin')
def make_active(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    _datastore.activate_user(user)
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/make_inactive/<int:id>')
@roles_required('admin')
def make_inactive(id):
    """
    Make a user account active
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)

    if user.has_role('admin') or user.has_role('root'):

        flash("Administrative users cannot be made inactive. Remove administration status before marking the user as inactive.")
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
        if form.email.data != user.email:

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
        if form.email.data != user.email:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data

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
        if form.email.data != user.email:
            user.confirmed_at = None
            resend_confirmation = True

        user.email = form.email.data
        user.username = form.username.data
        user.first_name = form.first_name.data
        user.last_name = form.last_name.data

        data.exam_number = form.exam_number.data
        data.cohort = form.cohort.data
        data.programme_id = form.programme.data.id

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
                              name=form.name.data, website=form.website.data, active=True);
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

        db.session.commit()

        return redirect(url_for('admin.edit_groups'))

    return render_template('admin/edit_group.html', group_form=form, group=group, title='Edit research group')


@admin.route('/make_group_active/<int:id>')
@roles_required('root')
def make_group_active(id):
    """
    View to make a research group active
    :param id:
    :return:
    """

    group = ResearchGroup.query.get_or_404(id)
    group.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_group_inactive/<int:id>')
@roles_required('root')
def make_group_inactive(id):
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

        degree_type = DegreeType(name=form.name.data, active=True)
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
        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/edit_type.html;', type_form=form, programme=degree_type, title='Edit degree type')


@admin.route('/make_type_active/<int:id>')
@roles_required('root')
def make_degree_type_active(id):
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
def make_degree_type_inactive(id):
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
        programme = DegreeProgramme(name=form.name.data, active=True, type_id=degree_type.id)
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
        db.session.commit()

        return redirect(url_for('admin.edit_degree_programmes'))

    return render_template('admin/edit_programme.html', programme_form=form, programme=programme, title='Edit degree programme')


@admin.route('/make_programme_active/<int:id>')
@roles_required('root')
def make_degree_programme_active(id):
    """
    Make a degree programme active
    :param id:
    :return:
    """

    programme = DegreeProgramme.query.get_or_404(id)
    programme.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_programme_inactive/<int:id>')
@roles_required('root')
def make_degree_programme_inactive(id):
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
@roles_required('admin')
def edit_skills():
    """
    View for edit skills
    :return:
    """

    skills = TransferableSkill.query.all()

    return render_template('admin/edit_skills.html', skills=skills)


@admin.route('/add_skill', methods=['GET', 'POST'])
@roles_required('admin')
def add_skill():
    """
    View to create a new transferable skill
    :return:
    """

    form = AddTransferrableSkillForm(request.form)

    if form.validate_on_submit():

        skill = TransferableSkill(name=form.name.data)
        db.session.add(skill)
        db.session.commit()

        return redirect(url_for('admin.edit_skills'))

    return render_template('admin/edit_skill.html', skill_form=form, title='Add new transferable skill')


@admin.route('/edit_skill/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
def edit_skill(id):
    """
    View to edit a transferable skill
    :param id:
    :return:
    """

    skill = TransferableSkill.query.get_or_404(id)
    form = EditTransferableSkillForm(obj=skill)

    form.skill = skill

    if form.validate_on_submit():

        skill.name = form.name.data
        db.session.commit()

        return redirect(url_for('admin.edit_skills'))

    return render_template('admin/edit_skill.html', skill_form=form, skill=skill, title='Edit transferable skill')


@admin.route('/make_skill_active/<int:id>')
@roles_required('root')
def make_skill_active(id):
    """
    Make a transferable active
    :param id:
    :return:
    """

    skill = TransferableSkill.query.get_or_404(id)
    skill.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_skill_inactive/<int:id>')
@roles_required('root')
def make_skill_inactive(id):
    """
    Make a transferable inactive
    :param id:
    :return:
    """

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


@admin.route('/add_project_class', methods=['GET', 'POST'])
@roles_required('root')
def add_project_class():
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
                            programmes=form.programmes.data,
                            active=True)
        db.session.add(data)

        # generate a corresponding configuration record for the current academic year
        current_year = MainConfig.query.order_by(MainConfig.year.desc()).first().year

        config = ProjectClassConfig(year=current_year,
                                    pclass_id=data.id,
                                    requests_issued=False,
                                    live=False,
                                    closed=False)

        db.session.add(config)

        # don't generate any go-live requests here; this is done explicitly by user action

        db.session.commit()

        return redirect(url_for('admin.edit_project_classes'))

    return render_template('admin/edit_project_class.html', project_form=form, title='Add new project class')


@admin.route('/edit_project_class/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_project_class(id):
    """
    Edit properties for an existing project class
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    form = EditProjectClassForm(obj=data)

    form.project_class = data

    if form.validate_on_submit():

        data.name = form.name.data
        data.year = form.year.data
        data.extent = form.extent.data
        data.require_confirm = form.require_confirm.data
        data.supervisor_carryover = form.supervisor_carryover.data
        data.submissions = form.submissions.data
        data.convenor = form.convenor.data
        data.programmes = form.programmes.data

        db.session.commit()

        return redirect(url_for('admin.edit_project_classes'))

    return render_template('admin/edit_project_class.html', project_form=form, project_class=data,
                           title='Edit project class')


@admin.route('/make_project_class_active/<int:id>')
@roles_required('root')
def make_project_class_active(id):
    """
    Make a project class active
    :param id:
    :return:
    """

    data = ProjectClass.query.get_or_404(id)
    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_project_class_inactive/<int:id>')
@roles_required('root')
def make_project_class_inactive(id):
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
@roles_accepted('admin', 'root')
def edit_supervisors():
    """
    View to list and edit supervisory roles
    :return:
    """

    roles = Supervisor.query.all()

    return render_template('admin/edit_supervisors.html', roles=roles)


@admin.route('/add_supervisor', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def add_supervisor():
    """
    Create a new supervisory role
    :return:
    """

    form = AddSupervisorForm(request.form)

    if form.validate_on_submit():

        data = Supervisor(name=form.name.data, active=True)
        db.session.add(data)
        db.session.commit()

        return redirect(url_for('admin.edit_supervisors'))

    return render_template('admin/edit_supervisor.html', supervisor_form=form, title='Add new supervisory role')


@admin.route('/edit_supervisor/<int:id>', methods=['GET', 'POST'])
@roles_accepted('admin', 'root')
def edit_supervisor(id):
    """
    Edit a supervisory role
    :param id:
    :return:
    """

    data = Supervisor.query.get_or_404(id)
    form = EditSupervisorForm(obj=data)

    if form.validate_on_submit():

        data.name = form.name.data
        db.session.commit()

        return redirect(url_for('admin.edit_supervisors'))

    return render_template('admin/edit_supervisor.html', supervisor_form=form, role=data,
                           title='Edit supervisory role')


@admin.route('/make_supervisor_active/<int:id>')
@roles_accepted('admin', 'root')
def make_supervisor_active(id):
    """
    Make a supervisor active
    :param id:
    :return:
    """

    data = Supervisor.query.get_or_404(id)
    data.enable()
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_supervisor_inactive/<int:id>')
@roles_accepted('admin', 'root')
def make_supervisor_inactive(id):
    """
    Make a supervisor inactive
    :param id:
    :return:
    """

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

    if form.validate_on_submit():

        user.first_name = form.first_name.data
        user.last_name = form.last_name.data

        data.academic_title = form.academic_title.data
        data.use_academic_title = form.use_academic_title.data
        data.sign_off_students = form.sign_off_students.data

        flash('All changes saved')

        db.session.commit()

        return redirect(url_for('faculty.dashboard'))

    else:

        if request.method == 'GET':

            form.first_name.data = user.first_name
            form.last_name.data = user.last_name

    return render_template('admin/faculty_settings.html', settings_form=form, data=data,
                           project_classes=ProjectClass.query.filter_by(active=True))


@admin.route('/global_rollover', methods=['GET', 'POST'])
@roles_required('root')
def global_rollover():
    """
    Globally advance the academic year
    (doesn't actually do anything directly; each project class must be advanced
    independently by its convenor or an administrator)
    :return:
    """

    current_year = MainConfig.query.order_by(MainConfig.year.desc()).first()
    next_year = current_year.year + 1

    form = GlobalRolloverForm(request.form)
    form.submit.label.text = 'Rollover to {yr}'.format(yr=next_year)

    if form.validate_on_submit():

        new_year = MainConfig(year=next_year)
        db.session.add(new_year)
        db.session.commit()

        return redirect(url_for('home.homepage'))

    return render_template('admin/global_rollover.html', rollover_form=form, year=next_year)
