#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from ..shared.quickfixes import QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_AVAILABLE
from .assessment import _PresentationAssessment_is_valid
from .associations import (
    live_project_programmes,
    live_project_skills,
    live_project_supervision,
    live_project_tags,
    live_project_to_modules,
    live_supervisors,
    sel_group_filter_table,
    sel_skill_filter_table,
)
from .defaults import IP_LENGTH
from .matching import (
    MatchingRecord,
    _delete_MatchingRecord_cache,
    _MatchingRecord_is_valid,
)
from .model_mixins import (
    ConfirmRequestStatesMixin,
)
from .project_class import *
from .project_class import _get_submission_period
from .projects import *
from .students import StudentData
from .submissions import Bookmark, CustomOffer, SelectionRecord, SubmissionRecord

# Import wildcard symbols needed from already-extracted modules
from .utilities import *


class LiveProject(
    db.Model,
    ProjectConfigurationMixinFactory(
        backref_label="live_projects",
        force_unique_names="arbitrary",
        skills_mapping_table=live_project_skills,
        skills_mapped_column=live_project_skills.c.skill_id,
        skills_self_column=live_project_skills.c.project_id,
        allow_edit_skills="disallow",
        programmes_mapping_table=live_project_programmes,
        programmes_mapped_column=live_project_programmes.c.programme_id,
        programmes_self_column=live_project_programmes.c.project_id,
        allow_edit_programmes="disallow",
        tags_mapping_table=live_project_tags,
        tags_mapped_column=live_project_tags.c.tag_id,
        tags_self_column=live_project_tags.c.project_id,
        allow_edit_tags="disallow",
        assessor_mapping_table=live_assessors,
        assessor_mapped_column=live_assessors.c.faculty_id,
        assessor_self_column=live_assessors.c.project_id,
        assessor_backref_label="assessor_for_live",
        allow_edit_assessors="disallow",
        supervisor_mapping_table=live_supervisors,
        supervisor_mapped_column=live_supervisors.c.faculty_id,
        supervisor_self_column=live_supervisors.c.project_id,
        supervisor_backref_label="supervisor_for_live",
        allow_edit_supervisors="allow",
    ),
    ProjectDescriptionMixinFactory(
        team_mapping_table=live_project_supervision,
        team_backref="live_projects",
        module_mapping_table=live_project_to_modules,
        module_backref="tagged_live_projects",
        module_mapped_column=live_project_to_modules.c.module_id,
        module_self_column=live_project_to_modules.c.project_id,
    ),
):
    """
    The definitive live project table
    """

    __tablename__ = "live_projects"

    # surrogate key for (config_id, number) -- need to ensure these are unique!
    id = db.Column(db.Integer(), primary_key=True)

    # key to ProjectClassConfig record that identifies the year and pclass
    config_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))
    config = db.relationship(
        "ProjectClassConfig",
        uselist=False,
        backref=db.backref("live_projects", lazy="dynamic"),
    )

    @property
    def forced_group_tags(self):
        tags = set()
        for group in self.config.project_class.force_tag_groups:
            assigned_tags = self.tags.filter_by(group_id=group.id).all()
            for tag in assigned_tags:
                tags.add(tag)

        return tags

    # key linking to parent project
    parent_id = db.Column(db.Integer(), db.ForeignKey("projects.id"))
    parent = db.relationship(
        "Project", uselist=False, backref=db.backref("live_projects", lazy="dynamic")
    )

    # definitive project number in this year
    number = db.Column(db.Integer())

    # AVAILABILITY

    # hidden?
    hidden = db.Column(db.Boolean(), default=False)

    # METADATA

    # count number of page views
    page_views = db.Column(db.Integer())

    # date of last view
    last_view = db.Column(db.DateTime())

    def is_available(self, sel):
        """
        determine whether this LiveProject is available for selection to a particular SelectingStudent
        :param sel:
        :return:
        """
        sel: SelectingStudent

        # if project is marked as hidden, it is not available
        if self.hidden:
            return False

        # generic projects are always available
        if self.generic:
            return True

        # if student doesn't satisfy recommended modules, sign-off is required by default (whether or not
        # the project/owner settings require sign-off)
        if not sel.satisfies_recommended(self) and not self.is_confirmed(sel):
            return False

        # if project doesn't require sign off, it is always available
        # if project owner doesn't require confirmation, it is always available
        if self.meeting_reqd != self.MEETING_REQUIRED or (
            self.owner is not None and self.owner.sign_off_students is False
        ):
            return True

        # otherwise, check if sel is in list of confirmed students
        if self.is_confirmed(sel):
            return True

        return False

    @property
    def _is_waiting_query(self):
        return self.confirmation_requests.filter_by(
            state=ConfirmRequestStatesMixin.REQUESTED
        )

    @property
    def _is_confirmed_query(self):
        return self.confirmation_requests.filter_by(
            state=ConfirmRequestStatesMixin.CONFIRMED
        )

    def is_waiting(self, sel):
        return get_count(self._is_waiting_query.filter_by(owner_id=sel.id)) > 0

    def is_confirmed(self, sel):
        return get_count(self._is_confirmed_query.filter_by(owner_id=sel.id)) > 0

    def get_confirm_request(self, sel):
        return self.confirmation_requests.filter_by(owner_id=sel.id).first()

    def make_confirm_request(
        self, sel, state="requested", resolved_by=None, comment=None
    ):
        if state not in ConfirmRequestStatesMixin._values:
            state = "requested"

        now = datetime.now()
        req: ConfirmRequest = ConfirmRequest(
            owner_id=sel.id,
            project_id=self.id,
            state=ConfirmRequestStatesMixin._values[state],
            viewed=False,
            request_timestamp=now,
            response_timestamp=None,
            resolved_id=resolved_by.id if resolved_by is not None else None,
            comment=comment,
        )
        if state == "confirmed":
            req.response_timestamp = now

        return req

    @property
    def ordered_custom_offers(self):
        return (
            self.custom_offers.join(
                SelectingStudent, SelectingStudent.id == CustomOffer.selector_id
            )
            .join(StudentData, StudentData.id == SelectingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .order_by(
                User.last_name.asc(),
                User.first_name.asc(),
                CustomOffer.creation_timestamp.asc(),
            )
        )

    def _get_popularity_attr(
        self,
        getter,
        live=True,
        live_interval: timedelta = timedelta(days=1),
        compare_interval: Optional[timedelta] = None,
    ):
        # compare_interval and live are incompatible
        if compare_interval is not None:
            live = False
            print(
                "Warning: LiveProject._get_popularity_attr() called with both live=True and compare_interval not None. live=True has been discarded"
            )

        if compare_interval is not None and not isinstance(compare_interval, timedelta):
            raise RuntimeError(
                f'Could not interpret type of compare_interval argument (type="{type(compare_interval)}"'
            )

        now = datetime.now()

        if compare_interval is None:
            record = self.popularity_data.order_by(
                PopularityRecord.datestamp.desc()
            ).first()
        else:
            record = (
                self.popularity_data.filter(
                    PopularityRecord.datestamp <= now - compare_interval
                )
                .order_by(PopularityRecord.datestamp.desc())
                .first()
            )

        # return None if no value stored, or if stored value is too stale (> 1 day old)
        if record is None or (live and (now - record.datestamp) > live_interval):
            return None

        return getter(record)

    def _get_popularity_history(self, getter):
        records = self.popularity_data.order_by(PopularityRecord.datestamp.asc()).all()

        date_getter = lambda x: x.datestamp
        xs = [date_getter(r) for r in records]
        ys = [getter(r) for r in records]

        return xs, ys

    def popularity_score(
        self,
        live=True,
        live_interval: timedelta = timedelta(days=1),
        compare_interval: Optional[timedelta] = None,
    ):
        """
        Return popularity score
        :param live: require a "live" estimate, ie. one that is sufficiently recent?
        :return:
        """
        return self._get_popularity_attr(
            lambda x: x.score,
            live=live,
            live_interval=live_interval,
            compare_interval=compare_interval,
        )

    def popularity_rank(
        self,
        live=True,
        live_interval: timedelta = timedelta(days=1),
        compare_interval: Optional[timedelta] = None,
    ):
        """
        Return popularity rank
        :param live: require a "live" estimate, ie. one that is sufficiently recent?
        :return:
        """
        return self._get_popularity_attr(
            lambda x: (x.score_rank, x.total_number),
            live=live,
            live_interval=live_interval,
            compare_interval=compare_interval,
        )

    @property
    def popularity_score_history(self):
        """
        Return time history of the popularity score
        :return:
        """
        return self._get_popularity_history(lambda x: x.score)

    @property
    def popularity_rank_history(self):
        """
        Return time history of the popularity rank
        :return:
        """
        return self._get_popularity_history(lambda x: (x.score_rank, x.total_number))

    def lowest_popularity_rank(
        self,
        live=True,
        live_interval: timedelta = timedelta(days=1),
        compare_interval: Optional[timedelta] = None,
    ):
        """
        Return least popularity rank
        :param live: require a "live" estimate, ie. one that is sufficiently recent?
        :return:
        """
        return self._get_popularity_attr(
            lambda x: x.lowest_score_rank,
            live=live,
            live_interval=live_interval,
            compare_interval=compare_interval,
        )

    def views_rank(
        self,
        live=True,
        live_interval: timedelta = timedelta(days=1),
        compare_interval: Optional[timedelta] = None,
    ):
        """
        Return views rank (there is no need for a views score -- the number of views is directly available)
        :param live: require a "live" estimate, ie. one that is sufficiently recent?
        :return:
        """
        return self._get_popularity_attr(
            lambda x: (x.views_rank, x.total_number),
            live=live,
            live_interval=live_interval,
            compare_interval=compare_interval,
        )

    @property
    def views_history(self):
        """
        Return time history of number of views
        :return:
        """
        return self._get_popularity_history(lambda x: x.views)

    @property
    def views_rank_history(self):
        """
        Return time history of views rank
        :return:
        """
        return self._get_popularity_history(lambda x: (x.views_rank, x.total_number))

    def bookmarks_rank(
        self,
        live=True,
        live_interval: timedelta = timedelta(days=1),
        compare_interval: Optional[timedelta] = None,
    ):
        """
        Return bookmark rank (number of bookmarks can be read directly)
        :param live: require a "live" estimate, ie. one that is sufficiently recent?
        :return:
        """
        return self._get_popularity_attr(
            lambda x: (x.bookmarks_rank, x.total_number),
            live=live,
            live_interval=live_interval,
            compare_interval=compare_interval,
        )

    @property
    def bookmarks_history(self):
        """
        Return time history of number of bookmarks
        :return:
        """
        return self._get_popularity_history(lambda x: x.bookmarks)

    @property
    def bookmarks_rank_history(self):
        """
        Return time history of bookmarks rank
        :return:
        """
        return self._get_popularity_history(
            lambda x: (x.bookmarks_rank, x.total_number)
        )

    def selections_rank(
        self,
        live=True,
        live_interval: timedelta = timedelta(days=1),
        compare_interval: Optional[timedelta] = None,
    ):
        """
        Return selection rank
        :param live: require a "live" estimate, ie. one that is sufficiently recent?
        :return:
        """
        return self._get_popularity_attr(
            lambda x: (x.selections_rank, x.total_number),
            live=live,
            live_interval=live_interval,
            compare_interval=compare_interval,
        )

    @property
    def selections_history(self):
        """
        Return time history of number of selections
        :return:
        """
        return self._get_popularity_history(lambda x: x.selections)

    @property
    def selections_rank_history(self):
        """
        Return time history of selections rank
        :return:
        """
        return self._get_popularity_history(
            lambda x: (x.selections_rank, x.total_number)
        )

    @property
    def show_popularity_data(self):
        return (
            self.parent.show_popularity
            or self.parent.show_bookmarks
            or self.parent.show_selections
        )

    @property
    def ordered_bookmarks(self):
        return self.bookmarks.order_by(Bookmark.rank)

    @property
    def ordered_selections(self):
        return self.selections.order_by(SelectionRecord.rank)

    @property
    def number_bookmarks(self):
        return get_count(self.bookmarks)

    @property
    def number_custom_offers(self, period: SubmissionPeriodDefinitionLike = None):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)
        return get_count(query)

    @property
    def number_selections(self):
        return get_count(self.selections)

    @property
    def number_pending(self):
        return get_count(self._is_waiting_query)

    @property
    def number_confirmed(self):
        return get_count(self._is_confirmed_query)

    @property
    def requests_waiting(self):
        return self._is_waiting_query.all()

    @property
    def requests_confirmed(self):
        return self._is_confirmed_query.all()

    def _custom_offers_pending_query(
        self, period: SubmissionPeriodDefinitionLike = None
    ):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers.filter(CustomOffer.status == CustomOffer.OFFERED)
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)

        query = (
            query.join(SelectingStudent, SelectingStudent.id == CustomOffer.selector_id)
            .join(StudentData, StudentData.id == SelectingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .order_by(User.last_name.asc(), User.first_name.asc())
        )
        return query

    def custom_offers_pending(self, period: SubmissionPeriodDefinitionLike = None):
        return self._custom_offers_pending_query(period).all()

    def number_offers_pending(self, period: SubmissionPeriodDefinitionLike = None):
        return get_count(self._custom_offers_pending_query(period))

    def _custom_offers_declined_query(
        self, period: SubmissionPeriodDefinitionLike = None
    ):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers.filter(CustomOffer.status == CustomOffer.DECLINED)
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)

        query = (
            query.join(SelectingStudent, SelectingStudent.id == CustomOffer.selector_id)
            .join(StudentData, StudentData.id == SelectingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .order_by(User.last_name.asc(), User.first_name.asc())
        )
        return query

    def custom_offers_declined(self, period: SubmissionPeriodDefinitionLike = None):
        return self._custom_offers_declined_query(period).all()

    def number_offers_declined(self, period: SubmissionPeriodDefinitionLike = None):
        return get_count(self._custom_offers_declined_query(period))

    def _custom_offers_accepted_query(
        self, period: SubmissionPeriodDefinitionLike = None
    ):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers.filter(CustomOffer.status == CustomOffer.ACCEPTED)
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)

        query = (
            query.join(SelectingStudent, SelectingStudent.id == CustomOffer.selector_id)
            .join(StudentData, StudentData.id == SelectingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .order_by(User.last_name.asc(), User.first_name.asc())
        )
        return query

    def custom_offers_accepted(self, period: SubmissionPeriodDefinitionLike = None):
        return self._custom_offers_accepted_query(period).all()

    def number_offers_accepted(self, period: SubmissionPeriodDefinitionLike = None):
        return get_count(self._custom_offers_accepted_query(period))

    def format_popularity_label(self, popover=False):
        if not self.parent.show_popularity:
            return None

        return self.popularity_label(popover=popover)

    def popularity_label(self, popover=False):
        score = self.popularity_rank(live=True)
        if score is None:
            return {"label": "Unavailable", "type": "secondary"}

        rank, total = score
        lowest_rank = self.lowest_popularity_rank(live=True)

        # don't report popularity data if there isn't enough differentiation between projects for it to be
        # meaningful. Remember the lowest rank is actually numerically the highest number.
        # We report scores only if there is enough differentiation to push this rank above the 50th percentile
        if rank is not None:
            frac = float(rank) / float(total)
        else:
            frac = 1.0

        if lowest_rank is not None:
            lowest_frac = float(lowest_rank) / float(total)
        else:
            lowest_frac = 1.0

        if lowest_frac < 0.5:
            return {"label": "Updating...", "type": "secondary"}

        label = "Low"
        if frac < 0.1:
            label = "Very high"
        elif frac < 0.3:
            label = "High"
        elif frac < 0.5:
            label = "Medium"

        return {"label": f"Popularity: {label}", "type": "info"}

    def format_bookmarks_label(self, popover=False):
        if not self.parent.show_bookmarks:
            return None

        return self.bookmarks_label(popover=popover)

    def bookmarks_label(self, popover=False):
        num = self.number_bookmarks

        pl = "s" if num != 1 else ""

        data = {"label": f"{num} bookmark{pl}", "type": "info"}
        if popover and num > 0:
            project_tags = [
                "{name}".format(name=rec.owner.student.user.name)
                for rec in self.bookmarks.order_by(Bookmark.rank).limit(10).all()
            ]
            data["popover"] = project_tags

        return data

    def views_label(self):
        pl = "s" if self.page_views != 1 else ""

        return {"label": f"{self.page_views} view{pl}", "type": "info"}

    def format_selections_label(self, popover=False):
        if not self.parent.show_selections:
            return None

        return self.selections_label(popover=popover)

    def selections_label(self, popover=False):
        num = self.number_selections

        pl = "s" if num != 1 else ""

        data = {"label": f"{num} selection{pl}", "type": "info"}

        if popover and num > 0:
            project_tags = [
                "{name} (rank #{rank})".format(
                    name=rec.owner.student.user.name, rank=rec.rank
                )
                for rec in self.selections.order_by(SelectionRecord.rank)
                .limit(10)
                .all()
            ]
            data["popover"] = project_tags

        return data

    def satisfies_preferences(self, sel):
        preferences = get_count(self.programmes)
        matches = get_count(self.programmes.filter_by(id=sel.student.programme_id))

        if preferences == 0:
            return None

        if matches > 1:
            raise RuntimeError(
                "Inconsistent number of degree preferences match a single SelectingStudent"
            )

        if matches == 1:
            return True

        return False

    @property
    def assessor_list_query(self):
        return super()._assessor_list_query(self.config.pclass_id)

    @property
    def assessor_list(self):
        return self.assessor_list_query.all()

    @property
    def number_assessors(self):
        return get_count(self.assessors)

    def is_assessor(self, fac_id):
        return get_count(self.assessors.filter_by(id=fac_id)) > 0

    @property
    def supervisor_list_query(self):
        return super()._supervisor_list_query(self.config.pclass_id)

    @property
    def supervisor_list(self):
        return self.supervisor_list_query.all()

    @property
    def number_supervisors(self):
        return get_count(self.supervisors)

    def is_supervisor(self, fac_id):
        return get_count(self.supervisors.filter_by(id=fac_id)) > 0

    @property
    def is_deletable(self):
        if get_count(self.submission_records) > 0:
            return False

        return True

    @property
    def CATS_supervision(self):
        config: ProjectClassConfig = self.config

        if config.uses_supervisor:
            if config.CATS_supervision is not None and config.CATS_supervision > 0:
                return config.CATS_supervision

        return None

    @property
    def CATS_marking(self):
        config: ProjectClassConfig = self.config

        if config.uses_marker:
            if config.CATS_marking is not None and config.CATS_marking > 0:
                return config.CATS_marking

        return None

    @property
    def CATS_moderation(self):
        config: ProjectClassConfig = self.config

        if config.uses_moderator:
            if config.CATS_moderation is not None and config.CATS_moderation > 0:
                return config.CATS_moderation

        return None

    @property
    def CATS_presentation(self):
        config: ProjectClassConfig = self.config

        if config.uses_presentations:
            if config.CATS_presentation is not None and config.CATS_presentation > 0:
                return config.CATS_presentation

        return None

    @property
    def has_alternatives(self) -> bool:
        if self.number_alternatives > 0:
            return True

        return False

    @property
    def number_alternatives(self) -> int:
        return get_count(self.alternatives)

    def maintenance(self):
        """
        Perform regular basic maintenance, to ensure validity of the database
        :return:
        """
        modified = False

        modified = super()._maintenance_assessor_remove_duplicates() or modified
        modified = super()._maintenance_supervisor_remove_duplicates() or modified

        return modified


@listens_for(LiveProject.assessors, "append")
def _LiveProject_assessors_append_handler(target, value, initiator):
    with db.session.no_autoflush:
        from .scheduling import (
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )
        from .utilities import _MatchingAttempt_is_valid

        match_records = db.session.query(MatchingRecord).filter_by(project_id=target.id)
        for record in match_records:
            cache.delete_memoized(_MatchingRecord_is_valid, record.id)
            cache.delete_memoized(_MatchingAttempt_is_valid, record.matching_id)

        schedule_slots = db.session.query(ScheduleSlot).filter(
            ScheduleSlot.talks.any(project_id=target.id)
        )
        for slot in schedule_slots:
            cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)
            cache.delete_memoized(_ScheduleAttempt_is_valid, slot.owner_id)
            if slot.owner is not None:
                cache.delete_memoized(
                    _PresentationAssessment_is_valid, slot.owner.owner_id
                )


