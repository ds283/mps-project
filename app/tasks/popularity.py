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
from uuid import uuid1


def compute_rank(self, num_live, rank_type, cid, query, accessor, writer):

    self.update_state(state='STARTED',
                      meta='Looking up current project class configuration for id={id}'.format(id=cid))

    try:

        # get most recent configuration record for this project class
        config = db.session.query(ProjectClassConfig).filter_by(id=cid).one()

    except SQLAlchemyError:

        raise self.retry()

    self.update_state(state='STARTED',
                      meta='Update {type} ranking for project class "{name}"'.format(type=rank_type,
                                                                                     name=config.project_class.name))

    try:

        # dig out PopularityRecords with given datestamp and config_id
        if query.count() != num_live:
            raise RuntimeError(
                'Number of records in group is incorrect: '
                'expected {exp}, found {obs}'.format(exp=num_live, obs=query.count()))

        current_rank = 1
        current_record = 1
        current_value = None

        try:

            records = query.all()
            for record in records:

                this_value = accessor(record)

                if current_value is None or this_value < current_value:
                    current_rank = current_record
                    current_value = this_value

                writer(record, current_rank)
                current_record += 1

            db.session.commit()

        except SQLAlchemyError:

            db.session.rollback()
            raise

    except SQLAlchemyError:

        raise self.retry()

    except RuntimeError:

        raise self.retry()

    self.update_state(state='SUCCESS')


def register_popularity_tasks(celery):

    @celery.task(bind=True)
    def compute_popularity_data(self, liveid, datestamp, uuid, num_live):

        self.update_state(state='STARTED', meta='Computing popularity score')

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
                                   datestamp=datestamp,
                                   uuid=uuid,
                                   score=score,
                                   views=data.page_views,
                                   bookmarks=data.bookmarks.count(),
                                   selections=data.selections.count(),
                                   score_rank=None,
                                   views_rank=None,
                                   bookmarks_rank=None,
                                   selections_rank=None,
                                   total_number=num_live)
            data.popularity_data.append(rec)

            db.session.commit()

        except SQLAlchemyError:

            raise self.retry()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True)
    def compute_popularity_score_rank(self, cid, uuid, num_live):

        query = db.session.query(PopularityRecord) \
            .filter_by(uuid=uuid, config_id=cid) \
            .order_by(PopularityRecord.score.desc())

        def accessor(x):
            return x.score

        def writer(x, r):
            x.score_rank = r

        return compute_rank(self, num_live, "popularity score", cid, query, accessor, writer)


    @celery.task(bind=True)
    def compute_views_rank(self, cid, uuid, num_live):

        query = db.session.query(PopularityRecord) \
            .filter_by(uuid=uuid, config_id=cid) \
            .order_by(PopularityRecord.views.desc())

        def accessor(x):
            return x.views

        def writer(x, r):
            x.views_rank = r

        return compute_rank(self, num_live, "views", cid, query, accessor, writer)


    @celery.task(bind=True)
    def compute_bookmarks_rank(self, cid, uuid, num_live):

        query = db.session.query(PopularityRecord) \
            .filter_by(uuid=uuid, config_id=cid) \
            .order_by(PopularityRecord.bookmarks.desc())

        def accessor(x):
            return x.bookmarks

        def writer(x, r):
            x.bookmarks_rank = r

        return compute_rank(self, num_live, "bookmarks", cid, query, accessor, writer)


    @celery.task(bind=True)
    def compute_selections_rank(self, cid, uuid, num_live):

        query = db.session.query(PopularityRecord) \
            .filter_by(uuid=uuid, config_id=cid) \
            .order_by(PopularityRecord.selections.desc())

        def accessor(x):
            return x.selections

        def writer(x, r):
            x.selections_rank = r

        return compute_rank(self, num_live, "selections", cid, query, accessor, writer)


    @celery.task(bind=True)
    def update_project_popularity_data(self, pid):

        self.update_state(state='STARTED',
                          meta='Looking up current project class configuration for id={id}'.format(id=pid))

        try:

            # get most recent configuration record for this project class
            config = db.session.query(ProjectClassConfig) \
                .filter_by(pclass_id=pid) \
                .order_by(ProjectClassConfig.year.desc()).one()

        except SQLAlchemyError:

            raise self.retry()

        self.update_state(state='STARTED',
                          meta='Update popularity data for project class "{name}"'.format(
                              name=config.project_class.name))

        # set up group of tasks to update popularity score of each LiveProject on this configuration
        # only need to work with projects that are open for student selections

        num_live = config.live_projects.count()
        datestamp = datetime.now()
        uuid = uuid1()

        if config.open:

            compute = group(compute_popularity_data.si(proj.id, datestamp, uuid, num_live) for proj in config.live_projects)

            job = chain([compute, compute_popularity_score_rank.si(config.id, uuid, num_live),
                                  compute_views_rank.si(config.id, uuid, num_live),
                                  compute_bookmarks_rank.si(config.id, uuid, num_live),
                                  compute_selections_rank.si(config.id, uuid, num_live)])

            job.apply_async()

        self.update_state(state='SUCCESS')


    @celery.task(bind=True)
    def update_popularity_data(self):

        self.update_state(state='STARTED', meta='Update popularity data')

        try:

            pclass_ids = db.session.query(ProjectClass.id).filter_by(active=True).all()

        except SQLAlchemyError:

            raise self.retry()

        tasks = group(update_project_popularity_data.si(i) for i in pclass_ids)
        tasks.apply_async()

        self.update_state(state='SUCCESS')
