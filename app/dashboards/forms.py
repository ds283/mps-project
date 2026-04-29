#
# Created by David Seery on 29/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form


class MarkingExportForm(Form):
    """
    Minimal button-only form used to POST the marking Excel export request.
    Carries no user-editable fields; its sole purpose is to provide CSRF
    protection via ``{{ form.hidden_tag() }}`` in the template.
    """

    pass
