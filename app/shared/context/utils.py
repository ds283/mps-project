#
# Created by David Seery on 19/01/2024$.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ...database import db
from ...models import ProjectClass


def get_pclass_list():
    return db.session.query(ProjectClass).filter_by(active=True).order_by(ProjectClass.name.asc()).all()


def get_pclass_config_list(pcs=None):
    if pcs is None:
        pcs = get_pclass_list()

    cs = [pclass.most_recent_config for pclass in pcs]

    # strip out 'None' entries before returning
    return [x for x in cs if x is not None]
