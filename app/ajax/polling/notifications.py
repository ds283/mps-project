#
# Created by David Seery on 06/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import jsonify


def notifications_payload(notifications):

    data = [{'uuid': n.uuid,
             'type': n.type,
             'payload': n.payload,
             'timestamp': n.timestamp} for n in notifications]

    return jsonify(data)
