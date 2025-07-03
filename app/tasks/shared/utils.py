#
# Created by ds283 on 03/07/2025.
# Copyright (c) 2025 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: ds283 <>
#
from typing import Optional, Union
from urllib.parse import quote

from ...models import User, SubmittedAsset, GeneratedAsset
from flask_mailman import EmailMessage

from ...shared.asset_tools import AssetCloudAdapter


def report_error(msg: str, source: str, user: Optional[User]):
    print(f"!! {source}: {msg}")
    if user is not None:
        user.post_message(msg, "error", autocommit=True)


def report_info(msg: str, source: str, user: Optional[User]):
    print(f">> {source}: {msg}")
    if user is not None:
        user.post_message(msg, "info", autocommit=True)


def attach_asset_to_email_msg(
    msg: EmailMessage,
    storage: AssetCloudAdapter,
    current_size: int,
    attached_documents,
    filename=None,
    max_attached_size=None,
    description=None,
    endpoint="download_submitted_asset",
):
    if not storage.exists():
        raise RuntimeError("_attach_documents() could not find asset in object store")

    # get size of file to be attached, in bytes
    asset: Union[SubmittedAsset, GeneratedAsset] = storage.record()
    asset_size = asset.filesize

    # if attachment is too large, generate a link instead
    if max_attached_size is not None and float(current_size + asset_size) / (1024 * 1024) > max_attached_size:
        if filename is not None:
            try:
                link = "https://mpsprojects.sussex.ac.uk/admin/{endpoint}/{asset_id}?filename={fnam}".format(
                    endpoint=endpoint, asset_id=asset.id, fnam=quote(filename)
                )
            except TypeError as e:
                link = "https://mpsprojects.sussex.ac.uk/admin/{endpoint}/{asset_id}".format(endpoint=endpoint, asset_id=asset.id)
                print(f'attach_asset_to_email_msg: TypeError received with filename="{filename}"')
        else:
            link = "https://mpsprojects.sussex.ac.uk/admin/{endpoint}/{asset_id}".format(endpoint=endpoint, asset_id=asset.id)
        attached_documents.append((False, link, description))
        asset_size = 0

    # otherwise, perform the attachment
    else:
        attached_name = (
            str(filename) if filename is not None else str(asset.target_name) if asset.target_name is not None else str(asset.unique_name)
        )

        msg.attach(filename=attached_name, mimetype=asset.mimetype, content=storage.get())

        attached_documents.append((True, attached_name, description))

    return asset_size
