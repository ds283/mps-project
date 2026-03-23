#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List, Tuple, Union

from ..database import db
from .academic import *
from .assessment import *
from .assets import *
from .associations import *
from .content import *
from .faculty import *
from .feedback import *
from .live_projects import *
from .matching import *
from .model_mixins import *
from .project_class import *
from .projects import *
from .scheduling import *
from .students import *
from .submissions import *
from .users import Role, User
from .utilities import *

# ############################


ProjectLike = Union[Project, LiveProject]
ProjectLikeList = List[ProjectLike]
ProjectDescLikeList = List[Tuple[ProjectLike, ProjectDescription]]
