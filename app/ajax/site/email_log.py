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
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.delete_email', id=email.id) }}">
                <i class="fa fa-trash"></i> Delete
            </a>
        </li>
    </ul>
</div>
"""

def email_log_data(emails):

    data = [{'recipient': e.user.name if e.user is not None
                else '<span class="label label-warning">Not logged</span>',
             'address': e.user.email if e.user is not None
                else e.recipient if e.recipient is not None
                else '<span class="label label-danger">Invalid</span>',
             'date': {
                 'display': e.send_date.strftime("%a %d %b %Y %H:%M:%S"),
                 'timestmap': e.send_date.timestamp()
             },
             'subject': '<a href="{link}">{sub}</a>'.format(link=url_for('admin.display_email', id=e.id),
                                                            sub=e.subject),
             'menu': render_template_string(_email_log_menu, email=e)} for e in emails]

    return jsonify(data)
