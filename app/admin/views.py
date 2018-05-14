#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template, redirect, url_for, flash, request, after_this_request, jsonify
from werkzeug.local import LocalProxy
from werkzeug.datastructures import MultiDict
from flask_security import login_required, roles_required, current_user, logout_user, login_user
from flask_security.utils import config_value, get_url, find_redirect, validate_redirect_url, get_message, do_flash, send_mail
from flask_security.confirmable import generate_confirmation_link
from flask_security.signals import user_registered

from .actions import register_user
from .forms import EditUserForm, \
    AddResearchGroupForm, EditResearchGroupForm, \
    AddDegreeTypeForm, EditDegreeTypeForm, \
    AddDegreeProgrammeForm, EditDegreeProgrammeForm, \
    AddTransferrableSkillForm, EditTransferableSkillForm
from ..models import db, User, FacultyData, ResearchGroup, DegreeType, DegreeProgramme, TransferableSkill

from . import admin


_security = LocalProxy(lambda: current_app.extensions['security'])
_datastore = LocalProxy(lambda: _security.datastore)


def _render_json(form, include_user=True, include_auth_token=False):
    has_errors = len(form.errors) > 0

    if has_errors:
        code = 400
        response = dict(errors=form.errors)
    else:
        code = 200
        response = dict()
        if include_user:
            response['user'] = form.user.get_security_payload()

        if include_auth_token:
            token = form.user.get_auth_token()
            response['user']['authentication_token'] = token

    return jsonify(dict(meta=dict(code=code), response=response)), code


def _commit(response=None):
    _datastore.commit()
    return response


def _ctx(endpoint):
    return _security._run_ctx_processor(endpoint)


def get_post_action_redirect(config_key, declared=None):
    urls = [
        get_url(request.args.get('next')),
        get_url(request.form.get('next')),
        find_redirect(config_key)
    ]
    if declared:
        urls.insert(0, declared)
    for url in urls:
        if validate_redirect_url(url):
            return url


def get_post_login_redirect(declared=None):
    return get_post_action_redirect('SECURITY_POST_LOGIN_VIEW', declared)


def get_post_register_redirect(declared=None):
    return get_post_action_redirect('SECURITY_POST_REGISTER_VIEW', declared)


def get_post_logout_redirect(declared=None):
    return get_post_action_redirect('SECURITY_POST_LOGOUT_VIEW', declared)


@admin.route('/create_user', methods=['GET', 'POST'])
@roles_required('admin')
def create_user():
    """
    View function that handles creation of a user account
    """

    if _security.confirmable or request.is_json:
        form_class = _security.confirm_register_form
    else:
        form_class = _security.register_form

    if request.is_json:
        form_data = MultiDict(request.get_json())
    else:
        form_data = request.form

    form = form_class(form_data)

    if form.validate_on_submit():
        field_data = form.to_dict()

        # hack to handle fact that 'roles' field in register_user() expects a list, not just a single string
        if 'roles' in field_data:
            if isinstance(field_data['roles'], str):
                field_data['roles'] = [ field_data['roles'] ]

        user = register_user(**field_data)
        form.user = user

        # insert associated records where needed
        if user.has_role('faculty'):
            data = FacultyData(id=user.id)
            db.session.add(data)
            db.session.commit()

        if not _security.confirmable or _security.login_without_confirmation:
            after_this_request(_commit)
            login_user(user)

        if not request.is_json:
            if 'next' in form:
                redirect_url = get_post_register_redirect(form.next.data)
            else:
                redirect_url = get_post_register_redirect()

            return redirect(redirect_url)
        return _render_json(form, include_auth_token=True)

    if request.is_json:
        return _render_json(form)

    return _security.render_template(config_value('REGISTER_USER_TEMPLATE'),
                                     user_form=form,
                                     **_ctx('register'), title='Register a new user account')


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

    # TODO: prevent 'admin' being removed from a 'root' user

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

    # TODO: prevent admin or sysadmin users being made inactive

    _datastore.deactivate_user(user)
    _datastore.commit()

    return redirect(request.referrer)


