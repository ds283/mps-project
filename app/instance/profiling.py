#
# Created by David Seery on 02/11/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os
import json

# PyInstrument based endpoint profiling
PROFILE_PYINSTRUMENT = bool(int(os.environ.get('PROFILE_PYINSTRUMENT', 0)))

# Werkzeug cProfile based profiler
# determine whether to use Werkzeug profiler to write a .prof to disk
# (from where we can use eg. PyCharm or SnakeViz as a GUI tool)
PROFILE_TO_DISK = bool(int(os.environ.get('PROFILE_TO_DISK', 0)))
PROFILE_DIRECTORY = os.environ.get('PROFILE_DIRECTORY')
PROFILE_RESTRICTIONS = json.loads(os.environ.get('PROFILE_RESTRICTIONS', '[]'))

# use Dozer to perform memory profiling?
PROFILE_MEMORY = bool(int(os.environ.get('PROFILE_MEMORY', 0)))
