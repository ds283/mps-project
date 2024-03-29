#
# Created by David Seery on 01/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from .assessment import register_assessment_tasks
from .assessors import register_assessor_tasks
from .availability import register_availability_tasks
from .background_tasks import register_background_tasks
from .backup import register_backup_tasks
from .batch_create import register_batch_create_tasks
from .canvas import register_canvas_tasks
from .close_selection import register_close_selection_tasks
from .cloud_api_audit import register_cloud_api_audit_tasks
from .email_notifications import register_email_notification_tasks
from .go_live import register_golive_tasks
from .issue_confirm import register_issue_confirm_tasks
from .maintenance import register_maintenance_tasks
from .marking import register_marking_tasks
from .matching import register_matching_tasks
from .matching_emails import register_matching_email_tasks
from .popularity import register_popularity_tasks
from .process_report import register_process_report_tasks
from .prune_email import register_prune_email
from .push_feedback import register_push_feedback_tasks
from .rollover import register_rollover_tasks
from .scheduling import register_scheduling_tasks
from .selecting import register_selecting_tasks
from .send_log_email import register_send_log_email
from .services import register_services_tasks
from .sessions import register_session_tasks
from .system import register_system_tasks
from .test import register_test_tasks
from .user_launch import register_user_launch_tasks
from .utilities import register_utility_tasks
