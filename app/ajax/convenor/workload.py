#
# Created by David Seery on 09/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template

from ...models import FacultyData, ProjectClassConfig, User


def faculty_workload_data(config: ProjectClassConfig, faculty):
    data = []

    u: User
    fd: FacultyData
    for u, fd in faculty:
        CATS_sup, CATS_mark, CATS_moderate, CATS_pres = fd.CATS_assignment(config)
        projects = fd.supervisor_assignments(config=config).all()
        marking = fd.marker_assignments(config=config).all()
        moderating = fd.moderator_assignments(config=config).all()
        presentations = fd.presentation_assignments(config=config).all()

        data.append(
            {
                "name": '<a class="text-decoration-none" href="mailto:{email}">{name}</a>'.format(
                    email=u.email, name=u.name
                ),
                "supervising": render_template(
                    "convenor/workload/_supervising.html",
                    f=fd,
                    config=config,
                    recs=projects,
                ),
                "marking": render_template(
                    "convenor/workload/_assessing.html",
                    f=fd,
                    config=config,
                    recs=marking,
                ),
                "moderating": render_template(
                    "convenor/workload/_assessing.html",
                    f=fd,
                    config=config,
                    recs=moderating,
                ),
                "presentations": render_template(
                    "convenor/workload/_presentations.html",
                    f=fd,
                    config=config,
                    recs=presentations,
                ),
                "workload": render_template(
                    "convenor/workload/_workload.html",
                    CATS_sup=CATS_sup,
                    CATS_mark=CATS_mark,
                    CATS_moderate=CATS_moderate,
                    CATS_pres=CATS_pres,
                    f=fd,
                    config=config,
                ),
            }
        )

    return data
