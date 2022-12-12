#
# Created by David Seery on 12/12/2022.
# Copyright (c) 2022 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime

from flask import flash, current_app
from flask_security import current_user
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import ProjectTagGroup, ProjectTag


def create_new_tags(form):
    matched, unmatched = form.tags.data

    if len(unmatched) > 0:
        default_group = db.session.query(ProjectTagGroup).filter_by(default=True).first()
        if default_group is None:

            default_group = db.session.query(ProjectTagGroup).first()
            if default_group is not None:
                flash('No default tag group has been set. Appending newly defined tags to the '
                      'group "{group}".'.format(group=default_group.name), 'warning')
            else:
                flash('No default tag group has been set. Newly defined tags have been '
                      'discarded.', 'error')

        if default_group is not None:
            for label in unmatched:
                new_tag = ProjectTag(name=label,
                                     group=default_group,
                                     colour=None,
                                     active=True,
                                     creator_id=current_user.id,
                                     creation_timestamp=datetime.now())
                try:
                    db.session.add(new_tag)
                    matched.append(new_tag)
                except SQLAlchemyError as e:
                    current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                    flash('Could not add newly defined tag "{tag}" due to a database error. '
                          'Please contact a system administrator'.format(tag=label), 'error')

    return matched