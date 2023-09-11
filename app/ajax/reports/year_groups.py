#
# Created by David Seery on 03/09/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from flask import render_template_string, get_template_attribute

# language=jinja2
_name = \
"""
<a class="text-decoration-none" href="mailto:{{ s.user.email }}">{{ s.user.name }}</a>
{% if s.intermitting %}
    <span class="badge bg-warning text-dark">TWD</span>
{% endif %}
{{ simple_label(s.academic_year_label()) }}
{{ simple_label(s.cohort_label) }}
"""


# language=jinja2
_selecting = \
"""
{% for sel in s.ordered_selecting %}
    {% if not sel.retired %}
        {{ simple_label(sel.config.project_class.make_label()) }}
    {% endif %}
{% endfor %}
"""


# language=jinja2
_submitting = \
"""
{% for sub in s.ordered_submitting %}
    {% if not sub.retired %}
        {{ simple_label(sub.config.project_class.make_label()) }}
    {% endif %}
{% endfor %}
"""

# language=jinja2
_programme = \
"""
{{ simple_label(s.programme.label) }}
"""

def year_groups(students):
    simple_label = get_template_attribute("labels.html", "simple_label")

    data = [{'name': render_template_string(_name, s=s, simple_label=simple_label),
             'programme': render_template_string(_programme, s=s, simple_label=simple_label),
             'selecting': render_template_string(_selecting, s=s, simple_label=simple_label),
             'submitting': render_template_string(_submitting, s=s, simple_label=simple_label)}
            for s in students]

    return data
