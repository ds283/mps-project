#
# Created by David Seery on 03/09/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template_string


# language=jinja2
_name = \
"""
<a href="mailto:{{ s.user.email }}">{{ s.user.name }}</a>
{% if s.intermitting %}
    <span class="badge badge-warning">TWD</span>
{% endif %}
{{ s.academic_year_label()|safe }}
{{ s.cohort_label|safe }}
"""


# language=jinja2
_selecting = \
"""
{% for sel in s.ordered_selecting %}
    {% if not sel.retired %}
        {{ sel.config.project_class.make_label()|safe }}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_submitting = \
"""
{% for sub in s.ordered_submitting %}
    {% if not sub.retired %}
        {{ sub.config.project_class.make_label()|safe }}
    {% endif %}
{% endfor %}
"""

def year_groups(students):
    data = [{'name': render_template_string(_name, s=s),
             'programme': s.programme.label,
             'selecting': render_template_string(_selecting, s=s),
             'submitting': render_template_string(_submitting, s=s)}
            for s in students]

    return data
