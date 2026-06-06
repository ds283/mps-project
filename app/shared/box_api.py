#
# Created by David Seery on 06/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime, timedelta
from typing import Optional

import requests
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from ..database import db
from ..models import User
from .internal_redis import get_redis

_REFRESH_THRESHOLD = timedelta(minutes=50)
_LOCK_TTL_SECONDS = 30


def _persist_tokens(user: User, access_token: str, refresh_token: str) -> None:
    user.box_access_token = access_token
    user.box_refresh_token = refresh_token
    user.box_token_valid = True
    # box_updated_at is handled by onupdate= on the column
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise


def _do_token_refresh(user: User) -> None:
    client_id = current_app.config.get("BOX_CLIENT_ID")
    client_secret = current_app.config.get("BOX_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Box is not configured on this server.")

    resp = requests.post(
        "https://api.box.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": user.box_refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=10,
    )
    if not resp.ok:
        user.box_token_valid = False
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
        resp.raise_for_status()

    data = resp.json()
    _persist_tokens(user, data["access_token"], data["refresh_token"])


def _make_db_token_storage_class():
    """Build a TokenStorage subclass that persists refreshed tokens to the DB User row."""
    from box_sdk_gen import AccessToken, TokenStorage

    class DBTokenStorage(TokenStorage):
        def __init__(self, user: User):
            self._user_id = user.id

        def _get_user(self) -> User:
            return db.session.query(User).filter_by(id=self._user_id).one()

        def store(self, token) -> None:
            u = self._get_user()
            u.box_access_token = token.access_token
            u.box_refresh_token = token.refresh_token
            u.box_token_valid = True
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

        def get(self) -> Optional[AccessToken]:
            u = self._get_user()
            if not u.box_token_valid:
                return None
            return AccessToken(
                access_token=u.box_access_token,
                refresh_token=u.box_refresh_token,
            )

        def clear(self) -> None:
            u = self._get_user()
            u.box_token_valid = False
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()

    return DBTokenStorage


def get_box_client(user: User):
    """Return a valid Box SDK client for user, performing a proactive refresh if needed."""
    client_id = current_app.config.get("BOX_CLIENT_ID")
    client_secret = current_app.config.get("BOX_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Box is not configured on this server.")

    now = datetime.now()

    def _needs_refresh(u: User) -> bool:
        return not u.box_token_valid or u.box_updated_at is None or (now - u.box_updated_at) > _REFRESH_THRESHOLD

    if _needs_refresh(user):
        r = get_redis()
        lock_key = f"box_token_lock:{user.id}"
        acquired = r.set(lock_key, "1", nx=True, ex=_LOCK_TTL_SECONDS)
        try:
            if acquired:
                db.session.refresh(user)
                if _needs_refresh(user):
                    _do_token_refresh(user)
        finally:
            if acquired:
                r.delete(lock_key)

    from box_sdk_gen import BoxClient, BoxOAuth, OAuthConfig

    DBTokenStorage = _make_db_token_storage_class()
    box_oauth = BoxOAuth(
        config=OAuthConfig(
            client_id=client_id,
            client_secret=client_secret,
            token_storage=DBTokenStorage(user),
        )
    )
    return BoxClient(auth=box_oauth)


def revoke_box_auth(user: User) -> None:
    """Clear Box credentials when a user explicitly disconnects Box."""
    user.box_token_valid = False
    user.box_access_token = None
    user.box_refresh_token = None
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise
