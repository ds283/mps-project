#
# Created by David Seery on 25/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

DEBUG = True  # enable Flask debugger
SQLALCHEMY_ECHO = False  # disable SQLAlchemy logging (takes a long time to emit all queries)

DEBUG_TB_PROFILER_ENABLED = False  # enable/disable profiling in the Flask debug toolbar
DEBUG_API_PREFIX = ''  # no special prefix for API (=Ajax) endpoints

PROFILE_TO_DISK = False  # determine whether to use Werkzeug profiler to write a .prof to disc
PROFILE_DIRECTORY = "./profiling"  # location of profiling data

# use Dozer to perform memory profiling?
PROFILE_MEMORY = True
