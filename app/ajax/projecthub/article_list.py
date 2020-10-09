#
# Created by David Seery on 09/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from flask import render_template_string

from ...models import FormattedArticle


_published = \
"""
{% if a.publication_timestamp %}
    {{ a.publication_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    by <i class="fas fa-user"></i> <a href="mailto:{{ a.created_by.email }}">{{ a.created_by.name }}"</a>
{% else %}
    <span class="badge badge-warning">Not published</span>
{% endif %}
"""


_last_edit = \
"""
{% if a.last_edit_timestamp %}
    {{ a.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    by <i class="fas fa-user"></i> <a href="mailto:{{ a.last_edited_by.email }}">{{ a.last_edited_by.name }}"</a>
{% elif a.creation_timestamp %}
    {{ a.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    by <i class="fas fa-user"></i> <a href="mailto:{{ a.created_by.email }}">{{ a.created_by.name }}"</a>
{% else %}
    <span class="badge badge-danger">None</span>
{% endif %}
"""


def article_list_data(articles: List[FormattedArticle]):
    data = [{'title': a.title,
             'published': render_template_string(_published, a=a),
             'last_edit': render_template_string(_last_edit, a=a),
             'status': "",
             'menu': ""} for a in articles]

    return data
