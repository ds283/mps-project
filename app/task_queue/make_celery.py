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

from celery import Celery
from celery.signals import worker_init


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

    class ContextTask(celery.Task):
        abstract = True

        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    return celery
