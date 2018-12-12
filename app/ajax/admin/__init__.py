#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from .buildings import buildings_data
from .degree_programmes import degree_programmes_data
from .degree_types import degree_types_data
from .groups import groups_data
from .levels import FHEQ_levels_data
from .messages import messages_data
from .modules import modules_data
from .pclasses import pclasses_data
from .periods import periods_data
from .roles import roles_data
from .rooms import rooms_data
from .skill_groups import skill_groups_data
from .skills import skills_data
from .supervisors import supervisors_data

from .matching.compare_matches import compare_match_data
from .matching.match_view_faculty import faculty_view_data
from .matching.match_view_student import student_view_data
from .matching.matches import matches_data

from .presentations.assessor_availability import assessor_session_availability_data, presentation_assessors_data
from .presentations.outstanding_availability import outstanding_availability_data
from .presentations.presentations import presentation_assessments_data
from .presentations.schedule_view_sessions import schedule_view_sessions
from .presentations.schedule_view_faculty import schedule_view_faculty
from .presentations.schedules import assessment_schedules_data
from .presentations.sessions import assessment_sessions_data
from .presentations.submitter_availability import submitter_session_availability_data, presentation_attendees_data
