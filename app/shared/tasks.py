#
# Created by David Seery on 01/03/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from app.task_queue import progress_update


def post_task_update_msg(
    celery_self, task_id: int, celery_state: str, task_state: int, progress_percent: int, msg: str, autocommit: bool = True
) -> None:
    progress_update(task_id, task_state, progress=progress_percent, message=msg, autocommit=autocommit)
    celery_self.update_state(state=celery_state, meta={"msg": msg})