@listens_for(LiveProject.assessors, "remove")
def _LiveProject_assessors_remove_handler(target, value, initiator):
    with db.session.no_autoflush:
        from .scheduling import (
            ScheduleSlot,
            _ScheduleAttempt_is_valid,
            _ScheduleSlot_is_valid,
        )
        from .utilities import _MatchingAttempt_is_valid

        match_records = db.session.query(MatchingRecord).filter_by(project_id=target.id)
        for record in match_records:
            cache.delete_memoized(_MatchingRecord_is_valid, record.id)
            cache.delete_memoized(_MatchingAttempt_is_valid, record.matching_id)

        schedule_slots = db.session.query(ScheduleSlot).filter(
            ScheduleSlot.talks.any(project_id=target.id)
        )
        for slot in schedule_slots:
            cache.delete_memoized(_ScheduleSlot_is_valid, slot.id)
            cache.delete_memoized(_ScheduleAttempt_is_valid, slot.owner_id)
            if slot.owner is not None:
                cache.delete_memoized(
                    _PresentationAssessment_is_valid, slot.owner.owner_id
                )


class ConfirmRequest(db.Model, ConfirmRequestStatesMixin):
    """
    Model a confirmation request from a student
    """

    __tablename__ = "confirm_requests"

    id = db.Column(db.Integer(), primary_key=True)

    # link to parent SelectingStudent
    owner_id = db.Column(db.Integer(), db.ForeignKey("selecting_students.id"))
    owner = db.relationship(
        "SelectingStudent",
        foreign_keys=[owner_id],
        uselist=False,
        backref=db.backref(
            "confirmation_requests",
            lazy="dynamic",
            cascade="all, delete, delete-orphan",
        ),
    )

    # link to LiveProject that for which we are requesting confirmation
    project_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))
    project = db.relationship(
        "LiveProject",
        foreign_keys=[project_id],
        uselist=False,
        backref=db.backref("confirmation_requests", lazy="dynamic"),
    )

    # confirmation state
    state = db.Column(db.Integer())

    # has this request been viewed?
    viewed = db.Column(db.Boolean(), default=False)

    # timestamp of request
    request_timestamp = db.Column(db.DateTime())

    # timestamp of response
    response_timestamp = db.Column(db.DateTime())

    # if declined, a short justification
    decline_justification = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # resolved/confirmed by
    resolved_id = db.Column(db.Integer(), db.ForeignKey("users.id"))
    resolved_by = db.relationship(
        "User",
        foreign_keys=[resolved_id],
        uselist=False,
        backref=db.backref("confirmations_resolved", lazy="dynamic"),
    )

    # add comment if required
    comment = db.Column(db.Text())

    def confirm(self, resolved_by=None, comment=None):
        if self.state != ConfirmRequest.CONFIRMED:
            self.owner.student.user.post_message(
                'Your confirmation request for project "{name}" has been approved.'.format(
                    name=self.project.name
                ),
                "success",
            )
            add_notification(
                self.owner.student.user, EmailNotification.CONFIRMATION_GRANTED, self
            )

        self.state = ConfirmRequest.CONFIRMED

        if self.response_timestamp is None:
            self.response_timestamp = datetime.now()

        if resolved_by is not None:
            if isinstance(resolved_by, int):
                self.resolved_id = resolved_by
            elif isinstance(resolved_by, User):
                self.resolved_id = resolved_by.id

        if comment is not None:
            self.comment = comment

        delete_notification(
            self.project.owner.user,
            EmailNotification.CONFIRMATION_REQUEST_CREATED,
            self,
        )

    def waiting(self):
        if self.state == ConfirmRequest.CONFIRMED:
            self.owner.student.user.post_message(
                'Your confirmation approval for the project "{name}" has been reverted to "pending". '
                "If you were not expecting this event, please make an appointment to discuss "
                "with the supervisor.".format(name=self.project.name),
                "info",
            )
            add_notification(
                self.owner.student.user, EmailNotification.CONFIRMATION_TO_PENDING, self
            )

        self.response_timestamp = None
        self.resolved_by = None
        self.comment = None

        self.state = ConfirmRequest.REQUESTED

    def remove(self, notify_student: bool = False, notify_owner: bool = False):
        if notify_owner:
            add_notification(
                self.project.owner,
                EmailNotification.CONFIRMATION_REQUEST_CANCELLED,
                self.owner.student,
                object_2=self.project,
                notification_id=self.id,
            )

        if self.state == ConfirmRequest.CONFIRMED:
            if notify_student:
                self.owner.student.user.post_message(
                    f'Your confirmation approval for project "{self.project.name}" has been removed. '
                    f"If you were not expecting this event, please make an appointment to discuss with "
                    f"the project supervisor.",
                    "info",
                )
                add_notification(
                    self.owner.student.user,
                    EmailNotification.CONFIRMATION_GRANT_DELETED,
                    self.project,
                    notification_id=self.id,
                )

        elif self.state == ConfirmRequest.DECLINED:
            if notify_student:
                self.owner.student.user.post_message(
                    f'Your declined request for approval to select project "{self.project.name}" has been removed. '
                    "If you still wish to select this project, you may now make a new request "
                    "for approval.",
                    "info",
                )
                add_notification(
                    self.owner.student.user,
                    EmailNotification.CONFIRMATION_DECLINE_DELETED,
                    self.project,
                    notification_id=self.id,
                )

        elif self.state == ConfirmRequest.REQUESTED:
            if notify_student:
                self.owner.student.user.post_message(
                    'Your request for confirmation approval for project "{name}" has been removed.'.format(
                        name=self.project.name
                    ),
                    "info",
                )
                add_notification(
                    self.owner.student.user,
                    EmailNotification.CONFIRMATION_REQUEST_DELETED,
                    self.project,
                    notification_id=self.id,
                )
                delete_notification(
                    self.project.owner.user,
                    EmailNotification.CONFIRMATION_REQUEST_CREATED,
                    self,
                )


