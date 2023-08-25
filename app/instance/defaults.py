#
# Created by David Seery on 25/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# TODO: consider whether these configuration variables should be handled in some other way

# DEFAULT ASSET LICENSES

FACULTY_DEFAULT_LICENSE = "Work"
STUDENT_DEFAULT_LICENSE = "Exam"
OFFICE_DEFAULT_LICENSE = "Work"

# user-facing defaults

DEFAULT_PROJECT_CAPACITY = 2
DEFAULT_ASSESSORS = 5

DEFAULT_SIGN_OFF_STUDENTS = True
DEFAULT_ENFORCE_CAPACITY = True
DEFAULT_SHOW_POPULARITY = True
DEFAULT_DONT_CLASH_PRESENTATIONS = True

DEFAULT_USE_ACADEMIC_TITLE = True

# delay between precompute cycles, measured in seconds
PRECOMPUTE_DELAY = 1800
