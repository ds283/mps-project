#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from .send_log_email import register_send_log_email
from .prune_email import register_prune_email
from .backup import register_backup_tasks
from .rollover import register_rollover_tasks

from .test import register_test_tasks
