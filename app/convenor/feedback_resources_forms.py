#
# Created by David Seery on 27/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import FileField, StringField, SubmitField, TextAreaField
from wtforms.validators import InputRequired, Length, Optional
from wtforms_alchemy import QuerySelectField

from ..models import DEFAULT_STRING_LENGTH, FeedbackTemplate
from ..database import db
from ..shared.forms.mixins import SaveChangesMixin
from ..shared.forms.queries import BuildTemplateTagName, GetActiveTemplateTags
from ..shared.forms.widgets import BasicTagSelectField


class FeedbackAssetMixin:
    label = StringField(
        "Label",
        validators=[
            InputRequired(message="A label is required"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
        description="A short, unique label for this asset within the project class.",
    )

    description = StringField(
        "Description",
        validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)],
        description="Optional description of this asset.",
    )


class UploadFeedbackAssetForm(Form, FeedbackAssetMixin):
    attachment = FileField(
        "File",
        description="Select a file to upload as the asset.",
    )

    submit = SubmitField("Upload asset")


class EditFeedbackAssetForm(Form, FeedbackAssetMixin, SaveChangesMixin):
    pass


class FeedbackTemplateMixin:
    label = StringField(
        "Label",
        validators=[
            InputRequired(message="A label is required"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
        description="A short, unique label for this template within the project class.",
    )

    description = StringField(
        "Description",
        validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)],
        description="Optional description of this template.",
    )

    template_body = TextAreaField(
        "Template body",
        validators=[Optional()],
        render_kw={"rows": 15},
        description="Jinja2 HTML template used to generate feedback reports.",
    )

    tags = BasicTagSelectField(
        "Tags",
        query_factory=GetActiveTemplateTags,
        get_label=BuildTemplateTagName,
        blank_text="Add tags...",
        validators=[Optional()],
        description="Optionally add tags to organise your templates. Type a new tag name to create one.",
    )


class AddFeedbackTemplateForm(Form, FeedbackTemplateMixin):
    submit = SubmitField("Add template")


class EditFeedbackTemplateForm(Form, FeedbackTemplateMixin, SaveChangesMixin):
    pass


def FeedbackRecipeFormFactory(pclass):
    pclass_id = pclass.id

    class FeedbackRecipeMixin:
        label = StringField(
            "Label",
            validators=[
                InputRequired(message="A label is required"),
                Length(max=DEFAULT_STRING_LENGTH),
            ],
            description="A short, unique label for this recipe within the project class.",
        )

        template = QuerySelectField(
            "Template",
            query_factory=lambda: db.session.query(FeedbackTemplate).filter_by(pclass_id=pclass_id),
            get_label=lambda t: t.label,
            allow_blank=True,
            blank_text="(no template selected)",
            validators=[Optional()],
            description="Select the primary feedback template used by this recipe.",
        )

    class AddFeedbackRecipeForm(Form, FeedbackRecipeMixin):
        submit = SubmitField("Add recipe")

    class EditFeedbackRecipeForm(Form, FeedbackRecipeMixin, SaveChangesMixin):
        pass

    return AddFeedbackRecipeForm, EditFeedbackRecipeForm
