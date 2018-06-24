#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import jsonify

def golive_data(config):

    data = [{'name': f.user.build_name(),
             'email': '<a href="mailto:{em}">{em}</a>'.format(em=f.user.email),
             'available': f.projects_offered_label(config.project_class),
             'unoffer': f.projects_unofferable_label()} for f in config.golive_required]

    return jsonify(data)
