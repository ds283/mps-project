#
# Created by David Seery on 07/08/2023$.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from pathlib import Path
from uuid import uuid4

from flask import current_app


class ScratchFileManager:

    def __init__(self):
        folder = Path(current_app.config.get('SCRATCH_FOLDER'))
        name = str(uuid4())
        self._path = folder / name


    def __enter__(self):
        return self


    def __exit__(self, type, value, traceback):
        self._path.unlink(missing_ok=True)


    @property
    def path(self):
        return self._path
