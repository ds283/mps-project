#
# Created by David Seery on 09/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app, render_template
from flask_mailman import EmailMultiAlternatives

from sqlalchemy import and_, or_
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import (
    User,
    TaskRecord,
    BackupRecord,
    ProjectClassConfig,
    Project,
    FacultyData,
    EnrollmentRecord,
    LiveProject,
    SelectingStudent,
    MatchingAttempt,
)

from ..task_queue import progress_update, register_task

from ..shared.convenor import add_liveproject

from celery import chain, group
from celery.exceptions import Ignore

from datetime import datetime, date
from dateutil import parser


def register_golive_tasks(celery):
    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def pclass_golive(self, task_id, config_id, convenor_id, deadline, auto_close, notify_faculty, notify_selectors, accommodate_matching, full_CATS):
        progress_update(task_id, TaskRecord.RUNNING, 0, "Preparing to Go Live...", autocommit=True)

        if isinstance(deadline, str):
            deadline: date = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        if not isinstance(auto_close, bool):
            auto_close = bool(auto_close)

        if not isinstance(notify_faculty, bool):
            notify_faculty = bool(notify_faculty)

        if not isinstance(notify_selectors, bool):
            notify_selectors = bool(notify_selectors)

        if isinstance(accommodate_matching, int):
            accommodate_matching: MatchingAttempt = db.session.query(MatchingAttempt).filter_by(id=accommodate_matching).first()

        # get database records for this project class
        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
            convenor: User = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None or convenor is None:
            if convenor is not None:
                convenor.post_message("Go Live failed because some database records could not be loaded.", "danger", autocommit=True)

            if config is None:
                self.update_state("FAILURE", meta={"msg": "Could not load ProjectClassConfig record from database"})

            if convenor is None:
                self.update_state("FAILURE", meta={"msg": "Could not load convenor User record from database"})

            raise self.replace(golive_fail.si(task_id, convenor_id))

        if not config.project_class.publish:
            return None

        year = config.year

        if config.selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_CONFIRMATIONS_NOT_ISSUED:
            convenor.post_message(
                "Cannot yet Go Live for {name} {yra}-{yrb} "
                "because confirmation requests have not been "
                "issued.".format(name=config.name, yra=year, yrb=year + 1),
                "warning",
                autocommit=True,
            )
            self.update_state("FAILURE", meta={"msg": "Confirmation requests have not been issued"})
            raise self.replace(golive_fail.si(task_id, convenor_id))

        if config.selector_lifecycle == ProjectClassConfig.SELECTOR_LIFECYCLE_WAITING_CONFIRMATIONS:
            convenor.post_message(
                "Cannot yet Go Live for {name} {yra}-{yrb} "
                "because not all confirmation responses have not been "
                "received. If needed, use Force Confirm to remove any blocking "
                "responses.".format(name=config.name, yra=year, yrb=year + 1),
                "warning",
                autocommit=True,
            )
            self.update_state("FAILURE", meta={"msg": "Some Go Live confirmations are still outstanding"})
            raise self.replace(golive_fail.si(task_id, convenor_id))

        pclass_id = config.pclass_id

        # build list of projects to be attached when we go live
        # note that we exclude any projects where the supervisor is not normally enrolled
        attached_projects = (
            db.session.query(Project)
            .filter(Project.active == True, Project.project_classes.any(id=pclass_id))
            .join(User, User.id == Project.owner_id, isouter=True)
            .join(FacultyData, FacultyData.id == Project.owner_id, isouter=True)
            .join(EnrollmentRecord, EnrollmentRecord.owner_id == Project.owner_id, isouter=True)
            .filter(
                or_(
                    Project.generic == True,
                    and_(
                        Project.generic == False,
                        User.active == True,
                        FacultyData.id != None,
                        EnrollmentRecord.pclass_id == pclass_id,
                        EnrollmentRecord.supervisor_state == EnrollmentRecord.SUPERVISOR_ENROLLED,
                    ),
                )
            )
            .order_by(User.last_name, User.first_name)
            .all()
        )

        # weed out projects that do not satisfy is_offerable predicate
        attached_projects = [p for p in attached_projects if p.is_offerable]

        # weed out projects belonging to supervisors that are 'full' as defined by the accommodated matching
        if accommodate_matching is not None:
            print('## Filtering projects to accommodate matching "{name}"'.format(name=accommodate_matching.name))

            def is_full(supervisor_id):
                sup_CATS, mark_CATS, mod_CATS = accommodate_matching.get_faculty_CATS(supervisor_id)
                project_CATS = config.CATS_supervision

                # a supervisor is full if their existing CATS allocation (from the matching we're accommodating)
                # plus the CATS required to supervise one (typical) project for this ProjectClass would
                # take the supervisor over the maximum allowed CATS.
                # The maximum is either specified (if full_CATS is not None) or taken from the
                # matching we're accommodating
                if full_CATS is not None:
                    return sup_CATS + project_CATS > full_CATS
                else:
                    return sup_CATS + project_CATS > accommodate_matching.CATS_max

            config.accommodate_matching = accommodate_matching
            config.full_CATS = full_CATS

            try:
                db.session.commit()
            except SQLAlchemyError as e:
                db.session.rollback()
                current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
                raise self.retry()

            filtered_projects = []
            for p in attached_projects:
                if not p.generic and p.owner_id is not None and is_full(p.owner_id):
                    print(
                        '## dropping project "{pname}" offered by supervisor "{sname}" because their CATS '
                        "allocation exceeds the limit (full_CATS={fc})".format(sname=p.owner.user.name, pname=p.name, fc=full_CATS)
                    )
                else:
                    filtered_projects.append(p)

            attached_projects = filtered_projects

        # check whether the list of projects is empty
        if len(attached_projects) == 0 and not auto_close:
            convenor.post_message(
                "Cannot yet Go Live for {name} {yra}-{yrb} "
                "because there would be no attached projects. If this is not what you expect, "
                "check active flags and sabbatical/exemption status for all enrolled faculty."
                "".format(name=config.name, yra=year, yrb=year + 1),
                "error",
                autocommit=True,
            )
            self.update_state("FAILURE", meta={"msg": "No attached projects"})
            return golive_fail.apply_async(args=(task_id, convenor_id))

        # build group of parallel tasks to take each offerable attached project to a live counterpart
        projects_group = group(project_golive.si(n + 1, p.id, config_id) for n, p in enumerate(attached_projects))

        # get backup task from Celery instance
        celery = current_app.extensions["celery"]
        backup = celery.tasks["app.tasks.backup.backup"]

        front_chain = chain(
            golive_initialize.si(task_id),
            backup.si(
                convenor_id,
                type=BackupRecord.PROJECT_GOLIVE_FALLBACK,
                tag="golive",
                description="Rollback snapshot for {proj} Go Live {yr}".format(proj=config.name, yr=year),
            ),
            golive_preprojects.si(task_id),
            projects_group,
        )

        # if this is a go-live-then-close job, don't bother sending email notifications;
        # otherwise, check which email notifications were enabled
        if not auto_close:
            if notify_faculty:
                front_chain = front_chain | golive_notify_faculty.si(task_id, config_id, convenor_id, deadline)
                print("## email notifications to faculty enabled")
            else:
                print("## email notifications to faculty disabled")

            if notify_selectors:
                front_chain = front_chain | golive_notify_selectors.si(task_id, config_id, convenor_id, deadline)
                print("## email notifications to selectors enabled")
            else:
                print("## email notifications to selectors disabled")

        else:
            print("## email notifications disabled by auto-close mode")

        seq = chain(front_chain, golive_finalize.si(task_id, config_id, convenor_id, deadline)).on_error(golive_fail.si(task_id, convenor_id))

        raise self.replace(seq)

    @celery.task()
    def golive_initialize(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 5, "Building rollback Go Live snapshot...", autocommit=True)

    @celery.task()
    def golive_preprojects(task_id):
        progress_update(task_id, TaskRecord.RUNNING, 30, "Moving attached projects onto the live system...", autocommit=True)

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def golive_notify_faculty(self, task_id, config_id, convenor_id, deadline):
        progress_update(task_id, TaskRecord.RUNNING, 60, "Sending email notifications to faculty supervisors...", autocommit=True)

        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            raise Ignore()

        # build list of faculty that are enrolled as supervisors
        faculty = set()

        # select faculty that are enrolled on this particular project class
        eq = (
            db.session.query(EnrollmentRecord.id, EnrollmentRecord.owner_id)
            .filter_by(pclass_id=config.pclass_id, supervisor_state=EnrollmentRecord.SUPERVISOR_ENROLLED)
            .subquery()
        )

        fd = (
            db.session.query(eq.c.owner_id, User, FacultyData)
            .join(User, User.id == eq.c.owner_id)
            .join(FacultyData, FacultyData.id == eq.c.owner_id)
            .filter(User.active == True)
        )

        for id, user, data in fd:
            if user not in config.golive_notified and data.id not in faculty:
                faculty.add(data.id)

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        task = chain(
            group(faculty_notification_email.si(d, config_id, deadline) for d in faculty if d is not None),
            notify.s(convenor_id, "{n} notification{pl} issued to faculty supervisors", "info"),
        )

        raise self.replace(task)

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def golive_notify_selectors(self, task_id, config_id, convenor_id, deadline):
        progress_update(task_id, TaskRecord.RUNNING, 70, "Sending email notifications to student selectors...", autocommit=True)

        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            raise Ignore()

        # build list of faculty that are enrolled as supervisors
        selectors = set()

        for sel in config.selecting_students.filter_by(retired=False).all():
            if sel.student.user not in config.golive_notified and sel.id not in selectors:
                selectors.add(sel.id)

        notify = celery.tasks["app.tasks.utilities.email_notification"]

        task = chain(
            group(student_notification_email.si(d, config_id, deadline) for d in selectors if d is not None),
            notify.s(convenor_id, "{n} notification{pl} issued to student selectors", "info"),
        )

        raise self.replace(task)

    @celery.task(bind=True, default_retry_delay=30)
    def set_notified(self, config_id, user_id):
        try:
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
            user = User.query.filter_by(id=user_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if user is None or config is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            raise Ignore()

        config.golive_notified.append(user)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def faculty_notification_email(self, faculty_id, config_id, deadline):
        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            data = FacultyData.query.filter_by(id=faculty_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None or config is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            raise Ignore()

        msg = EmailMultiAlternatives(
            subject="{name}: project list now published to students".format(name=config.project_class.name),
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_app.config["MAIL_REPLY_TO"]],
            to=[data.user.email],
        )

        # get live projects belonging to both this project class and this faculty member
        projects = config.live_projects.filter_by(owner_id=faculty_id).all()

        expect_requests = data.sign_off_students
        projects_use_signoff = False
        if expect_requests:
            for p in projects:
                if p.meeting_reqd == LiveProject.MEETING_REQUIRED:
                    projects_use_signoff = True
                    break

        msg.body = render_template(
            "email/go_live/faculty.txt",
            deadline=deadline,
            user=data.user,
            pclass=config.project_class,
            config=config,
            number_projects=len(projects),
            projects=projects,
            expect_requests=(expect_requests and projects_use_signoff),
        )

        # register a new task in the database
        task_id = register_task(msg.subject, description="Send confirmation request email to {r}".format(r=", ".join(msg.to)))

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        email_chain = chain(send_log_email.si(task_id, msg), set_notified.si(config_id, faculty_id))
        email_chain.apply_async(task_id=task_id)

        return 1

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def student_notification_email(self, selector_id, config_id, deadline):
        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            data = SelectingStudent.query.filter_by(id=selector_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if data is None or config is None:
            self.update_state("FAILURE", meta={"msg": "Could not load database records"})
            raise Ignore()

        msg = EmailMultiAlternatives(
            subject="{name}: project list now available".format(name=config.project_class.name),
            from_email=current_app.config["MAIL_DEFAULT_SENDER"],
            reply_to=[current_app.config["MAIL_REPLY_TO"]],
            to=[data.student.user.email],
        )

        msg.body = render_template(
            "email/go_live/selector.txt", user=data.student.user, student=data, pclass=config.project_class, config=config, deadline=deadline
        )

        html = render_template(
            "email/go_live/selector.html", user=data.student.user, student=data, pclass=config.project_class, config=config, deadline=deadline
        )
        msg.attach_alternative(html, "text/html")

        # register a new task in the database
        task_id = register_task(msg.subject, description="Send confirmation request email to {r}".format(r=", ".join(msg.to)))

        send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
        email_chain = chain(send_log_email.si(task_id, msg), set_notified.si(config_id, data.student_id))
        email_chain.apply_async(task_id=task_id)

        return 1

    @celery.task(bind=True, serializer="pickle", default_retry_delay=30)
    def golive_finalize(self, task_id, config_id, convenor_id, deadline):
        progress_update(task_id, TaskRecord.SUCCESS, 100, "Go Live complete", autocommit=False)

        if isinstance(deadline, str):
            deadline = parser.parse(deadline).date()
        else:
            if not isinstance(deadline, date):
                raise RuntimeError('Could not interpret "deadline" argument')

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is not None:
            # send direct message to user announcing successful Go Live event
            convenor.post_message(
                'Go Live "{proj}" ' "for {yra}-{yrb} is now complete".format(proj=config.name, yra=config.submit_year_a, yrb=config.submit_year_b),
                "success",
                autocommit=False,
            )

            convenor.send_replacetext("live-project-count", "{c}".format(c=config.live_projects.count()), autocommit=False)

        config.live = True
        config.live_deadline = deadline

        # try to avoid sending duplicate summary emails if we have been through Go Live before
        send_summary_email = config.golive_timestamp is None

        config.golive_id = convenor_id
        config.golive_timestamp = datetime.now()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if send_summary_email:
            recipients = set([config.project_class.convenor.user.email])
            if convenor is not None:
                recipients.add(convenor.email)

            for coconvenor in config.project_class.coconvenors:
                recipients.add(coconvenor.user.email)

            for user in config.project_class.office_contacts:
                recipients.add(user.email)

            msg = EmailMultiAlternatives(
                subject='[mpsprojects] "{name}": project list now published to ' "students".format(name=config.project_class.name),
                from_email=current_app.config["MAIL_DEFAULT_SENDER"],
                reply_to=[current_app.config["MAIL_REPLY_TO"]],
                to=list(recipients),
            )

            msg.body = render_template("email/go_live/convenor.txt", pclass=config.project_class, config=config, deadline=deadline)

            # register a new task in the database
            task_id = register_task(msg.subject, description="Send convenor email notification")

            send_log_email = celery.tasks["app.tasks.send_log_email.send_log_email"]
            send_log_email.apply_async(args=(task_id, msg), task_id=task_id)

    @celery.task(bind=True, default_retry_delay=30)
    def golive_fail(self, task_id, convenor_id):
        progress_update(task_id, TaskRecord.FAILURE, 100, "Encountered error during Go Live", autocommit=False)

        try:
            convenor = User.query.filter_by(id=convenor_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if convenor is not None:
            convenor.post_message("Go Live failed. Please contact a system administrator", "error", autocommit=False)

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

    @celery.task(bind=True, default_retry_delay=30)
    def project_golive(self, number, pid, config_id):
        try:
            add_liveproject(number, pid, config_id, autocommit=True)

        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        except KeyError as e:
            db.session.rollback()
            current_app.logger.exception("KeyError exception", exc_info=e)
            self.update_state(state="FAILURE", meta={"msg": "Database error: {msg}".format(msg=str(e))})
            raise Ignore()

    @celery.task(bind=True, default_retry_delay=30)
    def golive_close(self, config_id, convenor_id):
        try:
            convenor = User.query.filter_by(id=convenor_id).first()
            config: ProjectClassConfig = ProjectClassConfig.query.filter_by(id=config_id).first()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if config is not None:
            config.selection_closed = True
            config.closed_id = convenor_id
            config.closed_timestamp = datetime.now()

        if convenor is not None:
            convenor.post_message(
                'Student selections for "{name}" {yeara}-{yearb} have now been'
                " closed".format(name=config.name, yeara=config.submit_year_a, yearb=config.submit_year_b),
                "success",
            )

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()
