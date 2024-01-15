#
# Created by David Seery on 12/01/2024.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from datetime import datetime
from urllib.parse import SplitResult

from pandas import DataFrame


class AuditBackend:

    def __init__(self, uri: SplitResult):
        pass

    def store_audit_record(self, type: str, audit_data: str, driver: str = None, bucket: str = None,
                           host_uri: str = None) -> None:
        raise NotImplementedError(
            'The store_audit_record() method should be implemented by concrete AuditBackend instances')

    def get_audit_records(self, latest: datetime=None) -> DataFrame:
        raise NotImplementedError(
            'The get_audit_records() method should be implemented by concrete AuditBackend instances')

    def delete_audit_records(self, latest: datetime=None) -> None:
        raise NotImplementedError(
            'The delete_audit_records() method should be implemented by concrete AuditBackend instances')
