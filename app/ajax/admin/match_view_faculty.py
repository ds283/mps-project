#
# Created by David Seery on 22/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify, render_template_string


def faculty_view_data(records):

    data = [{'name': '',
             'projects': '',
             'marking': '',
             'workload': ''} for r in records]

    return jsonify(data)
