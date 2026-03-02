#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
import base64

from app.models import BackupRecord, GeneratedAsset, SubmittedAsset


def validate_nonce(nonce: bytes):
    base64_nonce = base64.urlsafe_b64encode(nonce).decode("ascii")

    if db.session.query(BackupRecord).filter_by(nonce=base64_nonce).first() is not None:
        return False

    if db.session.query(GeneratedAsset).filter_by(nonce=base64_nonce).first() is not None:
        return False

    if db.session.query(SubmittedAsset).filter_by(nonce=base64_nonce).first() is not None:
        return False

    return True
