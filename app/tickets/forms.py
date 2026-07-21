#
# Created by David Seery on 21/07/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
WTForms for the ticket detail view. Simple state actions (status change, assign/unassign, label
add/remove, watch/unwatch) carry their target in the URL and reuse the shared ConfirmActionForm for
CSRF; only the two content-bearing actions (comment, log email) need dedicated forms.
"""

from flask_security.forms import Form
from wtforms import (
    BooleanField,
    DateTimeField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, Optional

from ..models import TicketEmail


class TicketCommentForm(Form):
    body = TextAreaField("Comment", validators=[DataRequired()])

    # Phase 3 stores the intent only; the actual subscriber fan-out is wired in Phase 7.
    notify = BooleanField("Email subscribers", default=True)

    submit = SubmitField("Comment")
    submit_resolve = SubmitField("Comment & resolve")


class TicketLogEmailForm(Form):
    direction = SelectField(
        "Direction",
        coerce=int,
        choices=[(TicketEmail.OUTBOUND, "Outbound"), (TicketEmail.INBOUND, "Inbound / received")],
        default=TicketEmail.OUTBOUND,
    )
    from_addr = StringField("From", validators=[Optional(), Length(max=255)])
    to_addrs = StringField("To", validators=[Optional(), Length(max=255)])
    subject = StringField("Subject", validators=[DataRequired(), Length(max=255)])
    body = TextAreaField("Body", validators=[Optional()])

    submit = SubmitField("Log email")


class TicketComposeForm(Form):
    """
    New-ticket form (design screens 2b faculty / 3b office). The subject picker is a select2
    multiple whose option values are opaque tokens ("sub:<id>", "sel:<id>", "pc:<id>"); the
    candidate set is scoped by role and enforced server-side, so validate_choice is disabled here
    and the view re-validates every submitted token. Labels are label ids, likewise re-checked.
    """

    subjects = SelectMultipleField("What is this ticket about?", coerce=str, validate_choice=False)
    title = StringField("Title", validators=[DataRequired(), Length(max=255)])
    description = TextAreaField("Description", validators=[Optional()])
    due_date = DateTimeField("Due date", format="%d/%m/%Y", validators=[Optional()])
    labels = SelectMultipleField("Labels", coerce=int, validate_choice=False)

    submit = SubmitField("Create ticket")
