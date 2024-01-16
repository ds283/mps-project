#
# Created by David Seery on 2019-04-26.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from datetime import datetime

from flask_login import current_user
from ..models import SelectingStudent

from app.models import SelectionRecord


def store_selection(sel: SelectingStudent, converted=False, no_submit_IP=False):
    # delete any existing selections
    sel.selections = []

    # iterate through bookmarks, converting them to a selection set
    for bookmark in sel.ordered_bookmarks.limit(sel.number_choices):
        rec = SelectionRecord(
            owner_id=sel.id,
            liveproject_id=bookmark.liveproject_id,
            rank=bookmark.rank,
            converted_from_bookmark=converted,
            hint=SelectionRecord.SELECTION_HINT_NEUTRAL,
        )
        sel.selections.append(rec)

    sel.submission_time = datetime.now()

    if not no_submit_IP:
        sel.submission_IP = current_user.current_login_ip
    else:
        sel.submission_IP = None
