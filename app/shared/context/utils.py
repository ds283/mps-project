#
# Created by David Seery on 19/01/2024$.
# Copyright (c) 2024 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from typing import List

from ...database import db
from ...models import ProjectClass, ProjectClassConfig


def get_pclass_list() -> List[ProjectClass]:
    return (
        db.session.query(ProjectClass)
        .filter(
            ProjectClass.active == True,
            ProjectClass.publish == True,
        )
        .order_by(ProjectClass.name.asc())
        .all()
    )


def get_pclass_config_list(pcs: List[ProjectClass]=None) -> List[ProjectClassConfig]:
    if pcs is None:
        pcs: List[ProjectClass] = get_pclass_list()

    cs: List[ProjectClassConfig] = [pclass.most_recent_config for pclass in pcs]

    # strip out 'None' entries before returning
    return [x for x in cs if x is not None]
