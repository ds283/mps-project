#
# Created by David Seery on 09/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from . import DEFAULT_STRING_LENGTH
from ..database import db


class EmailTemplateTypesMixin:
    pass


class EmailTemplate(db.Model, EmailTemplateTypesMixin):
    __tablename__ = "email_templates"

    id = db.Column(db.Integer(), primary_key=True)

    # tenant, if specified
    # if not specified, this template is taken to apply globally
    # otherwise it is taken to apply to all project classes in the tenant, unless they in turn have an override
    tenant_id = db.Column(db.Integer(), db.ForeignKey("tenants.id"), nullable=True)
    tenant = db.relationship("Tenant", backref=db.backref("email_templates", lazy="dynamic"))

    # project class, if specified
    pclass_id = db.Column(db.Integer(), db.ForeignKey("project_classes.id"), nullable=True)
    pclass = db.relationship("ProjectClass", backref=db.backref("email_templates", lazy="dynamic"))

    # specify the type of this email, drawn from EmailTemplateTypesMixin
    type = db.Column(db.Integer(), nullable=False)

    # specify the subject line
    subject = db.Column(db.String(DEFAULT_STRING_LENGTH, collation='utf8_bin'), nullable=False)

    # specify the body of the email in HTML format
    # we autogenerate a text equivalent
    html_body = db.Column(db.Text, nullable=False)
