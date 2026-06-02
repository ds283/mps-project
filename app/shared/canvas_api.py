#
# Created by David Seery on 02/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Centralised Canvas REST API HTTP client for MPS-Project.

This module has no Flask, SQLAlchemy, or Celery dependencies. Callers must
extract credentials from ORM objects before passing them in as plain Python
values. CanvasAPIError is the sole exception type raised by all public functions.
"""

from urllib.parse import urljoin

import requests
from url_normalize import url_normalize


class CanvasAPIError(Exception):
    """
    Raised when a Canvas API call fails.

    Attributes
    ----------
    message : str
        Human-readable description of the failure.
    status_code : int | None
        HTTP status code returned by Canvas, or None if no HTTP response was
        received (e.g. connection error, timeout).
    response_body : str | None
        Raw response body, truncated to 500 characters. None if no response
        was received.
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


def make_session(api_token: str) -> requests.Session:
    """
    Return a requests.Session pre-configured with the Canvas Bearer token.

    All public functions in this module accept a pre-built session so that
    the session lifetime is controlled by the caller (typically a Celery
    task). Callers may also use this helper directly when they need to make
    ad-hoc Canvas requests not covered by a higher-level function.
    """
    session = requests.Session()
    session.headers.update({"Authorization": "Bearer {token}".format(token=api_token)})
    return session


def build_api_url(api_root: str, path: str) -> str:
    """
    Join api_root with path and normalise the result.

    Uses urljoin + url_normalize, matching the pattern already used
    throughout canvas.py.

    Parameters
    ----------
    api_root : str
        Canvas base URL, e.g. "https://canvas.sussex.ac.uk/".
    path : str
        API path, e.g. "courses/123/assignments/456/submissions/789".
        Leading slash optional.
    """
    return url_normalize(urljoin(api_root, path))


def get_paginated(session: requests.Session, url: str, **kwargs) -> list | None:
    """
    GET a Canvas endpoint, following pagination via Link headers, and return
    the concatenated list of all response items.

    Returns None if the initial response is falsy (connection failure or
    non-OK status), matching the behaviour of the original _URL_query helper
    in canvas.py that this function replaces.

    Parameters
    ----------
    session : requests.Session
        Authenticated session from make_session().
    url : str
        Fully-qualified Canvas API URL.
    **kwargs
        Passed through to session.get() — use for query parameters, e.g.
        params={"enrollment_type": "student"}.
    """
    response = session.get(url, **kwargs)

    if not response:
        return None

    response_list = []
    finished = False

    while not finished:
        json = response.json()
        response_list = response_list + json

        links = response.links
        if "next" in links:
            next_dict = links["next"]
            if "url" in next_dict:
                response = session.get(next_dict["url"])
            else:
                finished = True
        else:
            finished = True

    return response_list


def fetch_submission(
    session: requests.Session,
    api_root: str,
    course_id: int,
    assignment_id: int,
    user_id: int,
    include: list[str] | None = None,
) -> dict:
    """
    GET a single Canvas submission object.

    Parameters
    ----------
    session : requests.Session
        Authenticated session from make_session().
    api_root : str
        Canvas base URL.
    course_id : int
        Canvas course (module) ID.
    assignment_id : int
        Canvas assignment ID.
    user_id : int
        Canvas user ID of the student.
    include : list[str] | None
        Optional list of associations to include, e.g. ["submission_history"].
        Each entry is sent as a separate include[] query parameter.

    Returns
    -------
    dict
        Parsed JSON response from Canvas.

    Raises
    ------
    CanvasAPIError
        If the request fails or Canvas returns a non-OK status.
    """
    url = build_api_url(
        api_root,
        "courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}".format(
            course_id=course_id,
            assignment_id=assignment_id,
            user_id=user_id,
        ),
    )

    kwargs = {}
    if include:
        kwargs["params"] = {"include[]": include}

    try:
        response = session.get(url, **kwargs)
    except requests.RequestException as e:
        raise CanvasAPIError("Canvas API request failed: {err}".format(err=e)) from e

    if not response.ok:
        raise CanvasAPIError(
            "Canvas API returned error status {code}".format(code=response.status_code),
            status_code=response.status_code,
            response_body=response.text[:500],
        )

    return response.json()


def extract_turnitin_data(submission: dict) -> dict:
    """
    Extract Turnitin similarity scores from a Canvas submission object.

    Returns a dict with keys:
        turnitin_outcome      : str | None
        similarity_score      : int | None
        web_overlap           : int | None
        publication_overlap   : int | None
        student_overlap       : int | None

    All values are None when no scored Turnitin data is present in the
    submission object.

    This function is pure data transformation — it raises no exceptions and
    makes no network calls.
    """
    result = {
        "turnitin_outcome": None,
        "similarity_score": None,
        "web_overlap": None,
        "publication_overlap": None,
        "student_overlap": None,
    }

    if "turnitin_data" in submission:
        turnitin_attachments = submission["turnitin_data"]
        if len(turnitin_attachments) >= 1:
            key = next(iter(turnitin_attachments))
            turnitin_data = turnitin_attachments[key]
            if turnitin_data.get("status") == "scored":
                result["similarity_score"] = turnitin_data.get("similarity_score")
                result["web_overlap"] = turnitin_data.get("web_overlap")
                result["publication_overlap"] = turnitin_data.get("publication_overlap")
                result["student_overlap"] = turnitin_data.get("student_overlap")
                result["turnitin_outcome"] = turnitin_data.get("state")

    return result


