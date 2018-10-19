#
# Created by David Seery on 2018-10-16.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form

from ..shared.forms.mixins import SaveChangesMixin, ThemeMixin


class OfficeSettingsForm(Form, ThemeMixin, SaveChangesMixin):

    pass
