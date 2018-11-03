#
# Created by David Seery on 2018-11-02.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from celery import group
from celery.exceptions import Ignore

from ..database import db
from ..models import Project


def register_maintenance_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def maintenance(self):
        try:
            projects = db.session.query(Project).all()
        except SQLAlchemyError:
            raise self.retry()

        task = group(project_maintenance.s(p.id) for p in projects)
        task.apply_async()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True, default_retry_delay=30)
    def project_maintenance(self, pid):
        try:
            project = db.session.query(Project).filter_by(id=pid).first()
        except SQLAlchemyError:
            raise self.retry()

        if project is None:
            raise Ignore

        if project.maintenance():
            try:
                db.session.commit()
            except SQLAlchemyError:
                db.session.rollback()
                raise self.retry()

        self.update_state(state='SUCCESS')
