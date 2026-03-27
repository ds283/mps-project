#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# ############################
from typing import List, Tuple, Union

from .academic import *
from .assessment import *
from .assets import *
from .associations import *
from .choices import (
    academic_titles,
    academic_titles_dict,
    auto_enrol_year_choices,
    email_freq_choices,
    extent_choices,
    matching_history_choices,
    semester_choices,
    session_choices,
    short_academic_titles,
    short_academic_titles_dict,
    solver_choices,
    start_year_choices,
    student_level_choices,
    year_choices,
)
from .content import *
from .defaults import (
    DEFAULT_ASSIGNED_MARKERS,
    DEFAULT_ASSIGNED_MODERATORS,
    DEFAULT_STRING_LENGTH,
    IP_LENGTH,
    PASSWORD_HASH_LENGTH,
    SERIALIZED_LAYOUT_LENGTH,
    YEAR_LENGTH,
)
from .emails import *
from .faculty import *
from .feedback import *
from .live_projects import *
from .markingevent import *
from .matching import *
from .model_mixins import *
from .project_class import *
from .projects import *
from .scheduler import *
from .scheduling import *
from .students import *
from .submissions import *
from .tenants import *
from .users import *
from .utilities import *
from .journal import *
from .workflow_log import *

ProjectLike = Union[Project, LiveProject]
ProjectLikeList = List[ProjectLike]
ProjectDescLikeList = List[Tuple[ProjectLike, ProjectDescription]]
