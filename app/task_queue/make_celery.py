#
# Created by David Seery on 25/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
# Adapted from: Flask design patterns, http://flask.pocoo.org/docs/0.12/patterns/celery/
#

from datetime import datetime

from celery import Celery
from celery.signals import task_failure, task_revoked, worker_init


@worker_init.connect
def limit_chord_unlock_tasks(sender, **kwargs):
    """
    Set max_retries for chord.unlock tasks to avoid infinitely looping
    tasks. (see celery/celery#1700 or celery/celery#2725)
    """
    task = sender.app.tasks["celery.chord_unlock"]
    if task.max_retries is None:
        retries = getattr(sender.app.conf, "chord_unlock_max_retries", 100)
        print(f"@@ Setting max_retries for celery.chord_unlock to {retries}")
        task.max_retries = retries


def make_celery(app):
    celery_config = app.config["CELERY"]
    celery = Celery(
        app.import_name,
        backend=celery_config["result_backend"],
        broker=celery_config["broker_url"],
        broker_transport_options={"ttl": True},
        accept_content=celery_config["accept_content"],
        beat_scheduler="app.sqlalchemy_scheduler:DatabaseScheduler",
    )

    celery.config_from_object(celery_config)

    # Store a back-reference to the Flask app so that signal handlers (e.g.
    # worker_ready) can open an explicit app context without relying on
    # current_app, which may not be accessible from the signal's thread/context.
    celery.flask_app = app

    class ContextTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    @task_failure.connect
    def on_task_failure(task_id, exception, traceback, einfo, sender=None, **kwargs):
        """
        Catch-all signal handler: if a Celery task fails and its task_id matches a TaskRecord
        (i.e. it was launched directly with task_id=uuid), mark the TaskRecord as FAILURE.
        Tasks inside self.replace() chains have auto-generated IDs and won't match here;
        those must be handled by per-chain .on_error() callbacks.
        """
        with app.app_context():
            from ..database import db
            from ..models import TaskRecord
            try:
                task = db.session.query(TaskRecord).filter_by(id=task_id).first()
                if task is not None and task.status in (TaskRecord.PENDING, TaskRecord.RUNNING):
                    task.status = TaskRecord.FAILURE
                    task.message = f"Unexpected failure: {str(exception)[:200]}"
                    task.last_updated = datetime.now()
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                app.logger.exception("on_task_failure signal: database error", exc_info=e)

    @task_revoked.connect
    def on_task_revoked(request, terminated, signum, expired, sender=None, **kwargs):
        """
        If a Celery task is revoked and its task_id matches a TaskRecord, mark it TERMINATED.
        """
        with app.app_context():
            from ..database import db
            from ..models import TaskRecord
            try:
                task = db.session.query(TaskRecord).filter_by(id=request.id).first()
                if task is not None and task.status in (TaskRecord.PENDING, TaskRecord.RUNNING):
                    task.status = TaskRecord.TERMINATED
                    task.message = "Task was revoked"
                    task.last_updated = datetime.now()
                    db.session.commit()
            except Exception as e:
                db.session.rollback()
                app.logger.exception("on_task_revoked signal: database error", exc_info=e)

    return celery