@admin.route('/edit_user/<int:id>', methods=['GET', 'POST'])
@roles_required('admin')
def edit_user(id):
    """
    View function to edit an individual user account -- flask-security details only
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    form = EditUserForm(obj=user)

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

            confirmation_link, token = generate_confirmation_link(user)
            do_flash(*get_message('CONFIRM_REGISTRATION', email=user.email))

            user_registered.send(current_app._get_current_object(),
                                 user=user, confirm_token=token)

            if config_value('SEND_REGISTER_EMAIL'):
                send_mail(config_value('EMAIL_SUBJECT_REGISTER'), user.email,
                          'welcome', user=user, confirmation_link=confirmation_link)


        return redirect(url_for('admin.edit_users'))

    return render_template('security/register_user.html', user_form=form, user=user, title='Edit a user account')


@admin.route('/edit_affiliations/<int:id>')
@roles_required('admin')
def edit_affiliations(id):
    """
    View to edit research group affiliations for a given faculty member
    :param id:
    :return:
    """

    user = User.query.get_or_404(id)
    data = FacultyData.query.get_or_404(id)
    research_groups = ResearchGroup.query.all()

    return render_template('admin/edit_affiliations.html', user=user, data=data, research_groups=research_groups)


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
        data.affiliations.append(group)
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
        data.affiliations.remove(group)
        db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_groups')
@roles_required('root')
def edit_groups():
    """
    View function that handles listing of all registered research groups
    :return:
    """

    groups = ResearchGroup.query.all()

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
                              name=form.name.data, active=True);
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
    group.active = True
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
    group.active = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/edit_programmes')
@roles_required('root')
def edit_programmes():
    """
    View for edit programmes
    :return:
    """

    types = DegreeType.query.all()
    programmes = DegreeProgramme.query.all()

    return render_template('admin/edit_programmes.html', types=types, programmes=programmes)


@admin.route('/add_type', methods=['GET', 'POST'])
@roles_required('root')
def add_type():
    """
    View to create a new type
    :return:
    """

    form = AddDegreeTypeForm(request.form)

    if form.validate_on_submit():

        degree_type = DegreeType(name=form.name.data, active=True)
        db.session.add(degree_type)
        db.session.commit()

        return redirect(url_for('admin.edit_programmes'))

    return render_template('admin/edit_type.html', type_form=form, title='Add new degree type')


@admin.route('/edit_type/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_type(id):
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

        return redirect(url_for('admin.edit_programmes'))

    return render_template('admin/edit_type.html;', type_form=form, programme=degree_type, title='Edit degree type')


@admin.route('/make_type_active/<int:id>')
@roles_required('root')
def make_type_active(id):
    """
    Make a degree type active
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.active = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_type_inactive/<int:id>')
@roles_required('root')
def make_type_inactive(id):
    """
    Make a degree type inactive
    :param id:
    :return:
    """

    degree_type = DegreeType.query.get_or_404(id)
    degree_type.active = False
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/add_programme', methods=['GET', 'POST'])
@roles_required('root')
def add_programme():
    """
    View to create a new programme
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

        return redirect(url_for('admin.edit_programmes'))

    return render_template('admin/edit_programme.html', programme_form=form, title='Add new degree programme')


@admin.route('/edit_programme/<int:id>', methods=['GET', 'POST'])
@roles_required('root')
def edit_programme(id):
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

        return redirect(url_for('admin.edit_programmes'))

    return render_template('admin/edit_programme.html', programme_form=form, programme=programme, title='Edit degree programme')


@admin.route('/make_programme_active/<int:id>')
@roles_required('root')
def make_programme_active(id):
    """
    Make a degree programme active
    :param id:
    :return:
    """

    programme = DegreeProgramme.query.get_or_404(id)
    programme.active = True
    db.session.commit()

    return redirect(request.referrer)


@admin.route('/make_programme_inactive/<int:id>')
@roles_required('root')
def make_programme_inactive(id):
    """
    Make a degree programme inactive
    :param id:
    :return:
    """

    programme = DegreeProgramme.query.get_or_404(id)
    programme.active = False
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
