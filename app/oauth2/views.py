#
# Created by David Seery on 17/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from urllib.parse import urlparse

from boxsdk import OAuth2
from flask import redirect, url_for, session, flash, request, current_app
from flask_login import current_user, login_required

from . import oauth2
from ..database import db
from ..shared.utils import home_dashboard_url
from ..shared.workflow_logging import log_db_commit


def _safe_next_url(next_url):
    """
    Validate that next_url is a safe relative URL to prevent open-redirect attacks.
    Returns the URL if safe, otherwise None.
    """
    if not next_url:
        return None

    parsed = urlparse(next_url)

    # Must be a relative URL: no scheme, no netloc, and path must start with /
    # Also reject paths starting with // (protocol-relative external URLs)
    if parsed.scheme or parsed.netloc:
        return None

    if not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return None

    return next_url


@oauth2.route("/box")
@login_required
def box_login():
    """
    Initiate the Box OAuth2 authorisation flow. Redirects the user to the Box
    authorisation page. Stores the CSRF state token and optional return URL in
    the Flask session so they survive the round-trip to Box.
    """
    client_id = current_app.config.get("BOX_CLIENT_ID")
    client_secret = current_app.config.get("BOX_CLIENT_SECRET")

    if not client_id or not client_secret:
        flash("Box integration is not configured on this server.", "error")
        return redirect(home_dashboard_url())

    # Thread the return URL through the flow if provided and safe.
    next_url = _safe_next_url(request.args.get("next"))
    session["box_oauth_next"] = next_url

    redirect_url = url_for("oauth2.box_callback", _external=True)

    box_oauth = OAuth2(client_id=client_id, client_secret=client_secret)
    auth_url, csrf_token = box_oauth.get_authorization_url(redirect_url=redirect_url)

    session["box_oauth_state"] = csrf_token

    return redirect(auth_url)


@oauth2.route("/box-callback")
@login_required
def box_callback():
    """
    Handle the Box OAuth2 callback. Exchanges the authorisation code for access
    and refresh tokens, stores them on the current user, and redirects back to
    the page that initiated the flow (or the home dashboard as a fallback).
    """
    # Always consume the session values so they don't linger.
    expected_state = session.pop("box_oauth_state", None)
    next_url = session.pop("box_oauth_next", None)

    fallback_url = next_url or home_dashboard_url()

    # Verify CSRF state.
    returned_state = request.args.get("state")
    if not expected_state or returned_state != expected_state:
        flash("Box authorisation failed: invalid state token. Please try again.", "error")
        return redirect(fallback_url)

    auth_code = request.args.get("code")
    if not auth_code:
        flash("Box authorisation failed: no authorisation code returned. Please try again.", "error")
        return redirect(fallback_url)

    client_id = current_app.config.get("BOX_CLIENT_ID")
    client_secret = current_app.config.get("BOX_CLIENT_SECRET")

    try:
        box_oauth = OAuth2(client_id=client_id, client_secret=client_secret)
        access_token, refresh_token = box_oauth.authenticate(auth_code)
    except Exception as e:
        current_app.logger.exception("Box OAuth2 authentication error", exc_info=e)
        flash("Box authorisation failed: could not exchange code for tokens. Please try again.", "error")
        return redirect(fallback_url)

    try:
        current_user.box_access_token = access_token
        current_user.box_refresh_token = refresh_token
        current_user.box_token_valid = True
        db.session.commit()

        log_db_commit(
            f"User {current_user.name} linked their Box account",
            user=current_user,
        )
    except Exception as e:
        current_app.logger.exception("Error saving Box tokens", exc_info=e)
        db.session.rollback()
        flash("Box account was authorised but tokens could not be saved. Please try again.", "error")
        return redirect(fallback_url)

    flash("Your Box account has been linked successfully.", "success")
    return redirect(fallback_url)
