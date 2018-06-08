#
# Created by David Seery on 07/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


import random
import time

from ..task_queue import progress_update
from ..models import TaskRecord


def register_test_tasks(celery):

    @celery.task(bind=True)
    def test_task(self, task_id):
        """Background task that runs a long function with progress reports."""

        verb = ['Starting up', 'Booting', 'Repairing', 'Loading', 'Checking']
        adjective = ['master', 'radiant', 'silent', 'harmonic', 'fast']
        noun = ['solar array', 'particle reshaper', 'cosmic ray', 'orbiter', 'bit']

        message = ''
        progress_update(task_id, TaskRecord.RUNNING, 0, "Test task initializing", autocommit=True)

        total = random.randint(50, 100)

        for i in range(total):

            if not message or random.random() < 0.25:
                message = '{0} {1} {2}...'.format(random.choice(verb),
                                                  random.choice(adjective),
                                                  random.choice(noun))
            self.update_state(state='PROGRESS',
                              meta={'current': i, 'total': total,
                                    'status': message})

            progress_update(task_id, TaskRecord.RUNNING, round(100.0*float(i)/float(total)), message, autocommit=True)

            time.sleep(1)

        progress_update(task_id, TaskRecord.SUCCESS, 100, "Test task finalized", autocommit=True)

        return {'current': 100, 'total': 100, 'status': 'Task completed!',
                'result': 42}
