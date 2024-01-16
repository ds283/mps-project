#
# Created by David Seery on 02/09/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask_security.forms import Form

from .mixins import PeriodSelectorMixinFactory
from ...models import ProjectClassConfig


def SelectSubmissionRecordFormFactory(config: ProjectClassConfig, is_admin: bool):
    class SelectSubmissionRecordForm(Form, PeriodSelectorMixinFactory(config, is_admin)):
        pass

    return SelectSubmissionRecordForm
