#
# Created by David Seery on 12/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from urllib.parse import SplitResult

class AuditBackend:

    def __init__(self, uri: SplitResult):
        pass

    def store_audit_record(self, type: str, audit_data: str, driver: str=None, bucket: str=None, host_uri: str=None):
        raise NotImplementedError('The store_audit_record() method should be implemented by concrete AuditBackend instances')
