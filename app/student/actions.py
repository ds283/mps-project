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

from app.models import SelectionRecord
from ..models import SelectingStudent


def store_selection(sel: SelectingStudent, converted: bool = False, no_submit_IP: bool = False, reset: bool = True):
    # delete any existing selections if reset flag is set;
    # otherwise we try to merge the current submission list with the current bookmark list
    existing = set()
    rank = 1

    if reset:
        sel.selections = []
    else:
        for item in sel.selections:
            if item.rank >= rank:
                rank = item.rank + 1
            existing.add(item.liveproject_id)

    stored = []

    # iterate through bookmarks, appending them to a selection set, until we have sufficient selections or we have run out
    num_selections = len(existing)
    for bookmark in sel.ordered_bookmarks:
        if bookmark.liveproject_id not in existing and bookmark.liveproject.is_available(sel):
            rec = SelectionRecord(
                owner_id=sel.id,
                liveproject_id=bookmark.liveproject_id,
                rank=rank,
                converted_from_bookmark=converted,
                hint=SelectionRecord.SELECTION_HINT_NEUTRAL,
            )
            sel.selections.append(rec)
            existing.add(bookmark.liveproject_id)
            stored.append(bookmark.liveproject)

            num_selections += 1
            rank += 1

            if num_selections >= sel.number_choices:
                break

    sel.submission_time = datetime.now()

    if not no_submit_IP:
        sel.submission_IP = current_user.current_login_ip
    else:
        sel.submission_IP = None

    return stored
