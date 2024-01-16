#
# Created by David Seery on 02/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template

from ..database import db
from ..shared.utils import get_current_year

import re


def render_project(
    data,
    desc,
    form=None,
    text=None,
    url=None,
    show_selector=True,
    allow_approval=False,
    show_comments=False,
    comments=[],
    all_comments=False,
    all_workflow=False,
    pclass_id=None,
    workflow_history=[],
):
    current_year = get_current_year()

    if hasattr(data, "config"):
        archived = data.config is None or (current_year != data.config.year)
    else:
        # if config attribute is missing, most likely reason is that data is a Project rather than a LiveProject
        archived = False

    if hasattr(data, "hidden"):
        hidden = data.hidden
    else:
        hidden = False

    # without the sel variable, won't render any of the student-specific items
    return render_template(
        "student/show_project.html",
        title=data.name,
        project=data,
        desc=desc,
        form=form,
        text=text,
        url=url,
        show_selector=show_selector,
        allow_approval=allow_approval,
        show_comments=show_comments,
        comments=comments,
        all_comments=all_comments,
        all_workflow=all_workflow,
        pclass_id=pclass_id,
        workflow_history=workflow_history,
        archived=archived,
        hidden=hidden,
    )


def do_confirm(sel, project):
    if not project.is_waiting(sel):
        return False

    req = project.get_confirm_request(sel)
    if req is None:
        return False

    req.confirm()
    db.session.commit()

    return True


def do_deconfirm(sel, project):
    if not project.is_confirmed(sel):
        return False

    req = project.get_confirm_request(sel)
    if req is None:
        return False

    req.remove()
    db.session.delete(req)
    db.session.commit()

    return True


def do_deconfirm_to_pending(sel, project):
    if not project.is_confirmed(sel):
        return False

    req = project.get_confirm_request(sel)
    if req is None:
        return False

    req.waiting()
    db.session.commit()

    return True


def do_cancel_confirm(sel, project):
    if not project.is_waiting(sel):
        return False

    req = project.get_confirm_request(sel)
    if req is None:
        return False

    req.remove()
    db.session.delete(req)
    db.session.commit()

    return True
