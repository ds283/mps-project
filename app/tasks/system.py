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


def register_system_tasks(celery):

    pass
