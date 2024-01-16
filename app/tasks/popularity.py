#
# Created by David Seery on 12/07/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime, timedelta
from typing import List, Tuple
from uuid import uuid1

from celery import chain, group
from dateutil import parser
from flask import current_app
from math import floor
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import LiveProject, ProjectClass, ProjectClassConfig, PopularityRecord


def compute_rank(self, num_live, rank_type, cid, query, accessor, writer):
    self.update_state(state="STARTED", meta={"msg": "Looking up current project class configuration for id={id}".format(id=cid)})

    try:
        # get most recent configuration record for this project class
        config: ProjectClassConfig = db.session.query(ProjectClassConfig).filter_by(id=cid).one()

    except SQLAlchemyError as e:
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    self.update_state(state="STARTED", meta={"msg": 'Update {type} ranking for project class "{name}"'.format(type=rank_type, name=config.name)})

    lowest_rank = None

    try:
        # dig out PopularityRecords with given datestamp and config_id
        if query.count() != num_live:
            raise RuntimeError("Number of records in group is incorrect: expected {exp}, found {obs}".format(exp=num_live, obs=query.count()))

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

                if lowest_rank is None or current_rank > lowest_rank:
                    lowest_rank = current_rank

                current_record += 1

            db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise

    except SQLAlchemyError as e:
        current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
        raise self.retry()

    except RuntimeError:
        raise self.retry()

    self.update_state(state="SUCCESS")
    return lowest_rank


