#
# Created by David Seery on 19/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from datetime import datetime
from typing import List

from flask import has_request_context, session, render_template
from flask_login import current_user
from jinja2 import Template

from .assessments import get_assessment_data
from .matching import get_matching_data
from .utils import get_pclass_list, get_pclass_config_list
from ..utils import home_dashboard_url
from ... import site_revision, site_copyright_dates
from ...database import db
from ...models import User


def get_global_context_data():
    pcs = get_pclass_list()
    configs = get_pclass_config_list(pcs)

    assessment = get_assessment_data(configs)
    matching = get_matching_data(configs)

    assessment.update(matching)
    return assessment


def _get_previous_login():
    if not has_request_context():
        return None

    if session.get("previous_login", None) is not None:
        real_id = session["previous_login"]
        real_user = db.session.query(User).filter_by(id=real_id).first()
    else:
        real_user = None

    return real_user


def build_static_context_data(app):
    global _static_ctx

    # data that does not change from request to request can be evaluated, cached, and re-used
    _static_ctx = {
        "website_revision": site_revision,
        "website_copyright_dates": site_copyright_dates,
        "branding_label": app.config.get("BRANDING_LABEL", "Not configured"),
        "branding_login_landing_string": app.config.get("BRANDING_LOGIN_LANDING_STRING", "Not configured"),
        "branding_public_landing_string": app.config.get("BRANDING_PUBLIC_LANDING_STRING", "Not configured"),
        "email_is_live": app.config.get("EMAIL_IS_LIVE", False),
        "backup_is_live": app.config.get("BACKUP_IS_LIVE", False),
        "video_explainer_panopto_server": app.config.get("VIDEO_EXPLAINER_PANOPTO_SERVER", None),
        "video_explainer_panopto_session": app.config.get("VIDEO_EXPLAINER_PANOPTO_SESSION", None),
    }

    if _static_ctx["video_explainer_panopto_server"] is not None and _static_ctx["video_explainer_panopto_session"] is not None:
        _static_ctx["enable_video_explainer"] = True
    else:
        _static_ctx["enable_video_explainer"] = False

    return _static_ctx


def _build_global_context():
    if not has_request_context():
        return {}

    roles = set(role.name for role in current_user.roles)
    if isinstance(current_user, User):
        mask_roles = set(role.name for role in current_user.mask_roles)
        visible_roles = roles.difference(mask_roles)
    else:
        visible_roles = roles

    is_faculty = "faculty" in visible_roles
    is_office = "office" in visible_roles
    is_student = "student" in visible_roles
    is_reports = "reports" in visible_roles

    is_root = "root" in visible_roles
    is_admin = "admin" in visible_roles
    is_edit_tags = "edit_tags" in visible_roles
    is_view_email = "view_email" in visible_roles
    is_manage_users = "manage_users" in visible_roles
    is_emailer = "email" in visible_roles

    base_context_data = get_global_context_data()
    matching_ready = base_context_data["matching_ready"]
    has_assessments = base_context_data["has_assessments"]

    # assumes _static_ctx has been suitably initialized
    return _static_ctx | {
        "current_time": datetime.now(),
        "real_user": _get_previous_login(),
        "home_dashboard_url": home_dashboard_url(),
        "is_faculty": is_faculty,
        "is_office": is_office,
        "is_student": is_student,
        "is_reports": is_reports,
        "is_convenor": is_faculty and current_user.faculty_data is not None and current_user.faculty_data.is_convenor,
        "is_root": is_root,
        "is_admin": is_admin,
        "is_edit_tags": is_edit_tags,
        "is_view_email": is_view_email,
        "is_manage_users": is_manage_users,
        "is_emailer": is_emailer,
        "matching_ready": matching_ready,
        "has_assessments": has_assessments,
    }


def render_template_context(template: str | Template | List[str | Template], **kwargs) -> str:
    context = _build_global_context()
    return render_template(template, **kwargs, **context)