class LiveProjectAlternative(db.Model, AlternativesPriorityMixin):
    """
    Capture alternatives to a given project, with a priority
    """

    __tablename__ = "live_project_alternatives"

    # primary key
    id = db.Column(db.Integer(), primary_key=True)

    # owning project
    parent_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))
    parent = db.relationship(
        "LiveProject",
        foreign_keys=[parent_id],
        uselist=False,
        backref=db.backref(
            "alternatives", lazy="dynamic", cascade="all, delete, delete-orphan"
        ),
    )

    # alternative project
    alternative_id = db.Column(db.Integer(), db.ForeignKey("live_projects.id"))
    alternative = db.relationship(
        "LiveProject",
        foreign_keys=[alternative_id],
        uselist=False,
        backref=db.backref("alternative_for", lazy="dynamic"),
    )

    def get_library(self):
        """
        get library version of this alternative, if one exists
        :return:
        """
        lp: LiveProject = self.parent
        p: Project = lp.parent

        if p is None:
            return None

        alt_lp: LiveProject = self.alternative
        alt_p: Project = alt_lp.parent

        if alt_p is None:
            return None

        return (
            db.session.query(ProjectAlternative)
            .filter_by(parent_id=p.id, alternative_id=alt_p.id)
            .first()
        )

    @property
    def in_library(self):
        """
        test whether this alternative is also listed in the main library
        :return:
        """
        pa: Optional[ProjectAlternative] = self.get_library()
        return pa is not None

    def get_reciprocal(self):
        """
        get reciprocal version of this alternative, if one exists
        :return:
        """
        return (
            db.session.query(LiveProjectAlternative)
            .filter_by(parent_id=self.alternative_id, alternative_id=self.parent_id)
            .first()
        )

    @property
    def has_reciprocal(self):
        rcp: Optional[LiveProjectAlternative] = self.get_reciprocal()
        return rcp is not None


