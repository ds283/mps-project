#
# Created by David Seery on 14/02/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from email.utils import getaddresses, formataddr

from flask import render_template, redirect, flash, session, request, current_app
from flask_security import roles_accepted, current_user

from . import services
from .forms import SendEmailFormFactory
from ..database import db
from ..models import User
from ..shared.utils import home_dashboard


@services.route("send_email", methods=["GET", "POST"])
@roles_accepted("admin", "root", "email")
def send_email():
    # attempt to extract a distribution list from the session
    to_list = request.args.getlist("to", None)

    if to_list is None:
        distribution_list = None
        length = 0
    else:
        distribution_list = [db.session.query(User).filter_by(id=n).first() for n in to_list]
        length = len(distribution_list)

    url = request.args.get("url", None)
    text = request.args.get("text", None)

    SendEmailForm = SendEmailFormFactory(use_recipients=False if distribution_list is not None else True)
    form = SendEmailForm(request.form)

    if form.is_submitted():
        if form.send.data is True:
            if form.validate():
                if distribution_list is None:
                    to_addresses = getaddresses([form.recipient.data])

                    if to_addresses is None or len(to_addresses) == 0:
                        flash('Could not parse list of "To" addresses', "error")

                else:
                    to_addresses = None

                notify_addresses = getaddresses([form.notify_addrs.data])
                reply_to = formataddr((current_user.name, current_user.email))

                celery = current_app.extensions["celery"]

                sent = False

                if distribution_list is not None:
                    send_mail = celery.tasks["app.tasks.services.send_distribution_list"]

                    task = send_mail.s(to_list, notify_addresses, form.subject.data, form.body.data, reply_to, current_user.id)
                    task.apply_async()
                    sent = True

                elif to_addresses is not None:
                    send_mail = celery.tasks["app.tasks.services.send_email_list"]

                    task = send_mail.s(to_addresses, notify_addresses, form.subject.data, form.body.data, reply_to, current_user.id)
                    task.apply_async()
                    sent = True

                if sent:
                    if url is not None:
                        return redirect(url)

                    return home_dashboard()

        elif hasattr(form, "clear_recipients") and form.clear_recipients.data is True:
            distribution_list = None
            to_list = None
            length = 0

    return render_template(
        "services/send_email.html", form=form, distribution_list=distribution_list, to_list=to_list, length=length, url=url, text=text
    )
