#
# Created by David Seery on 26/05/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


# language=jinja2
_name = """
<a class="text-decoration-none" href="mailto:{{ u.email }}">{{ u.name }}</a>
"""


def download_log(downloads):
    data = [
        {
            "name": {"display": render_template_string(_name, u=d.downloader), "sortstring": d.downloader.last_name + d.downloader.first_name},
            "timestamp": {"display": d.timestamp.strftime("%a %d %b %Y %H:%M:%S"), "timestamp": d.timestamp.timestamp()},
        }
        for d in downloads
    ]

    return jsonify(data)
