#
# Created by David Seery on 01/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

LANGUAGE_ANALYSIS_MONGO_URL = os.environ.get("LANGUAGE_ANALYSIS_MONGO_URL")
LANGUAGE_ANALYSIS_DATABASE = os.environ.get("LANGUAGE_ANALYSIS_DATABASE")
LANGUAGE_ANALYSIS_SCRAPED_TEXT_COLLECTION = os.environ.get(
    "LANGUAGE_ANALYSIS_SCRAPED_TEXT_COLLECTION"
)
