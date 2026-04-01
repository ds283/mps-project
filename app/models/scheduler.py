#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
import json
from datetime import datetime, timedelta

from celery import schedules
from sqlalchemy.event import listens_for

from ..database import db

# Models imported from thirdparty/celery_sqlalchemy_scheduler


class CrontabSchedule(db.Model):
    __tablename__ = "celery_crontabs"

    id = db.Column(db.Integer, primary_key=True)
    minute = db.Column(db.String(64), default="*")
    hour = db.Column(db.String(64), default="*")
    day_of_week = db.Column(db.String(64), default="*")
    day_of_month = db.Column(db.String(64), default="*")
    month_of_year = db.Column(db.String(64), default="*")

    @property
    def schedule(self):
        return schedules.crontab(
            minute=self.minute,
            hour=self.hour,
            day_of_week=self.day_of_week,
            day_of_month=self.day_of_month,
            month_of_year=self.month_of_year,
        )

    @classmethod
    def from_schedule(cls, dbsession, schedule):
        spec = {
            "minute": schedule._orig_minute,
            "hour": schedule._orig_hour,
            "day_of_week": schedule._orig_day_of_week,
            "day_of_month": schedule._orig_day_of_month,
            "month_of_year": schedule._orig_month_of_year,
        }
        try:
            query = dbsession.query(CrontabSchedule)
            query = query.filter_by(**spec)
            existing = query.one()
            return existing
        except db.exc.NoResultFound:
            return cls(**spec)
        except db.exc.MultipleResultsFound:
            query = dbsession.query(CrontabSchedule)
            query = query.filter_by(**spec)
            query.delete()
            dbsession.commit()
            return cls(**spec)


class IntervalSchedule(db.Model):
    __tablename__ = "celery_intervals"

    id = db.Column(db.Integer, primary_key=True)
    every = db.Column(db.Integer, nullable=False)
    period = db.Column(db.String(24))

    @property
    def schedule(self):
        return schedules.schedule(timedelta(**{self.period: self.every}))

    @classmethod
    def from_schedule(cls, dbsession, schedule, period="seconds"):
        every = max(schedule.run_every.total_seconds(), 0)
        try:
            query = dbsession.query(IntervalSchedule)
            query = query.filter_by(every=every, period=period)
            existing = query.one()
            return existing
        except db.exc.NoResultFound:
            return cls(every=every, period=period)
        except db.exc.MultipleResultsFound:
            query = dbsession.query(IntervalSchedule)
            query = query.filter_by(every=every, period=period)
            query.delete()
            dbsession.commit()
            return cls(every=every, period=period)


class DatabaseSchedulerEntry(db.Model):
    __tablename__ = "celery_schedules"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255, collation="utf8_bin"))
    task = db.Column(db.String(255, collation="utf8_bin"))
    interval_id = db.Column(db.Integer, db.ForeignKey("celery_intervals.id"))
    crontab_id = db.Column(db.Integer, db.ForeignKey("celery_crontabs.id"))
    arguments = db.Column(db.String(255), default="[]")
    keyword_arguments = db.Column(db.String(255, collation="utf8_bin"), default="{}")
    queue = db.Column(db.String(255))
    exchange = db.Column(db.String(255))
    routing_key = db.Column(db.String(255))
    expires = db.Column(db.DateTime)
    enabled = db.Column(db.Boolean, default=True)
    last_run_at = db.Column(db.DateTime)
    total_run_count = db.Column(db.Integer, default=0)
    date_changed = db.Column(db.DateTime)

    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    owner = db.relationship(
        "User", backref=db.backref("scheduled_tasks", lazy="dynamic")
    )

    interval = db.relationship(
        IntervalSchedule, backref=db.backref("entries", lazy="dynamic")
    )
    crontab = db.relationship(
        CrontabSchedule, backref=db.backref("entries", lazy="dynamic")
    )

    @property
    def args(self):
        return json.loads(self.arguments)

    @args.setter
    def args(self, value):
        self.arguments = json.dumps(value)

    @property
    def kwargs(self):
        kwargs_ = json.loads(self.keyword_arguments)
        if self.task == "app.tasks.backup.backup" and isinstance(kwargs_, dict):
            if "owner_id" in kwargs_:
                del kwargs_["owner_id"]
            kwargs_["owner_id"] = self.owner_id
        return kwargs_

    @kwargs.setter
    def kwargs(self, kwargs_):
        if self.task == "app.tasks.backup.backup" and isinstance(kwargs_, dict):
            if "owner_id" in kwargs_:
                del kwargs_["owner_id"]
        self.keyword_arguments = json.dumps(kwargs_)

    @property
    def schedule(self):
        if self.interval:
            return self.interval.schedule
        if self.crontab:
            return self.crontab.schedule


@listens_for(DatabaseSchedulerEntry, "before_insert")
def _set_entry_changed_date(mapper, connection, target):
    target.date_changed = datetime.now()
