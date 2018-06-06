#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from app.models import db, TaskRecord

from datetime import datetime


def queue_task(obj, name, owner_id=None, description=None):

    data = TaskRecord(id=obj.id,
                      name=name,
                      owner_id=owner_id,
                      description=description,
                      start_date=datetime.now(),
                      complete=False)

    db.session.add(data)
    db.session.commit()
