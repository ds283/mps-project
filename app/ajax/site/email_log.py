#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify, url_for


_email_log_menu = \
"""
<div class="dropdown">
    <button class="btn btn-success btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu">
        <li>
            <a href="{{ url_for('admin.delete_email', id=email.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
    </ul>
</div>
"""

def email_log_data(emails):

    data = []

    for email in emails:
        data.append({ 'recipient': email.user.build_name() if email.user is not None
                            else '<span class="label label-warning">Not logged</span>',
                      'address': email.user.email if email.user is not None
                            else email.recipient if email.recipient is not None
                            else '<span class="label label-danger">Invalid</span>',
                      'date': email.send_date.strftime("%a %d %b %Y %H:%M:%S"),
                      'subject': '<a href="{link}">{sub}</a>'.format(link=url_for('admin.display_email', id=email.id),
                                                                     sub=email.subject),
                      'menu': render_template_string(_email_log_menu, email=email)
                      })

    return jsonify(data)
