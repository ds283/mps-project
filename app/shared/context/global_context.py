#
# Created by David Seery on 19/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>

from .assessments import get_assessment_data
from .matching import get_matching_data
from .utils import get_pclass_list, get_pclass_config_list


def get_global_context_data():
    pcs = get_pclass_list()
    configs = get_pclass_config_list(pcs)

    assessment = get_assessment_data(configs)
    matching = get_matching_data(configs)

    assessment.update(matching)
    return assessment
