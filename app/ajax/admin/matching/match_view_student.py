#
# Created by David Seery on 22/08/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from typing import List

from ....database import db
from ....models import EmailLog, SelectingStudent, StudentData, User


def get_match_student_emails(s: SelectingStudent, show_max: int = 7) -> List[EmailLog]:
    data: StudentData = s.student

    emails: List[EmailLog] = (
        db.session.query(EmailLog).filter(EmailLog.recipients.any(User.id == data.id)).order_by(EmailLog.send_date.desc()).limit(show_max).all()
    )

    return emails
