#
# Created by David Seery on 2019-03-26.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app

from ..database import db
from ..models import ConfirmRequest, LiveProject, ProjectClassConfig, SelectingStudent, User

from celery.exceptions import Ignore

from sqlalchemy.exc import SQLAlchemyError


def _reassign_liveprojects(item_list, dest_config):
    delete_items = set()

    for item in item_list:
        new_liveproject = dest_config.live_projects.filter_by(parent_id=item.liveproject.parent_id).first()

        # delete record if no match; otherwise reassign
        if new_liveproject is None:
            delete_items.add(item)
        else:
            item.liveproject_id = new_liveproject.id

    # delete records that had no match
    for item in delete_items:
        db.session.delete(item)


def register_selecting_tasks(celery):

    @celery.task(bind=True, default_retry_delay=30)
    def remove_new(self, config_id, faculty_id):
        if isinstance(config_id, str):
            config_id = int(config_id)

        try:
            lps = db.session.query(LiveProject) \
                .filter(LiveProject.config_id == config_id,
                        LiveProject.owner_id == faculty_id).all()
        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        for lp in lps:
            unseen_confirmations = lp.confirmation_requests \
                .filter(ConfirmRequest.state == ConfirmRequest.REQUESTED,
                        ConfirmRequest.viewed != True).all()

            for confirm in unseen_confirmations:
                confirm.viewed = True

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()


    @celery.task(bind=True, default_retry_delay=10)
    def move_selector(self, sel_id, dest_id, user_id):
        try:
            sel: SelectingStudent = db.session.query(SelectingStudent).filter_by(id=sel_id).first()
            dest_config: ProjectClassConfig = db.session.query(ProjectClassConfig).filter_by(id=dest_id).first()
            user: User = db.session.query(User).filter_by(id=user_id).first()

        except SQLAlchemyError as e:
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        if sel is None:
            self.update_state('FAILURE', meta={'msg': 'Could not load SelectingStudent id={id} from database'.format(od=sel_id)})
            raise Ignore()

        if dest_config is None:
            self.update_state('FAILURE', meta={'msg': 'Could not load ProjectClassConfig id={id} from '
                                               'database'.format(id=dest_id)})
            raise Ignore()

        if user is None:
            self.update_date('FAILURE', meta={'msg': 'Could not load User id={id} from database'.format(id=user_id)})
            raise Ignore()

        # # detach any matches of which this selector is a part; they won't make sense after the move
        sel.remove_matches()

        # # reassign selector
        sel.config_id = dest_config.id

        # walk through bookmarks
        _reassign_liveprojects(sel.custom_offers, dest_config)
        _reassign_liveprojects(sel.bookmarks, dest_config)
        _reassign_liveprojects(sel.selections, dest_config)

        sel.re_rank_bookmarks()
        sel.re_rank_selections()

        try:
            db.session.commit()
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.exception("SQLAlchemyError exception", exc_info=e)
            raise self.retry()

        user.post_message('Selector "{name}" has been moved to project class "{pcl}".'.format(name=sel.student.user.name,
                                                                                              pcl=dest_config.name),
                          'success', autocommit=True)
