#
# Created by David Seery on 18/02/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import StringField, SubmitField, TextAreaField
from wtforms.validators import InputRequired, Optional


def SendEmailFormFactory(use_recipients=True):
    class SendEmailForm(Form):
        # recipients field if it is being used; if not, the form page will generate a
        # "clear recipients" button
        if use_recipients:
            recipient = StringField(
                "To", validators=[InputRequired()], description="Enter a list of comma-separated email addresses for the recipients"
            )
        else:
            clear_recipients = SubmitField("Clear recipients")

        # notify field
        notify_addrs = StringField(
            "Also notify",
            validators=[Optional()],
            description="Enter a list of comma-separated email addresses who will be sent copies of the email.",
        )

        # subject field
        subject = StringField("Subject", validators=[InputRequired()])

        # email body
        body = TextAreaField("", render_kw={"rows": 10}, validators=[InputRequired()])

        # send button
        send = SubmitField("Send")

    return SendEmailForm
