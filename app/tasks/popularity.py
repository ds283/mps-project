#
# Created by David Seery on 12/07/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..models import db, LiveProject, ProjectClass, ProjectClassConfig, PopularityRecord

from celery import chain, group

from datetime import datetime


def register_popularity_tasks(celery):

    @celery.task(bind=True)
    def compute_popularity_index(self, liveid, num_live):

        self.update_state(state='STARTED', meta='Computing popularity index')

        try:

            data = db.session.query(LiveProject).filter_by(id=liveid).one()

            # popularity score = page views + 4 * bookmarks + 10 * selection_score
            score = data.page_views

            bookmarks = data.bookmarks.count()
            score += 4*bookmarks

            max_selections = data.config.project_class.initial_choices
            for item in data.selections:
                item_score = max_selections - item.rank + 1
                score += 10*item_score

            rec = PopularityRecord(liveproject_id=data.id,
                                   config_id=data.config_id,
                                   datestamp=datetime.now(),
                                   index=score,
                                   rank=None,
                                   total_number=num_live)
            data.popularity_data.append(rec)

            db.session.commit()

        except SQLAlchemyError:

            raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True)
    def update_project_popularity_indices(self, pid):

        self.update_state(state='STARTED', meta='Update popularity indices for project class')

        try:

            # get most recent configuration record for this project class
            config = db.session.query(ProjectClassConfig).filter_by(pclass_id=pid).order_by(ProjectClassConfig.year.desc()).one()

        except SQLAlchemyError:

            raise self.retry()

        # set up group of tasks to update popularity index of each LiveProject on this configuration
        # only need to work with projects that are open for student selections

        num_live = config.live_projects.count()

        if config.open:
            tasks = group(compute_popularity_index.si(p.id, num_live) for p in config.live_projects)
            tasks.apply_async()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True)
    def update_popularity_indices(self):

        self.update_state(state='STARTED', meta='Update popularity indices for project class')

        try:

            pclass_ids = db.session.query(ProjectClass.id).filter_by(active=True).all()

        except SQLAlchemyError:

            raise self.retry()

        tasks = group(update_project_popularity_indices.si(i) for i in pclass_ids)
        tasks.apply_async()

        self.update_state(state='SUCCESS')
