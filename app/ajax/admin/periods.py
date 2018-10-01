#
# Created by David Seery on 2018-09-27.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


_presentation = \
"""
{% if flag %}
    <span class="label label-success">Yes</span>
{% else %}
    <span class="label label-default">No</span>
{% endif %}
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-default btn-sm btn-block dropdown-toggle" type="button" data-toggle="dropdown">
        Actions
        <span class="caret"></span>
    </button>
    <ul class="dropdown-menu dropdown-menu-right">
        <li>
            <a href="{{ url_for('admin.edit_period', id=period.id) }}">
                <i class="fa fa-cogs"></i> Edit period
            </a>
        </li>
        <li>
            <a href="{{ url_for('admin.delete_period', id=period.id) }}">
                <i class="fa fa-trash"></i> Delete period
            </a>
        </li>
    </ul>
</div>
"""


def periods_data(periods):

    data = [{'number': p.period,
             'name': '<span class="label label-default">None</span>' if p.name is None else p.name,
             'has_presentation': render_template_string(_presentation, flag=p.has_presentation),
             'menu': render_template_string(_menu, period=p)} for p in periods]

    return jsonify(data)
