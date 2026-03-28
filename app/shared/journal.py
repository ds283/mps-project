#
# Created by David Seery on 27/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from ..database import db
from ..models import MainConfig, StudentJournalEntry


def create_auto_journal_entry(student, html_content, title=None, project_class_config=None):
    """
    Create an automatically-generated journal entry for a student with no owner.

    :param student: StudentData instance
    :param html_content: HTML string for the entry body
    :param title: optional short title string for the entry
    :param project_class_config: optional single ProjectClassConfig to link the entry to
    """
    config = db.session.query(MainConfig).order_by(MainConfig.year.desc()).first()
    config_year = config.year if config is not None else None

    entry = StudentJournalEntry(
        student_id=student.id,
        config_year=config_year,
        created_timestamp=datetime.now(),
        owner_id=None,
        title=title,
        entry=html_content,
    )
    db.session.add(entry)
    db.session.flush()

    if project_class_config is not None:
        entry.project_classes.append(project_class_config)
