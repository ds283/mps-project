#
# Created by David Seery on 25/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

DEBUG = True  # enable Flask debugger

SQLALCHEMY_ECHO = False  # disable SQLAlchemy logging (takes a long time to emit all queries)

DEBUG_TB_PROFILER_ENABLED = False  # enable/disable profiling in the Flask debug toolbar
DEBUG_API_PREFIX = ''  # no special prefix for API (=Ajax) endpoints

# our own, hand-rolled profiler:
# determine whether to use Werkzeug profiler to write a .prof to disk
# (from where we can use eg. SnakeViz as a GUI tool)
PROFILE_TO_DISK = bool(int(os.environ.get('PROFILE_TO_DISK', 0)))
PROFILE_DIRECTORY = os.environ.get('PROFILE_DIRECTORY')
PORFILE_RESTRICTIONS = json.loads(os.environ.get('PROFILE_RESTRICTIONS', '[]'))

# use Dozer to perform memory profiling?
PROFILE_MEMORY = bool(int(os.environ.get('PROFILE_MEMORY', 0)))
