#
# Created by David Seery on 05/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import render_template_string, jsonify


# language=jinja2
_manage_backups_menu = \
"""
<div class="dropdown">
    <button class="btn btn-secondary btn-sm full-width-button dropdown-toggle" type="button" data-bs-toggle="dropdown">
        Actions
    </button>
    <div class="dropdown-menu dropdown-menu-dark mx-0 border-0 dropdown-menu-end">
        <a class="dropdown-item d-flex gap-2" href="{{ url_for('admin.confirm_delete_backup', id=backup.id) }}">
            <i class="fas fa-trash fa-fw"></i> Delete
        </a>
    </div>
</div>
"""


def backups_data(backups):
    data = [{'date': {
                'display': b.date.strftime("%a %d %b %Y %H:%M:%S"),
                'timestamp': b.date.timestamp()
            },
            'initiated': '<a class="text-decoration-none" href="mailto:{e}">{name}</a>'.format(e=b.owner.email,
                                                                  name=b.owner.name) if b.owner is not None
            else '<span class="badge bg-secondary">Nobody</span>',
            'type': b.type_to_string(),
            'description': b.description if b.description is not None and len(b.description) > 0
            else '<span class="badge bg-secondary">None</span>',
            'filename': b.filename,
            'db_size': b.readable_db_size,
            'archive_size': b.readable_archive_size,
            'menu': render_template_string(_manage_backups_menu, backup=b)} for b in backups]

    return jsonify(data)
