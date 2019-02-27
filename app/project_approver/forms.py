#
# Created by David Seery on 2019-02-26.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import StringField, IntegerField, SelectField, SubmitField, TextAreaField, BooleanField
from wtforms.validators import InputRequired, Optional
from wtforms_alchemy.fields import QuerySelectField

from functools import partial


class EditCommentForm(Form):

    comment = TextAreaField('Edit your comment', render_kw={"rows": 5})

    limit_visibility = BooleanField('Limit visibility to approvals team')

    submit = SubmitField('Save changes')
