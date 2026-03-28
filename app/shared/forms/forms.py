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
from flask_wtf import FlaskForm
from wtforms import SubmitField
from wtforms.validators import DataRequired
from wtforms_alchemy import QuerySelectField

from .mixins import PeriodSelectorMixinFactory
from .queries import BuildWorkflowTemplateLabel
from ...models import ProjectClassConfig


class ChooseEmailTemplateForm(FlaskForm):
    template = QuerySelectField(
        "Email template",
        allow_blank=False,
        get_label=BuildWorkflowTemplateLabel,
        validators=[DataRequired(message="Please select an email template.")],
    )
    submit = SubmitField("Send")


class ChoosePairedEmailTemplatesForm(FlaskForm):
    """For triggers that send two distinct email types (e.g. notify + unneeded)."""

    template_primary = QuerySelectField(
        "Email template",
        allow_blank=False,
        get_label=BuildWorkflowTemplateLabel,
        validators=[DataRequired(message="Please select an email template.")],
    )
    template_secondary = QuerySelectField(
        "Email template",
        allow_blank=False,
        get_label=BuildWorkflowTemplateLabel,
        validators=[DataRequired(message="Please select an email template.")],
    )
    submit = SubmitField("Send")


def SelectSubmissionRecordFormFactory(config: ProjectClassConfig, is_admin: bool):
    class SelectSubmissionRecordForm(
        Form, PeriodSelectorMixinFactory(config, is_admin)
    ):
        pass

    return SelectSubmissionRecordForm
