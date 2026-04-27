#
# Created by David Seery on 27/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import flash, redirect, request
from flask_security import roles_accepted

from app.convenor import convenor

from ..models import ProjectClass
from ..shared.context.global_context import render_template_context
from ..shared.utils import redirect_url
from ..shared.validators import validate_is_convenor


@convenor.route("/resources/<int:pclass_id>")
@roles_accepted("faculty", "admin", "root")
def resources(pclass_id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(pclass_id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    config = pclass.most_recent_config
    if config is None:
        flash(
            "Internal error: could not locate ProjectClassConfig. Please contact a system administrator.",
            "error",
        )
        return redirect(redirect_url())

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    return render_template_context(
        "convenor/dashboard/resources.html",
        pclass=pclass,
        config=config,
        url=url,
        text=text,
    )
