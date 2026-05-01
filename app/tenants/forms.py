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
from wtforms import BooleanField, SelectField, SelectMultipleField, StringField, SubmitField
from wtforms.validators import InputRequired, Length
from wtforms_alchemy.fields import QuerySelectMultipleField

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


class DeleteForm(Form):
    """Minimal form used solely to provide CSRF protection for destructive POST actions."""
    submit = SubmitField("Delete")


class AddTenantForm(Form, TenantMixin):
    submit = SubmitField("Add new tenant")


class EditTenantForm(Form, TenantMixin, SaveChangesMixin):
    pass



def AddAICalibrationFormFactory(tenant_id: int, llm_configs: list[tuple]):
    """
    Factory for the "add calibration" form.

    llm_configs: list of (model_name, context_window) pairs discovered from stored
                 submission data for this tenant; used to populate the LLM config selector.
    """

    def _get_pclasses():
        return (
            ProjectClass.query.filter(
                ProjectClass.tenant_id == tenant_id,
                ProjectClass.publish.is_(True),
            )
            .order_by(ProjectClass.name)
            .all()
        )

    llm_choices = [("", "— none (lexical only) —")] + [
        (f"{m}::{c}", f"{m}  (context: {c:,} tokens)") for m, c in llm_configs
    ]

    class AddAICalibrationForm(Form):
        feature_set = SelectField(
            "Calibration type",
            choices=[("lexical", "Lexical (3D — MATTR, MTLD, sentence CV)"),
                     ("full", "Full (4D — lexical + mean NLL)")],
            default="lexical",
            description="Choose 'Full' to include NLL predictability metrics. "
                        "A matching LLM configuration must be selected below.",
        )

        llm_config = SelectField(
            "LLM configuration",
            choices=llm_choices,
            default="",
            description="The (model, context-window) pair to use for full calibrations. "
                        "Leave as '— none —' for lexical-only calibrations. "
                        "Only configurations found in stored submission data are listed.",
        )

        project_classes = QuerySelectMultipleField(
            "Project classes",
            query_factory=_get_pclasses,
            get_label=lambda p: p.name,
            description="Select project classes to include. Each project class may belong to "
                        "at most one calibration per (feature set, LLM configuration) combination.",
        )

        years = SelectMultipleField(
            "Academic years",
            coerce=int,
            description="Select academic years to include in the calibration baseline. "
                        "For lexical calibrations, prefer pre-LLM years (≤ 2022).",
        )

        submit = SubmitField("Run and save calibration")

    return AddAICalibrationForm


def RecalculateAIConcernFormFactory(tenant_id: int):
    """
    Factory that builds a form for re-evaluating the Mahalanobis AI-concern
    flag on existing completed submissions for a given tenant.
    """

    def _get_pclasses():
        return (
            ProjectClass.query.filter(
                ProjectClass.tenant_id == tenant_id,
                ProjectClass.publish.is_(True),
            )
            .order_by(ProjectClass.name)
            .all()
        )

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

        full_recalculate = BooleanField(
            "Full recalculation (re-process cached text and recompute all lexical metrics)",
            default=False,
            description="Re-process the cached extracted text through the current metric "
                        "pipeline (MATTR, MTLD, burstiness, sentence CV) before reclassifying. "
                        "Picks up algorithm improvements in the metric implementation. "
                        "Slower than reclassification only.",
        )

        submit = SubmitField("Recalculate AI concern")

    return RecalculateAIConcernForm