@cache.memoize()
def _SelectingStudent_is_valid(sid):
    obj: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sid).one()

    errors = {}
    warnings = {}

    student: StudentData = obj.student
    user: User = student.user
    config: ProjectClassConfig = obj.config

    # CONSTRAINT 1 - owning student should be active
    if not user.active:
        errors["active"] = "Student is inactive"

    # CONSTRAINT 2 - owning student should not be TWD
    if student.intermitting:
        errors["intermitting"] = "Student is intermitting"

    # CONSTRAINT 3 - if a student has submitted a ranked selection list, it should
    # contain as many selections as we are expecting
    if obj.has_submitted:
        num_selected = obj.number_selections
        num_expected = obj.number_choices
        err_msg = f"Expected {num_expected} selections, but {num_selected} submitted"

        if num_selected < num_expected:
            if obj.has_bookmarks:
                errors["number_selections"] = {
                    "msg": err_msg,
                    "quickfix": QUICKFIX_POPULATE_SELECTION_FROM_BOOKMARKS_AVAILABLE,
                }
            else:
                errors["number_selections"] = err_msg
        elif num_selected > num_expected:
            warnings["number_selections"] = err_msg

    if not config.select_in_previous_cycle:
        num_submitters = get_count(obj.submitters)
        if num_submitters > 1:
            warnings["paired_submitter"] = {
                "msg": f"Selector has too many ({num_submitters}) paired submitters"
            }
        elif num_submitters == 0:
            warnings["paired_submitter"] = {"msg": f"Selector has no paired submitter"}

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


