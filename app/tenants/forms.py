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
from wtforms import BooleanField, SelectMultipleField, StringField, SubmitField
from wtforms.validators import InputRequired, Length
from wtforms_sqlalchemy.fields import QuerySelectMultipleField

from ..models import DEFAULT_STRING_LENGTH, ProjectClass
from ..shared.forms.mixins import SaveChangesMixin


class TenantMixin:
    name = StringField(
        "Tenant name",
        validators=[
            InputRequired(message="Tenant name is required"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
    )

    colour = StringField(
        "Colour",
        validators=[Length(max=DEFAULT_STRING_LENGTH)],
        description="Assign a colour to help identify this tenant",
    )

    in_2026_ATAS_campaign = BooleanField("In 2026 ATAS campaign", default=False)


class AddTenantForm(Form, TenantMixin):
    submit = SubmitField("Add new tenant")


class EditTenantForm(Form, TenantMixin, SaveChangesMixin):
    pass


def CalibrateAIConcernFormFactory(tenant_id: int):
    """
    Factory that builds a form for running the Mahalanobis AI-concern
    calibration for a given tenant.

    project_classes — the subset of the tenant's project classes to use
    years           — the academic years (ProjectClassConfig.year) to include;
                      rendered as a multi-select of all years present in the
                      tenant's data (template must populate choices at runtime)
    """

    def _get_pclasses():
        return ProjectClass.query.filter_by(tenant_id=tenant_id).order_by(ProjectClass.name).all()

    class CalibrateAIConcernForm(Form):
        project_classes = QuerySelectMultipleField(
            "Project classes",
            query_factory=_get_pclasses,
            get_label=lambda p: p.name,
            description="Select which project classes to include in the calibration. Leave all selected to use every project class belonging to this tenant.",
        )

        # Choices for 'years' are populated dynamically in the view based on
        # the years available in the tenant's data.
        years = SelectMultipleField(
            "Academic years",
            coerce=int,
            description="Select academic years to include. Defaults to pre-LLM years (≤ 2022).",
        )

        submit = SubmitField("Run calibration")

    return CalibrateAIConcernForm


def RecalculateAIConcernFormFactory(tenant_id: int):
    """
    Factory that builds a form for re-evaluating the Mahalanobis AI-concern
    flag on existing completed submissions for a given tenant.
    """

    def _get_pclasses():
        return ProjectClass.query.filter_by(tenant_id=tenant_id).order_by(ProjectClass.name).all()

    class RecalculateAIConcernForm(Form):
        project_classes = QuerySelectMultipleField(
            "Project classes",
            query_factory=_get_pclasses,
            get_label=lambda p: p.name,
            description="Select which project classes to recalculate. Leave all selected to recalculate across every project class.",
        )

        # Choices populated dynamically in the view.
        years = SelectMultipleField(
            "Academic years",
            coerce=int,
            description="Select which academic years to recalculate. Leave all selected to recalculate all years.",
        )

        submit = SubmitField("Recalculate AI concern")

    return RecalculateAIConcernForm