def register_popularity_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def compute_popularity_data(self, liveid, datestamp, uuid, num_live):
        self.update_state(state="STARTED", meta={"msg": "Computing popularity score"})

        try:
            data = db.session.query(LiveProject).filter_by(id=liveid).one()

            # popularity score = page views + 4 * bookmarks + 10 * selection_score
            score = data.page_views

            bookmarks = data.bookmarks.count()
            score += 4 * bookmarks

            max_selections = data.config.project_class.initial_choices
            for item in data.selections:
                item_score = max_selections - item.rank + 1
                score += 10 * item_score

            rec = PopularityRecord(
                liveproject_id=data.id,
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
                total_number=num_live,
            )
            data.popularity_data.append(rec)

            db.session.commit()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state="SUCCESS")

    @celery.task(bind=True, default_retry_delay=30)
    def compute_popularity_score_rank(self, cid, uuid, num_live):
        query = db.session.query(PopularityRecord).filter_by(uuid=uuid, config_id=cid).order_by(PopularityRecord.score.desc())

        def accessor(x):
            return x.score

        def writer(x, r):
            x.score_rank = r

        return compute_rank(self, num_live, "popularity score", cid, query, accessor, writer)

    @celery.task(bind=True, default_retry_delay=30)
    def store_lowest_popularity_score_rank(self, lowest_rank, cid, uuid, num_live):
        self.update_state(state="STARTED", meta={"msg": "Storing lowest-rank for popularity score"})

        query = db.session.query(PopularityRecord).filter_by(uuid=uuid, config_id=cid)

        try:
            if query.count() != num_live:
                raise RuntimeError("Number of records in group is incorrect: expected {exp}, found {obs}".format(exp=num_live, obs=query.count()))

            try:
                records = query.all()

                for record in records:
                    record.lowest_score_rank = lowest_rank

                db.session.commit()

            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        except RuntimeError:
            raise self.retry()

        self.update_state(state="SUCCESS")

    @celery.task(bind=True, default_retry_delay=30)
    def compute_views_rank(self, cid, uuid, num_live):
        query = db.session.query(PopularityRecord).filter_by(uuid=uuid, config_id=cid).order_by(PopularityRecord.views.desc())

        def accessor(x):
            return x.views

        def writer(x, r):
            x.views_rank = r

        return compute_rank(self, num_live, "views", cid, query, accessor, writer)

    @celery.task(bind=True, default_retry_delay=30)
    def compute_bookmarks_rank(self, cid, uuid, num_live):
        query = db.session.query(PopularityRecord).filter_by(uuid=uuid, config_id=cid).order_by(PopularityRecord.bookmarks.desc())

        def accessor(x):
            return x.bookmarks

        def writer(x, r):
            x.bookmarks_rank = r

        return compute_rank(self, num_live, "bookmarks", cid, query, accessor, writer)

    @celery.task(bind=True, default_retry_delay=30)
    def compute_selections_rank(self, cid, uuid, num_live):
        query = db.session.query(PopularityRecord).filter_by(uuid=uuid, config_id=cid).order_by(PopularityRecord.selections.desc())

        def accessor(x):
            return x.selections

        def writer(x, r):
            x.selections_rank = r

        return compute_rank(self, num_live, "selections", cid, query, accessor, writer)

    @celery.task(bind=True, default_retry_delay=30)
    def update_project_popularity_data(self, pid):
        self.update_state(state="STARTED", meta={"msg": "Looking up current project class configuration for id={id}".format(id=pid)})

        try:
            # get most recent configuration record for this project class
            pcl: ProjectClass = db.session.query(ProjectClass).filter_by(id=pid).first()
            config: ProjectClassConfig = pcl.most_recent_config

        except SQLAlchemyError:
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": 'Update popularity data for project class "{name}"'.format(name=config.name)})

        # set up group of tasks to update popularity score of each LiveProject on this configuration
        # only need to work with projects that are open for student selections

        num_live = config.live_projects.count()
        datestamp = datetime.now()
        uuid = uuid1()

        # only compute popularity for project classes where student selections are open
        if config.selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
            compute = group(compute_popularity_data.si(proj.id, datestamp, uuid, num_live) for proj in config.live_projects)

            tasks = chain(
                [
                    compute,
                    compute_popularity_score_rank.si(config.id, uuid, num_live),
                    store_lowest_popularity_score_rank.s(config.id, uuid, num_live),
                    compute_views_rank.si(config.id, uuid, num_live),
                    compute_bookmarks_rank.si(config.id, uuid, num_live),
                    compute_selections_rank.si(config.id, uuid, num_live),
                ]
            )
            raise self.replace(tasks)

        self.update_state(state="SUCCESS")

    @celery.task(bind=True, default_retry_delay=30)
    def update_popularity_data(self):
        self.update_state(state="STARTED", meta={"msg": "Update popularity data"})

        try:
            pclass_ids = db.session.query(ProjectClass.id).filter_by(active=True).all()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        tasks = group(update_project_popularity_data.si(i.id) for i in pclass_ids)
        raise self.replace(tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def thin_bin(self, period: int, unit: str, input_bin: List[Tuple[int, str]]):
        self.update_state(state="STARTED", meta={"msg": "Thinning popularity record bin for {period} {unit}".format(period=period, unit=unit)})

        # sort records from the bin into order, then retain the record with the highest score
        # This means that re-running the thinning task is idempotent and stable under small changes in binning.
        # output_bin will eventually contain the retained record from this bin
        # Currently the second member of each tuple in input_bin isn't used; this is the datestamp of the
        # corresponding record, but currently we don't use that.
        # In the counterpart task for thinning backups we retain the oldest backup, but here we retain the highest
        # score. Both approaches are idempotent.

        # keep a list of records that we drop
        dropped = []

        try:
            # retain popularity record with the highest score
            records: List[PopularityRecord] = [db.session.query(PopularityRecord).filter_by(id=r[0]).first() for r in input_bin]

            highest_score = None
            retained_record = None

            for record in records:
                if record is not None and (highest_score is None or record.score > highest_score):
                    highest_score = record.score
                    retained_record = record

            if retained_record is not None:
                for record in records:
                    if record.id is not None and record.id != retained_record.id:
                        dropped.append((record.id, str(record.datestamp)))
                        db.session.delete(record)

                db.session.commit()

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state="SUCCESS")
        return {"period": period, "unit": unit, "retained": (retained_record.id, str(retained_record.datestamp)), "dropped": dropped}

    @celery.task(bind=True, default_retry_delay=30)
    def thin_popularity_data(self, liveid):
        self.update_state(state="STARTED", meta={"msg": "Building list of popularity records for LiveProject id={id}".format(id=liveid)})

        try:
            liveproject: LiveProject = db.session.query(LiveProject).filter_by(id=liveid).first()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        # extract time limits from parent project class
        keep_hourly = liveproject.config.project_class.keep_hourly_popularity
        keep_daily = liveproject.config.project_class.keep_daily_popularity

        # if keep_hourly is not set then behaviour is undefined, so just leave everything as it is and exit
        # note, it's OK for keep_daily to be undefined; in that case we keep daily records forever
        if keep_hourly is None:
            self.update_state(state="SUCCESS")
            return

        max_hourly_age = timedelta(days=keep_hourly)
        max_daily_age = None if keep_daily is None else max_hourly_age + timedelta(weeks=keep_daily)

        daily = {}
        weekly = {}

        now = datetime.now()

        # loop through all PopularityRecords attached to this LiveProject
        for record in liveproject.popularity_data:
            record: PopularityRecord

            # deduce current age of this record
            age = now - record.datestamp

            if age < max_hourly_age:
                # do nothing; we retain all hourly records younger than the cutoff
                pass

            elif max_daily_age is None or (max_daily_age is not None and age < max_daily_age):
                if age.days in daily:
                    daily[age.days].append((record.id, record.datestamp))
                else:
                    daily[age.days] = [(record.id, record.datestamp)]

            else:
                # work out age in weeks (as an integer)
                age_weeks = floor(float(age.days) / float(7))  # returns an Integer in Python3
                if age_weeks in weekly:
                    weekly[age_weeks].append((record.id, record.datestamp))
                else:
                    weekly[age_weeks] = [(record.id, record.datestamp)]

        daily_list = [thin_bin.s(k, "days", daily[k]) for k in daily]
        weekly_list = [thin_bin.s(k, "weeks", weekly[k]) for k in weekly]

        total_list = daily_list + weekly_list

        thin_tasks = group(*total_list)
        raise self.replace(thin_tasks)

    @celery.task(bind=True, default_retry_delay=30)
    def thin_project_popularity_data(self, pid):
        self.update_state(state="STARTED", meta={"msg": "Looking up current project class configuration for id={id}".format(id=pid)})

        try:
            # get most recent configuration record for this project class
            pcl: ProjectClass = db.session.query(ProjectClass).filter_by(id=pid).first()
            config: ProjectClassConfig = pcl.most_recent_config

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        self.update_state(state="STARTED", meta={"msg": 'Thin out popularity data for project class "{name}"'.format(name=config.name)})

        if config.selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_SELECTIONS_OPEN:
            tasks = group(thin_popularity_data.si(proj.id) for proj in config.live_projects)
            raise self.replace(tasks)

        self.update_state(state="SUCCESS")

    @celery.task(bind=True, default_retry_delay=30)
    def thin(self):
        self.update_state(state="STARTED", meta={"msg": "Thin out popularity data"})

        try:
            pclass_ids = db.session.query(ProjectClass.id).filter_by(active=True).all()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        tasks = group(thin_project_popularity_data.si(i.id) for i in pclass_ids)
        raise self.replace(tasks)