class SelectingStudent(db.Model, ConvenorTasksMixinFactory(ConvenorSelectorTask)):
    """
    Model a student who is selecting a project in the current cycle
    """

    __tablename__ = "selecting_students"

    id = db.Column(db.Integer(), primary_key=True)

    # retired flag
    retired = db.Column(db.Boolean(), index=True)

    # enable conversion to SubmittingStudent at next rollover
    # (eg. for Research Placement or JRAs we only want to convert is student's application is successful)
    convert_to_submitter = db.Column(db.Boolean(), default=True)

    # key to ProjectClass config record that identifies this year and pclass
    config_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))
    config = db.relationship(
        "ProjectClassConfig",
        uselist=False,
        backref=db.backref("selecting_students", lazy="dynamic"),
    )

    # key to student userid
    student_id = db.Column(db.Integer(), db.ForeignKey("student_data.id"))
    student = db.relationship(
        "StudentData",
        foreign_keys=[student_id],
        uselist=False,
        backref=db.backref("selecting", lazy="dynamic"),
    )

    # research group filters applied
    group_filters = db.relationship(
        "ResearchGroup",
        secondary=sel_group_filter_table,
        lazy="dynamic",
        backref=db.backref("filtering_students", lazy="dynamic"),
    )

    # transferable skill group filters applied
    skill_filters = db.relationship(
        "TransferableSkill",
        secondary=sel_skill_filter_table,
        lazy="dynamic",
        backref=db.backref("filtering_students", lazy="dynamic"),
    )

    # SELECTION METADATA

    # 'selections' field is added by backreference from SelectionRecord
    # 'bookmarks' field is added by backreference from Bookmark

    # record time of last selection submission
    submission_time = db.Column(db.DateTime())

    # record IP address of selection request
    submission_IP = db.Column(db.String(IP_LENGTH))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = False
        self._warnings = False

    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = False
        self._warnings = False

    @property
    def _requests_waiting_query(self):
        return self.confirmation_requests.filter_by(state=ConfirmRequest.REQUESTED)

    @property
    def _requests_confirmed_query(self):
        return self.confirmation_requests.filter_by(state=ConfirmRequest.CONFIRMED)

    @property
    def _requests_declined_query(self):
        return self.confirmation_requests.filter_by(state=ConfirmRequest.DECLINED)

    @property
    def requests_waiting(self):
        return self._requests_waiting_query.all()

    @property
    def requests_confirmed(self):
        return self._requests_confirmed_query.all()

    @property
    def requests_declined(self):
        return self._requests_declined_query.all()

    @property
    def number_pending(self):
        return get_count(self._requests_waiting_query)

    @property
    def number_confirmed(self):
        return get_count(self._requests_confirmed_query)

    @property
    def number_declined(self):
        return get_count(self._requests_declined_query)

    @property
    def has_bookmarks(self):
        """
        determine whether this SelectingStudent has bookmarks
        :return:
        """
        return self.number_bookmarks > 0

    @property
    def ordered_bookmarks(self):
        """
        return bookmarks in rank order
        :return:
        """
        return self.bookmarks.order_by(Bookmark.rank)

    def re_rank_bookmarks(self):
        # reorder bookmarks to keep the ranking contiguous
        rk = 1
        bookmark: Bookmark
        for bookmark in self.bookmarks.order_by(Bookmark.rank.asc()):
            bookmark.rank = rk
            rk += 1

    def re_rank_selections(self):
        # reorder selection records to keep rankings contiguous
        rk = 1
        selection: SelectionRecord
        for selection in self.selections.order_by(SelectionRecord.rank.asc()):
            selection.rank = rk
            rk = 1

    @property
    def ordered_custom_offers(self):
        return self.custom_offers.order_by(CustomOffer.creation_timestamp.asc())

    @property
    def number_bookmarks(self):
        return get_count(self.bookmarks)

    @property
    def number_selections(self):
        return get_count(self.selections)

    def number_custom_offers(self, period: SubmissionPeriodDefinitionLike = None):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)
        return get_count(query)

    def _custom_offers_pending_query(
        self, period: SubmissionPeriodDefinitionLike = None
    ):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers.filter(CustomOffer.status == CustomOffer.OFFERED)
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)

        query = (
            query.join(SelectingStudent, SelectingStudent.id == CustomOffer.selector_id)
            .join(StudentData, StudentData.id == SelectingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .order_by(User.last_name.asc(), User.first_name.asc())
        )
        return query

    def custom_offers_pending(self, period: SubmissionPeriodDefinitionLike = None):
        return self._custom_offers_pending_query(period).all()

    def number_offers_pending(self, period: SubmissionPeriodDefinitionLike = None):
        return get_count(self._custom_offers_pending_query(period))

    def _custom_offers_declined_query(
        self, period: SubmissionPeriodDefinitionLike = None
    ):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers.filter(CustomOffer.status == CustomOffer.DECLINED)
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)

        query = (
            query.join(SelectingStudent, SelectingStudent.id == CustomOffer.selector_id)
            .join(StudentData, StudentData.id == SelectingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .order_by(User.last_name.asc(), User.first_name.asc())
        )
        return query

    def custom_offers_declined(self, period: SubmissionPeriodDefinitionLike = None):
        return self._custom_offers_declined_query(period).all()

    def number_offers_declined(self, period: SubmissionPeriodDefinitionLike = None):
        return get_count(self._custom_offers_declined_query(period))

    def _custom_offers_accepted_query(
        self, period: SubmissionPeriodDefinitionLike = None
    ):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.custom_offers.filter(CustomOffer.status == CustomOffer.ACCEPTED)
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)

        query = (
            query.join(SelectingStudent, SelectingStudent.id == CustomOffer.selector_id)
            .join(StudentData, StudentData.id == SelectingStudent.student_id)
            .join(User, User.id == StudentData.id)
            .order_by(User.last_name.asc(), User.first_name.asc())
        )
        return query

    def custom_offers_accepted(self, period: SubmissionPeriodDefinitionLike = None):
        return self._custom_offers_accepted_query(period).all()

    def number_offers_accepted(self, period: SubmissionPeriodDefinitionLike = None):
        return get_count(self._custom_offers_accepted_query(period))

    def has_accepted_offers(self, period: SubmissionPeriodDefinitionLike = None):
        return self.number_offers_accepted(period) > 0

    @property
    def has_submission_list(self):
        return self.selections.first() is not None

    @property
    def academic_year(self):
        """
        Compute the current academic year for this student, relative to our ProjectClassConfig record
        :return:
        """
        return self.student.compute_academic_year(self.config.year)

    @property
    def has_graduated(self):
        return self.student.has_graduated

    def academic_year_label(self, current_year=None, show_details=False):
        return self.student.academic_year_label(
            self.config.year, show_details=show_details, current_year=current_year
        )

    @property
    def is_initial_selection(self):
        """
        Determine whether this is the initial selection or a switch
        :return:
        """

        # if this project class does not allow switching, we are always on an "initial" selection
        if not self.config.allow_switching:
            return True

        # 28 March 2023: removed this check based on the academic year because it can produce the wrong
        # result for part-time students. We now have these for the Data Science MSc programme.
        # These students seem to select a project in Y2 which leads to a wrong result when computed
        # using the academic year, because at the moment we specify start years from projects
        # *as a whole*. Perhaps we need to specify start year *per programme*.

        # TODO: consider specifying the start year of a project type per programme. However, this might
        #  be too cumbersome.

        # academic_year = self.academic_year
        #
        # # if academic year is not None, we can do a simple numerical check
        # if academic_year is not None:
        #     config: ProjectClassConfig = self.config
        #     return self.academic_year == config.start_year - (1 if config.select_in_previous_cycle else 0)

        # if it is none, check whether there are any SubmittingStudent instances for this project type
        return (
            db.session.query(SubmittingStudent)
            .filter(SubmittingStudent.student_id == self.student_id)
            .join(
                ProjectClassConfig, ProjectClassConfig.id == SubmittingStudent.config_id
            )
            .filter(
                ProjectClassConfig.pclass_id == self.config.pclass_id,
                ProjectClassConfig.year < self.config.year,
            )
            .first()
            is None
        )

    @property
    def is_optional(self):
        """
        Determine whether this selection is optional (an example would be to sign-up for a research placement project).
        :return:
        """
        return self.config.is_optional

    @property
    def number_choices(self):
        """
        Compute the number of choices this student should make
        :return:
        """
        if self.is_initial_selection:
            return self.config.initial_choices

        else:
            return self.config.switch_choices

    @property
    def is_valid_selection(self):
        """
        Determine whether the current set of bookmarks constitutes a valid selection
        :return:
        """
        messages = []
        valid = True

        # STEP 1 - total number of bookmarks must equal or exceed required number of choices
        num_choices = self.number_choices
        if self.bookmarks.count() < num_choices:
            valid = False
            if not self.has_submitted:
                messages.append(
                    "You have insufficient bookmarks. You must submit at least {n} "
                    "choice{pl}.".format(
                        n=num_choices, pl="" if num_choices == 1 else "s"
                    )
                )

        rank = 0
        counts = {}
        sd: StudentData = self.student
        for item in self.bookmarks.order_by(Bookmark.rank).all():
            # STEP 2 - all bookmarks in "active" positions must be available to this user
            project: LiveProject = item.liveproject
            rank += 1

            if project is not None:
                # STEP 2a: if the project is not available to this student, the selection is not valid
                if not project.is_available(self):
                    valid = False
                    if not project.generic and project.owner is not None:
                        fac: FacultyData = project.owner
                        user: User = fac.user
                        messages.append(
                            "Project <em>{name}</em> (currently ranked #{rk}) is not yet available for "
                            "selection because confirmation from the supervisor is required. Please set "
                            'up a meeting by email to <a href="mailto:{email}">{supv}</a> '
                            '&langle;<a href="mailto:{email}">{email}</a>&rangle;.'
                            "".format(
                                name=project.name,
                                rk=rank,
                                supv=user.name,
                                email=user.email,
                            )
                        )
                    else:
                        messages.append(
                            "Project <em>{name}</em> (currently ranked #{rk}) is not yet available for "
                            "selection because confirmation from the supervisor is "
                            "required.".format(name=project.name, rk=rank)
                        )

                # STEP 2b - check that the maximum number of projects for a single faculty member
                # is not exceeded
                if not project.generic:
                    if project.owner_id not in counts:
                        counts[project.owner_id] = 1
                    else:
                        counts[project.owner_id] += 1

                # STEP 2c - hidden projects are not available
                if project.hidden:
                    valid = False
                    messages.append(
                        "Project <em>{name}</em> (currently ranked #{rk}) is no longer available to be selected.".format(
                            name=project.name, rk=rank
                        )
                    )

                # STEP 2d - if the student has ATAS restrictions, they cannot select ATAS-restricted projects
                if sd.ATAS_restricted and project.ATAS_restricted:
                    valid = False
                    messages.append(
                        "Project <em>{name}</em> (currently ranked #{rk}) is restricted and cannot be selected.".format(
                            name=project.name, rk=rank
                        )
                    )

            if rank >= num_choices:
                break

        # STEP 3 - second part: check the final counts
        config: ProjectClassConfig = self.config
        if config.faculty_maximum is not None:
            max = config.faculty_maximum
            for owner_id in counts:
                count = counts[owner_id]
                if count > max:
                    valid = False

                    owner = db.session.query(FacultyData).filter_by(id=owner_id).first()
                    if owner is not None:
                        messages.append(
                            "You have selected {n} project{npl} offered by {name}, "
                            "but you are only allowed to choose a maximum of <strong>{nmax} "
                            "project{nmaxpl}</strong> from the same "
                            "supervisor.".format(
                                n=count,
                                npl="" if count == 1 else "s",
                                name=owner.user.name,
                                nmax=max,
                                nmaxpl="" if max == 1 else "s",
                            )
                        )

        if valid:
            messages = ["Your current selection of bookmarks is ready to submit."]

        return (valid, messages)

    @property
    def has_submitted(self):
        """
        Determine whether a submission has been made
        :return:
        """
        # have made a selection if have accepted a sufficient number of custom offers
        number_accepted_offers = self.number_offers_accepted()
        if number_accepted_offers > 0:
            number_periods = get_count(self.config.project_class.periods)
            if number_accepted_offers >= number_periods:
                return True

        # have made a selection if submitted a list of choices:
        if self.has_submission_list:
            return True

        return False

    def is_project_submitted(self, proj):
        if isinstance(proj, int):
            proj_id = proj
        elif isinstance(proj, LiveProject):
            proj_id = proj.id
        else:
            raise RuntimeError(
                'Could not interpret "proj" parameter of type {x}'.format(x=type(proj))
            )

        if self.number_offers_accepted() > 0:
            accepted_offers = self.accepted_offers()
            if any(offer.liveproject.id == proj_id for offer in accepted_offers):
                return {"submitted": True, "rank": 1}
            else:
                return {"submitted": False}

        selrec: SelectionRecord = self.selections.filter_by(
            liveproject_id=proj_id
        ).first()
        if selrec is None:
            return {"submitted": False}

        return {"submitted": True, "rank": selrec.rank}

    def is_project_bookmarked(self, proj):
        if isinstance(proj, int):
            proj_id = proj
        elif isinstance(proj, LiveProject):
            proj_id = proj.id
        else:
            raise RuntimeError(
                'Could not interpret "proj" parameter of type {x}'.format(x=type(proj))
            )

        bkrec: Bookmark = self.bookmarks.filter_by(liveproject_id=proj_id).first()
        if bkrec is None:
            return {"bookmarked": False}

        return {"bookmarked": True, "rank": bkrec.rank}

    @property
    def ordered_selections(self):
        return self.selections.order_by(SelectionRecord.rank)

    def project_rank(self, proj):
        # ignore bookmarks; these will have been converted to
        # SelectionRecords after closure if needed, and project_rank() is only really
        # meaningful once selections have closed
        if isinstance(proj, int):
            proj_id = proj
        elif isinstance(proj, LiveProject):
            proj_id = proj.id
        else:
            raise RuntimeError(
                'Could not interpret "proj" parameter of type {x}'.format(x=type(proj))
            )

        if not self.has_submitted:
            return None

        if self.number_offers_accepted() > 0:
            accepted_offers = self.accepted_offers()
            if any(offer.liveproject.id == proj_id for offer in accepted_offers):
                return 1

            return None

        for item in self.selections.all():
            item: SelectionRecord
            if item.liveproject_id == proj_id:
                return item.rank

        return None

    def alternative_priority(self, proj):
        # if this project is not ranked, determine whether it is a viable alternative and the corresponding priority
        if isinstance(proj, int):
            proj_id = proj
        elif isinstance(proj, LiveProject):
            proj_id = proj.id
        else:
            raise RuntimeError(
                'Could not interpret "proj" parameter of type {x}'.format(x=type(proj))
            )

        data = {"project": None, "priority": 1000}

        for item in self.selections.all():
            item: SelectionRecord
            lp: LiveProject = item.liveproject

            for alt in lp.alternatives:
                alt: LiveProjectAlternative
                if alt.alternative_id == proj_id:
                    current_priority = data["priority"]
                    if alt.priority < current_priority:
                        data["priority"] = alt.priority
                        data["project"] = lp

        if data["project"] is None:
            return None

        return data

    def accepted_offers(self, period: SubmissionPeriodDefinitionLike = None):
        _pd = _get_submission_period(period, self.config.project_class)
        query = self.ordered_custom_offers.filter(
            CustomOffer.status == CustomOffer.ACCEPTED
        )
        if _pd is not None:
            query = query.filter(CustomOffer.period_id == _pd.id)
        return query

    def satisfies_recommended(self, desc):
        if get_count(desc.modules) == 0:
            return True

        for module in desc.modules:
            if get_count(self.student.programme.modules.filter_by(id=module.id)) == 0:
                return False

        return True

    @property
    def number_matches(self):
        return get_count(self.matching_records)

    @property
    def has_matches(self):
        return self.number_matches > 0

    def remove_matches(self):
        # remove any matching records pointing to this selector
        # (they are owned by the MatchingAttempt, so won't be deleted by cascade)
        for rec in self.matching_records:
            db.session.delete(rec)

    def detach_records(self):
        # remove any matching records pointing to this selector
        # (they are owned by the MatchingAttempt, so won't be deleted by cascade)
        for rec in self.matching_records:
            db.session.delete(rec)

        # remove any custom offers pointing to this selector
        # (they are owned by the LiveProject being offered, so won't be deleted by cascade)
        for offer in self.custom_offers:
            db.session.delete(offer)

    @property
    def is_valid(self):
        flag, self._errors, self._warnings = _SelectingStudent_is_valid(self.id)
        self._validated = True

        return flag

    @property
    def has_issues(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0 or len(self._warnings) > 0

    @property
    def errors(self):
        if not self._validated:
            check = self.is_valid
        return self._errors.values()

    @property
    def warnings(self):
        if not self._validated:
            check = self.is_valid
        return self._warnings.values()


@listens_for(SelectingStudent, "before_update")
def _SelectingStudent_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SelectingStudent_is_valid, target.id)

        for record in target.matching_records:
            _delete_MatchingRecord_cache(record.id, record.matching_id)


