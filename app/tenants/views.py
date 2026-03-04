#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, redirect, flash, request, jsonify, url_for
from flask_security import roles_required
from sqlalchemy.exc import SQLAlchemyError

from . import tenants
from .forms import AddTenantForm, EditTenantForm
from .. import ajax
from ..database import db
from ..models import Tenant
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..tools import ServerSideSQLHandler


@tenants.route('/edit_tenants')
@roles_required("root")
def edit_tenants():
    return render_template_context("tenants/edit_tenants.html")


@tenants.route('/tenants_ajax', methods=["POST"])
@roles_required("root")
def tenants_ajax():
    base_query = db.session.query(Tenant)
    
    name = {"search": Tenant.name, "order": Tenant.name}
    
    columns = {"name": name}
    
    with ServerSideSQLHandler(request, base_query, columns) as handler:
        return handler.build_payload(ajax.tenants.tenants_data)


@tenants.route('/add_tenant', methods=["GET", "POST"])
@roles_required("root")
def add_tenant():
    form = AddTenantForm(request.form)
    
    if form.validate_on_submit():
        tenant = Tenant(
            name=form.name.data,
            colour=form.colour.data,
            force_ATAS_flag=form.force_ATAS_flag.data,
            in_2026_ATAS_campaign=form.in_2026_ATAS_campaign.data,
        )

        try:
            db.session.add(tenant)
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not add new tenant because of a database error. Please contact a system administrator.", "error")

        return redirect(url_for('tenants.edit_tenants'))
        
    return render_template_context("tenants/edit_tenant.html", tenant_form=form, title="Add new tenant")


@tenants.route('/edit_tenant/<int:id>', methods=["GET", "POST"])
@roles_required("root")
def edit_tenant(id):
    tenant = db.session.query(Tenant).get_or_404(id)
    
    form = EditTenantForm(obj=tenant)
    form.tenant = tenant
    
    if form.validate_on_submit():
        tenant.name = form.name.data
        tenant.colour = form.colour.data
        tenant.force_ATAS_flag = form.force_ATAS_flag.data
        tenant.in_2026_ATAS_campaign = form.in_2026_ATAS_campaign.data

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not rename tenant because of a database error. Please contact a system administrator.", "error")

        return redirect(url_for('tenants.edit_tenants'))
        
    return render_template_context("tenants/edit_tenant.html", tenant_form=form, title="Edit tenant")
