#
# Created by David Seery on 07/09/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask_security.forms import Form
from wtforms import SubmitField, DateField
from wtforms.validators import InputRequired
from wtforms_alchemy import QuerySelectField

from ..shared.forms.queries import MarkerQuery, BuildMarkerLabel, GetPresentationFeedbackFaculty, BuildActiveFacultyName
from ..shared.forms.mixins import FeedbackMixin
from functools import partial


class GoLiveForm(Form):

    # normal Go Live option
    live = SubmitField('Go live')

    # go live and close option
    live_and_close = SubmitField('Go live and immediately close')

    # deadline field
    live_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[InputRequired()])


class IssueFacultyConfirmRequestForm(Form):

    # deadline for confirmation responses
    request_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[InputRequired()])

    # submit button: issue requests
    issue_requests = SubmitField('Issue confirmation requests')


class OpenFeedbackForm(Form):

    # deadline for feedback
    feedback_deadline = DateField('Deadline', format='%d/%m/%Y', validators=[InputRequired()])

    # submit button: open feedback
    open_feedback = SubmitField('Open feedback period')


def AssignMarkerFormFactory(live_project, pclass_id):

    class AssignMarkerForm(Form):

        # 2nd marker
        marker = QuerySelectField('Assign 2nd marker', query_factory=partial(MarkerQuery, live_project),
                                  get_label=partial(BuildMarkerLabel, pclass_id))

    return AssignMarkerForm


def AssignPresentationFeedbackFormFactory(record_id):

    class AssignPresentationFeedbackForm(Form, FeedbackMixin):

        assessor = QuerySelectField('Assign feedback to assessor',
                                    query_factory=partial(GetPresentationFeedbackFaculty, record_id),
                                    get_label=BuildActiveFacultyName)

    return AssignPresentationFeedbackForm