@listens_for(SelectingStudent, "before_insert")
def _SelectingStudent_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SelectingStudent_is_valid, target.id)


@listens_for(SelectingStudent, "before_delete")
def _SelectingStudent_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SelectingStudent_is_valid, target.id)


@cache.memoize()
def _SubmittingStudent_is_valid(sid):

    obj: SubmittingStudent = db.session.query(SubmittingStudent).filter_by(id=sid).one()

    errors = {}
    warnings = {}

    student: StudentData = obj.student
    user: User = student.user
    config: ProjectClassConfig = obj.config

    # CONSTRAINT 1 - owning student should be active
    if not user.active:
        errors["active"] = "Student is inactive"

    # CONSTRAINT 2 - owning student should not be TWD
    if student.intermitting:
        errors["intermitting"] = "Student is intermitting"

    # CONSTRAINT 3 - CONSTITUENT SubmissionRecord INSTANCES SHOULD BE INDIVIDUALLY VALID
    records_errors = False
    records_warnings = False
    for record in obj.records:
        record: SubmissionRecord
        flag = record.has_issues

        if flag:
            if len(record.errors) > 0:
                records_errors = True
            if len(record.warnings) > 0:
                records_warnings = True

    if records_errors:
        if config.number_submissions > 1:
            errors["records"] = (
                "Project or role assignments for some submission periods have errors"
            )
        else:
            errors["records"] = "Project or role assignments have errors"
    elif records_warnings:
        if config.number_submissions > 1:
            warnings["records"] = (
                "Project or role assignments for some submission periods have warnings"
            )
        else:
            warnings["records"] = "Project or role assignments have warnings"

    # CONSTRAINT 4 - check if there should be a paired selector instance
    if not config.select_in_previous_cycle:
        if obj.selector is None:
            warnings["paired_selector"] = {"msg": "Submitter has no paired selector"}

    if len(errors) > 0:
        return False, errors, warnings

    return True, errors, warnings


