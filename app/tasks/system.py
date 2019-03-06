#
# Created by David Seery on 2018-12-07.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template
from flask_mail import Message

from celery.exceptions import Ignore
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User

from ..task_queue import register_task

from datetime import datetime

from gc import get_stats


def register_system_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def email_garbage_collection_stats(self):
        data = get_stats(memory_pressure=True)

        send_log_email = celery.tasks['app.tasks.send_log_email.send_log_email']
        msg = Message(subject='[mpsproject] garbage collection statistics',
                      sender=current_app.config['MAIL_DEFAULT_SENDER'],
                      reply_to=current_app.config['MAIL_REPLY_TO'],
                      recipients=current_app.config['ADMIN_EMAIL'])

        msg.body = render_template('email/system/garbage_collection.txt', data=data, now=datetime.now())

        # register a new task in the database
        task_id = register_task(msg.subject, description='Send periodic garbage collection statistics')
        send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

        return 1
