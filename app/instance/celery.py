#
# Created by David Seery on 24/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

CELERY = {
    "result_backend": os.environ.get("CELERY_RESULT_BACKEND"),
    "broker_url": os.environ.get("CELERY_BROKER_URL"),
    "accept_content": ["json", "pickle"],
    "task_create_missing_queues": True,
    "task_default_queue": "default",
    "task_routes": {"app.task.ping.ping": {"queue": "priority"}},
    "chord_unlock_max_retries": 100,
}
