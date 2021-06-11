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
{% if a.published and a.publication_timestamp %}
    {{ a.publication_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    by <i class="fas fa-user"></i> <a href="mailto:{{ a.created_by.email }}">{{ a.created_by.name }}</a>
{% else %}
    <span class="badge bg-warning text-dark">Not published</span>
{% endif %}
"""


_last_edit = \
"""
{% if a.last_edit_timestamp %}
    {{ a.last_edit_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    by <i class="fas fa-user"></i> <a href="mailto:{{ a.last_edited_by.email }}">{{ a.last_edited_by.name }}</a>
{% elif a.creation_timestamp %}
    {{ a.creation_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
    by <i class="fas fa-user"></i> <a href="mailto:{{ a.created_by.email }}">{{ a.created_by.name }}</a>
{% else %}
    <span class="badge bg-danger">None</span>
{% endif %}
"""


_title = \
"""
<a href="{{ url_for('projecthub.show_formatted_article', aid=a.id, url=url, text=text) }}">{{ a.title }}</a>
"""


_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm btn-block dropdown-toggle" type="button"
            data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-end">
        <a class="dropdown-item" href="{{ url_for('projecthub.show_formatted_article', aid=a.id, url=url, text=text) }}"><i class="fas fa-search fa-fw"></i> Show article...</a> 
        <a class="dropdown-item" href="{{ url_for(edit_endpoint, aid=a.id) }}"><i class="fas fa-pencil-alt fa-fw"></i> Edit...</a>
        <a class="dropdown-item" href="#"><i class="fas fa-trash fa-fw"></i> Delete</a>
    </div>
</div>
"""

def article_list_data(url: str, text: str, edit_endpoint: str, articles: List[FormattedArticle]):
    data = [{'title': render_template_string(_title, a=a, url=url, text=text),
             'published': render_template_string(_published, a=a),
             'last_edit': render_template_string(_last_edit, a=a),
             'status': '',
             'menu': render_template_string(_menu, a=a, edit_endpoint=edit_endpoint, url=url, text=text)} for a in articles]

    return data
