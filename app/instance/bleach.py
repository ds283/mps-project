#
# Created by David Seery on 25/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# Bleach configuration
BLEACH_ALLOWED_TAGS = [
    'a',
    'abbr',
    'acronym',
    'b',
    'br',
    'blockquote',
    'code',
    'dd',
    'dt',
    'em',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'i',
    'img',
    'li',
    'ol',
    'p',
    'strong',
    'tt',
    'ul',
    'div',
    'span'
]

BLEACH_ALLOWED_ATTRIBUTES = {
    '*': ['style'],
    'a': ['href', 'alt', 'title'],
    'abbr': ['title'],
    'acronym': ['title'],
    'div': ['class'],
    'img': ['src', 'alt', 'title'],
}

BLEACH_ALLOWED_STYLES = [
    'color',
    'font-weight'
]