def upload_submission_comment_file(
    session: requests.Session,
    api_root: str,
    course_id: int,
    assignment_id: int,
    user_id: int,
    filename: str,
    file_bytes: bytes,
    content_type: str = "application/pdf",
) -> int:
    """
    Upload a file to a Canvas submission comment slot using the Canvas
    three-step file upload protocol. Returns the Canvas file ID on success.

    The returned ID can be passed as comment[file_ids][] in a subsequent
    grade PUT call.

    Parameters
    ----------
    session : requests.Session
        Authenticated session from make_session().
    api_root : str
        Canvas base URL.
    course_id : int
        Canvas course (module) ID.
    assignment_id : int
        Canvas assignment ID.
    user_id : int
        Canvas user ID of the student.
    filename : str
        Filename to register on Canvas, e.g. "feedback_harry_golding.pdf".
    file_bytes : bytes
        Raw file content.
    content_type : str
        MIME type; defaults to "application/pdf".

    Returns
    -------
    int
        Canvas file ID of the newly uploaded file.

    Raises
    ------
    CanvasAPIError
        If any step of the three-step upload fails.
    """
    notify_url = build_api_url(
        api_root,
        "courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}/files".format(
            course_id=course_id,
            assignment_id=assignment_id,
            user_id=user_id,
        ),
    )

    # Step 1 — notify Canvas
    try:
        notify_response = session.post(
            notify_url,
            json={"name": filename, "size": len(file_bytes), "content_type": content_type},
        )
    except requests.RequestException as e:
        raise CanvasAPIError("Canvas file upload step 1 failed: {err}".format(err=e)) from e

    if not notify_response.ok:
        raise CanvasAPIError(
            "Canvas file upload step 1 returned error status {code}".format(
                code=notify_response.status_code
            ),
            status_code=notify_response.status_code,
            response_body=notify_response.text[:500],
        )

    notify_data = notify_response.json()
    upload_url = notify_data["upload_url"]
    upload_params = notify_data["upload_params"]

    # Step 2 — upload to pre-signed URL as multipart/form-data
    # Fields must appear in order: upload_params first, then the file last
    fields = [(key, value) for key, value in upload_params.items()]
    fields.append(("file", (filename, file_bytes, content_type)))

    try:
        upload_response = session.post(upload_url, files=fields)
    except requests.RequestException as e:
        raise CanvasAPIError("Canvas file upload step 2 failed: {err}".format(err=e)) from e

    if upload_response.status_code == 201:
        file_id = upload_response.json()["id"]
    elif upload_response.is_redirect or upload_response.status_code in (301, 302, 303, 307, 308):
        location = upload_response.headers.get("Location")
        if not location:
            raise CanvasAPIError(
                "Canvas file upload step 2 returned redirect with no Location header",
                status_code=upload_response.status_code,
            )
        try:
            confirm_response = session.get(location)
        except requests.RequestException as e:
            raise CanvasAPIError(
                "Canvas file upload step 2 redirect follow failed: {err}".format(err=e)
            ) from e
        if not confirm_response.ok:
            raise CanvasAPIError(
                "Canvas file upload step 2 redirect target returned error {code}".format(
                    code=confirm_response.status_code
                ),
                status_code=confirm_response.status_code,
                response_body=confirm_response.text[:500],
            )
        file_id = confirm_response.json()["id"]
    else:
        raise CanvasAPIError(
            "Canvas file upload step 2 returned unexpected status {code}".format(
                code=upload_response.status_code
            ),
            status_code=upload_response.status_code,
            response_body=upload_response.text[:500],
        )

    return int(file_id)


def push_grade_to_canvas(
    session: requests.Session,
    api_root: str,
    course_id: int,
    assignment_id: int,
    user_id: int,
    posted_grade: float,
    file_ids: list[int] | None = None,
    text_comment: str | None = None,
) -> dict:
    """
    PUT a grade and optional comment/file attachments to a Canvas submission.

    Parameters
    ----------
    session : requests.Session
        Authenticated session from make_session().
    api_root : str
        Canvas base URL.
    course_id : int
        Canvas course (module) ID.
    assignment_id : int
        Canvas assignment ID.
    user_id : int
        Canvas user ID of the student.
    posted_grade : float
        Numeric grade to post.
    file_ids : list[int] | None
        Canvas file IDs to attach as comment attachments. Each is sent as a
        separate comment[file_ids][] field. Pass None or [] to omit.
    text_comment : str | None
        Optional plain-text comment. Pass None to omit.

    Returns
    -------
    dict
        Canvas submission object returned by the API.

    Raises
    ------
    CanvasAPIError
        If Canvas returns a non-2xx status code.
    """
    url = build_api_url(
        api_root,
        "courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}".format(
            course_id=course_id,
            assignment_id=assignment_id,
            user_id=user_id,
        ),
    )

    fields = [("submission[posted_grade]", str(round(posted_grade, 2)))]

    if text_comment is not None:
        fields.append(("comment[text_comment]", text_comment))

    if file_ids:
        for fid in file_ids:
            fields.append(("comment[file_ids][]", fid))

    try:
        response = session.put(url, data=fields)
    except requests.RequestException as e:
        raise CanvasAPIError("Canvas grade push failed: {err}".format(err=e)) from e

    if not response.ok:
        raise CanvasAPIError(
            "Canvas grade push returned error status {code}".format(code=response.status_code),
            status_code=response.status_code,
            response_body=response.text[:500],
        )

    return response.json()
