#
# Created by David Seery on 02/03/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from .defaults import DEFAULT_STRING_LENGTH
from ..database import db

class Tenant(db.Model):
    """
    Model an individual tenant
    """

    __tablename__ = "tenants"

    # primary key
    id = db.Column(db.Integer, primary_key=True)

    # name
    name = db.Column(db.String(DEFAULT_STRING_LENGTH))
