#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import StringField, SubmitField
from wtforms.validators import InputRequired, Length

from ..models import DEFAULT_STRING_LENGTH
from ..shared.forms.mixins import SaveChangesMixin


class TenantMixin:
    name = StringField(
        "Tenant name", validators=[InputRequired(message="Tenant name is required"), Length(max=DEFAULT_STRING_LENGTH)]
    )


class AddTenantForm(Form, TenantMixin):
    submit = SubmitField("Add new tenant")


class EditTenantForm(Form, TenantMixin, SaveChangesMixin):
    pass
