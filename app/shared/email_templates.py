#
# Created by David Seery on 28/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime

from sqlalchemy import func

from ..database import db
from ..models.emails import EmailTemplate


def clone_email_template(
    template: EmailTemplate, pclass_id, tenant_id, creator
) -> EmailTemplate:
    """
    Clone *template* at the given (pclass_id, tenant_id) scope.

    Returns a new, unsaved EmailTemplate with active=False and the next version number.
    Labels are copied from the source template.
    The caller must call db.session.add() and commit (e.g. via log_db_commit).
    """
    max_version = (
        db.session.query(func.max(EmailTemplate.version))
        .filter(
            EmailTemplate.type == template.type,
            EmailTemplate.tenant_id == tenant_id,
            EmailTemplate.pclass_id == pclass_id,
        )
        .scalar()
    )
    new_version = (max_version or 0) + 1
    now = datetime.now()

    new_template = EmailTemplate(
        active=False,
        tenant_id=tenant_id,
        pclass_id=pclass_id,
        type=template.type,
        subject=template.subject,
        html_body=template.html_body,
        comment=f"Duplicated from version {template.version}",
        version=new_version,
        last_used=None,
        creator_id=creator.id,
        creation_timestamp=now,
        last_edit_timestamp=None,
        last_edit_id=None,
    )
    new_template.labels = list(template.labels)
    return new_template
