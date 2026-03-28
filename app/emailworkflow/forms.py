#
# Created by David Seery on 24/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_wtf import FlaskForm
from wtforms import DateTimeField, IntegerField, SubmitField
from wtforms.validators import DataRequired, NumberRange
from wtforms_alchemy import QuerySelectField

from app.shared.forms.queries import BuildWorkflowTemplateLabel


class EditWorkflowForm(FlaskForm):
    send_time = DateTimeField(
        "Target send time",
        format="%d/%m/%Y %H:%M",
        validators=[DataRequired(message="A target send time is required.")],
    )
    max_attachment_size = IntegerField(
        "Max attachment size (bytes)",
        validators=[
            DataRequired(message="A maximum attachment size is required."),
            NumberRange(min=0, message="Attachment size must be non-negative."),
        ],
    )
    template = QuerySelectField(
        "Email template",
        allow_blank=False,
        get_label=BuildWorkflowTemplateLabel,
        validators=[DataRequired(message="Please select a template.")],
    )
    submit = SubmitField("Update")
