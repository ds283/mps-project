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

from ....models import FormattedArticle


_title = \
"""
<a href="{{ url_for('projecthub.show_formatted_article', aid=a.id, url=url, text=text) }}">{{ a.title }}</a>
"""


_author = \
"""
<i class="fas fa-user"></i> <a href="mailto:{{ a.created_by.email }}">{{ a.created_by.name }}</a>
"""


_published = \
"""
{% if a.publication_timestamp %}
    {{ a.publication_timestamp.strftime("%a %d %b %Y %H:%M:%S") }}
{% else %}
    <span class="badge bg-warning text-dark">None</span>
{% endif %}
"""


def articles(url: str, text: str, articles: List[FormattedArticle]):
    data = [{'title': render_template_string(_title, a=a, url=url, text=text),
             'published': render_template_string(_published, a=a),
             'author': render_template_string(_author, a=a)} for a in articles]

    return data
