#
# Created by David Seery on 15/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from flask import current_app
from celery.exceptions import Ignore

from pymongo import MongoClient
from datetime import datetime, timedelta

from ..shared.timer import Timer


def register_session_tasks(celery):
    @celery.task(bind=True, default_retry_delay=30)
    def sift_sessions(self):
        mongo_url = current_app.config["SESSION_MONGO_URL"]
        db_name = current_app.config["SESSION_MONGODB_DB"]
        collection_name = current_app.config["SESSION_MONGODB_COLLECT"]
        key_prefix = current_app.config["SESSION_KEY_PREFIX"]

        if mongo_url is None:
            raise Ignore()

        print("-- Entering sift_sessions maintenance cycle for MongoDB server-side sessions")

        with MongoClient(host=mongo_url) as client:
            db = client[db_name]
            collection = db[collection_name]

            # first, if there are any sessions without an expiry date,
            # set their expiry to today plus 7 days
            expiry_date = datetime.now() + timedelta(days=7)
            with Timer() as expiry_timer:
                result = collection.update_many({"expiration": None}, {"$set": {"expiration": expiry_date}}, upsert=False)
            print("-- identified {matched} sessions without a valid expiry date".format(matched=result.matched_count))
            print("-- modified {modified} sessions to expires on {date}".format(modified=result.modified_count, date=expiry_date))
            print("-- elapsed time for query = {s}".format(s=expiry_timer.interval))

            # second, determine whether there are any sessions that are stale and
            # should be removed
            stale_date = datetime.now() - timedelta(days=1)
            with Timer() as stale_timer:
                result = collection.delete_many({"expiration": {"$lt": stale_date}})
            print("-- deleted {count} stale sessions".format(count=result.deleted_count))
            print("-- elapsed time for query = {s}".format(s=stale_timer.interval))

        print("-- sift_sessions maintenance cycle complete")
