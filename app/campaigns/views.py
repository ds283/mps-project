#
# Created by David Seery on 03/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from flask import request, current_app, flash, url_for, redirect
from flask_security import roles_required, current_user
from sqlalchemy.exc import SQLAlchemyError

from . import campaigns
from .tools import check_2026_ATAS
from ..models import FacultyData, Project, ProjectTag
from ..shared.context.global_context import render_template_context
from ..database import db


@campaigns.route('/atas_2026', methods=['GET', 'POST'])
@roles_required("faculty")
def atas_2026():
    fd: FacultyData = FacultyData.query.get_or_404(current_user.id)
    data = check_2026_ATAS(fd)

    FormType = data["form"]
    projects = data["projects"]

    form: FormType = FormType(request.form)

    if form.validate_on_submit():
        for project in projects:
            project: Project

            ATAS_label = f"project_{project.id}_ATAS"
            tag_label = f"project_{project.id}_tags"

            project.ATAS_restricted = form[ATAS_label].data
            for tag in form[tag_label].data:
                tag: ProjectTag
                if tag not in project.tags:
                    project.tags.append(tag)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            flash("Could not save changes because of a database error. Please contact a system administrator", "error")
        else:
            flash("Thank you for updating your projects. Your changes have been saved successfully", "info")
            return redirect(url_for('faculty.dashboard'))

    return render_template_context('campaigns/2026_ATAS.html', input_form=form, projects=projects)