class SubmittingStudent(db.Model, ConvenorTasksMixinFactory(ConvenorSubmitterTask)):
    """
    Model a student who is submitting work for evaluation in the current cycle
    """

    __tablename__ = "submitting_students"

    id = db.Column(db.Integer(), primary_key=True)

    # retired flag
    retired = db.Column(db.Boolean(), index=True)

    # key to ProjectClass config record that identifies this year and pclass
    config_id = db.Column(db.Integer(), db.ForeignKey("project_class_config.id"))
    config = db.relationship(
        "ProjectClassConfig",
        uselist=False,
        backref=db.backref("submitting_students", lazy="dynamic"),
    )

    # key to student userid
    student_id = db.Column(db.Integer(), db.ForeignKey("student_data.id"))
    student = db.relationship(
        "StudentData",
        foreign_keys=[student_id],
        uselist=False,
        backref=db.backref("submitting", lazy="dynamic"),
    )

    # capture parent SelectingStudent, if one exists
    selector_id = db.Column(
        db.Integer(), db.ForeignKey("selecting_students.id"), default=None
    )
    selector = db.relationship(
        "SelectingStudent",
        foreign_keys=[selector_id],
        uselist=False,
        backref=db.backref("submitters", lazy="dynamic"),
    )

    # are the assignments published to the student?
    published = db.Column(db.Boolean())

    # CANVAS INTEGRATION

    # user id of matched canvas submission, or None if we cannot find a match
    canvas_user_id = db.Column(db.Integer(), default=None, nullable=True)

    # flag a student that is missing in the Canvas database
    canvas_missing = db.Column(db.Integer(), default=None, nullable=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._validated = False
        self._errors = False
        self._warnings = False

    @orm.reconstructor
    def _reconstruct(self):
        self._validated = False
        self._errors = False
        self._warnings = False

    @property
    def selector_config(self):
        # if we already have a cached SelectingStudent instance, use that to determine the config
        if self.selector is not None:
            return self.selector.config

        # otherwise, work it out "by hand"
        current_config: ProjectClassConfig = self.config

        if current_config.select_in_previous_cycle:
            return current_config.previous_config

        return current_config

    @property
    def academic_year(self):
        """
        Compute the current academic year for this student, relative this ProjectClassConfig
        :return:
        """
        return self.student.compute_academic_year(self.config.year)

    def academic_year_label(self, show_details=False, current_year=None):
        return self.student.academic_year_label(
            self.config.year, show_details=show_details, current_year=current_year
        )

    def get_assignment(self, period=None):
        from .project_class import SubmissionPeriodRecord

        if period is None:
            period = self.config.current_period

        if isinstance(period, SubmissionPeriodRecord):
            period_number = period.submission_period
        elif isinstance(period, int):
            period_number = period
        else:
            raise TypeError(
                "Expected period to be a SubmissionPeriodRecord or an integer"
            )

        records: List[SubmissionRecord] = (
            self.records.join(
                SubmissionPeriodRecord,
                SubmissionPeriodRecord.id == SubmissionRecord.period_id,
            )
            .filter(SubmissionPeriodRecord.submission_period == period_number)
            .all()
        )

        if len(records) == 0:
            return None
        elif len(records) == 1:
            return records[0]

        raise RuntimeError("Too many projects assigned for this submission period")

    @property
    def ordered_assignments(self):
        from .project_class import SubmissionPeriodRecord

        return self.records.join(
            SubmissionPeriodRecord,
            SubmissionPeriodRecord.id == SubmissionRecord.period_id,
        ).order_by(SubmissionPeriodRecord.submission_period.asc())

    @property
    def supervisor_feedback_late(self):

        supervisor_states = [
            r.supervisor_feedback_state == SubmissionRecord.FEEDBACK_LATE
            for r in self.records
        ]
        response_states = [
            r.supervisor_response_state == SubmissionRecord.FEEDBACK_LATE
            for r in self.records
        ]

        return any(supervisor_states) or any(response_states)

    @property
    def marker_feedback_late(self):

        states = [
            r.marker_feedback_state == SubmissionRecord.FEEDBACK_LATE
            for r in self.records
        ]

        return any(states)

    @property
    def presentation_feedback_late(self):
        states = [r.presentation_feedback_late for r in self.records]

        return any(states)

    @property
    def has_late_feedback(self):
        return (
            self.supervisor_feedback_late
            or self.marker_feedback_late
            or self.presentation_feedback_late
        )

    @property
    def has_report(self):
        """
        Returns true if a report has been uploaded and processed for the current submission period
        :return:
        """
        sub: SubmissionRecord = self.get_assignment()
        return sub.processed_report is not None

    @property
    def has_attachments(self):
        """
        Returns true if attachments have been uploaded for the current submission period
        :return:
        """
        sub: SubmissionRecord = self.get_assignment()
        return sub.attachments.first() is not None

    def detach_records(self):
        """
        Remove submission records from any linked ScheduleSlot instance, preparatory to deleting this
        record itself
        :return:
        """
        for rec in self.records:
            for slot in rec.scheduled_slots:
                slot.talks.remove(rec)

            for slot in rec.original_scheduled_slots:
                slot.original_talks.remove(rec)

    @property
    def is_valid(self):
        flag, self._errors, self._warnings = _SubmittingStudent_is_valid(self.id)
        self._validated = True

        return flag

    @property
    def has_issues(self):
        if not self._validated:
            check = self.is_valid
        return len(self._errors) > 0 or len(self._warnings) > 0

    @property
    def errors(self):
        if not self._validated:
            check = self.is_valid
        return self._errors.values()

    @property
    def warnings(self):
        if not self._validated:
            check = self.is_valid
        return self._warnings.values()


@listens_for(SubmittingStudent, "before_update")
def _SubmittingStudent_update_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SubmittingStudent_is_valid, target.id)


@listens_for(SubmittingStudent, "before_insert")
def _SubmittingStudent_insert_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SubmittingStudent_is_valid, target.id)


@listens_for(SubmittingStudent, "before_delete")
def _SubmittingStudent_delete_handler(mapper, connection, target):
    target._validated = False

    with db.session.no_autoflush:
        cache.delete_memoized(_SubmittingStudent_is_valid, target.id)
