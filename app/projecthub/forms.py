#
# Created by David Seery on 09/10/2020.
# Copyright (c) 2020 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#
from flask_security import Form
from flask_security.forms import Form
from wtforms import (
    BooleanField,
    DateTimeField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import InputRequired, Length, Optional
from wtforms_alchemy import QuerySelectField, QuerySelectMultipleField

from ..models import DEFAULT_STRING_LENGTH, SubmissionRecord, SubmissionRole
from ..shared.forms.mixins import SaveChangesMixin


class FormattedArticleForm(Form):
    title = StringField(
        "Article title",
        validators=[
            InputRequired("Please enter a title for your article or news story"),
            Length(max=DEFAULT_STRING_LENGTH),
        ],
    )

    article = TextAreaField("Article", validators=[Optional()], render_kw={"rows": 10})

    published = BooleanField(
        "Published",
        description="Select this option to make your article visible to other users",
    )

    publish_on = DateTimeField(
        "Automatically publish at a specified time",
        format="%d/%m/%Y %H:%M",
        description="If you wish your article to be published automatically at "
        "a specified time, enter it here. Leave blank to disable "
        "automated publication.",
        validators=[Optional()],
    )


class AddFormatterArticleForm(FormattedArticleForm):
    submit = SubmitField("Add new article")


class EditFormattedArticleForm(FormattedArticleForm, SaveChangesMixin):
    pass


class MeetingSummaryForm(Form):
    meeting_summary = TextAreaField(
        "Meeting summary",
        validators=[Optional()],
        render_kw={"rows": 15},
        description="A summary of the meeting that will be visible to the student and supervision team.",
    )

    submit = SubmitField("Save changes")


class SupervisionNotesForm(Form):
    supervision_notes = TextAreaField(
        "Supervision notes",
        validators=[Optional()],
        render_kw={"rows": 15},
        description="Private notes for the supervision team. These are not visible to the student.",
    )

    submit = SubmitField("Save changes")


def _build_supervisor_role_label(role: SubmissionRole) -> str:
    """Return a human-readable label for a SubmissionRole used in the team selector."""
    if role.user is not None:
        return f"{role.user.name} ({role.role_as_str})"
    return f"Unknown user ({role.role_as_str})"


def build_event_team_form(event):
    """
    Factory that returns an EventTeamForm class whose query_factory is bound to the
    SubmissionRole instances eligible to appear in the team for *event*.

    Eligible roles are those attached to the parent SubmissionRecord with
    ROLE_SUPERVISOR or ROLE_RESPONSIBLE_SUPERVISOR, excluding the event owner.
    """
    from ..models import SubmissionRecord

    owner_id = event.owner_id
    record: SubmissionRecord = event.sub_record

    def _query_factory():
        return [role for role in record.supervisor_roles if role.id != owner_id]

    class EventTeamForm(Form):
        team = QuerySelectMultipleField(
            "Attending supervisors",
            query_factory=_query_factory,
            get_label=_build_supervisor_role_label,
            validators=[Optional()],
            description="Select additional supervisors (other than the event owner) who attended this meeting.",
        )

        submit = SubmitField("Save changes")

    return EventTeamForm


def ReassignEventOwnerFormFactory(event):
    """
    Factory that returns a form for reassigning the owner of a SupervisionEvent.
    The new owner must be one of the current team members (i.e. a SubmissionRole
    that is already in the event's team collection).
    """
    from ..models import SubmissionRole, SupervisionEvent

    event_id = event.id

    def _query_factory():
        # Reload the event to get the current team
        ev: SupervisionEvent = SupervisionEvent.query.get(event_id)
        if ev is None:
            return []
        sub_record: SubmissionRecord = ev.sub_record
        return [r for r in sub_record.supervisor_roles if r.id != ev.owner_id]

    def _get_label(role: SubmissionRole) -> str:
        if role is not None and role.user is not None:
            return f"{role.user.name} ({role.role_as_str})"
        return "Unknown"

    class ReassignEventOwnerForm(Form):
        new_owner = QuerySelectField(
            "New event owner",
            query_factory=_query_factory,
            get_label=_get_label,
            allow_blank=False,
            description="Select the team member who should become the new owner of this event.",
        )

        submit = SubmitField("Reassign owner")

    return ReassignEventOwnerForm


class SetRegularMeetingTimesForm(Form, SaveChangesMixin):
    weekday = SelectField(
        "Day of the week",
        description="Specify the day of the week when you normally meet",
        choices=SubmissionRole.weekdays_choices,
        coerce=int,
    )

    start_time = DateTimeField(
        "Meeting start time",
        format="%H:%M",
        description="Select the start time for your regular meeting.",
    )

    location = StringField(
        "Meeting location",
        validators=[Optional(), Length(max=DEFAULT_STRING_LENGTH)],
    )


class SetSubmissionRoleNotificationPreferencesForm(Form, SaveChangesMixin):
    prompt_after_event = BooleanField(
        "Send email prompt to record attendance after each supervision event",
        default=False,
    )

    prompt_at_fixed_time = BooleanField(
        "Send email prompt at specified time",
        description="If set, an email will be sent on the day of the event at the time specified below. If not set, an email will be sent ",
    )

    prompt_at_time = DateTimeField(
        "Time to send email prompt",
        format="%H:%M",
    )

    prompt_delay = SelectField(
        "Delay before sending email prompt",
        choices=SubmissionRole._prompt_delay_choices,
        coerce=int,
    )

    prompt_in_reminder = BooleanField(
        "Include this student in reminder emails",
        description="Select to include this student in periodic reminder email (if attendance data is still to be recorded)",
        default=True,
    )
