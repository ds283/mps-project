#
# Created by David Seery on 08/05/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from datetime import datetime
from typing import Optional, Union

from sqlalchemy.ext.declarative import declared_attr

from ..database import db
from ..shared.sqlalchemy import get_count
from .associations import (
    generated_acl,
    generated_acr,
    submitted_acl,
    submitted_acr,
    temporary_acl,
    temporary_acr,
)
from .defaults import DEFAULT_STRING_LENGTH
from .model_mixins import (
    AssetDownloadDataMixin,
    AssetExpiryMixin,
    BaseAssetMixin,
    InstrumentedAssetMixinFactory,
)
from .users import User


class TemporaryAsset(
    db.Model,
    AssetExpiryMixin,
    InstrumentedAssetMixinFactory(temporary_acl, temporary_acr),
):
    """
    Track temporary uploaded assets
    """

    __tablename__ = "temporary_assets"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    @classmethod
    def get_type(cls):
        return "TemporaryAsset"


class ThumbnailAsset(
    db.Model,
    BaseAssetMixin,
):
    """
    Track an asset that is a thumbnail of a SubmittedAsset or GeneratedAsset
    """

    __tablename__ = "thumbnail_assets"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)


class AssetThumbnailMixin:
    # (optional) thumbnail asset at small 200x200 size; if None, no thumbnail exists
    small_thumbnail_id = db.Column(
        db.Integer(), db.ForeignKey("thumbnail_assets.id"), default=None
    )

    @declared_attr
    def small_thumbnail(cls):
        return db.relationship(
            "ThumbnailAsset",
            foreign_keys=[cls.small_thumbnail_id],
        )

    # (optional) thumbnail asset at medium 400x400 size; if None, no thumbnail exists
    medium_thumbnail_id = db.Column(
        db.Integer(), db.ForeignKey("thumbnail_assets.id"), default=None
    )

    @declared_attr
    def medium_thumbnail(cls):
        return db.relationship(
            "ThumbnailAsset",
            foreign_keys=[cls.medium_thumbnail_id],
        )

    # thumbnail error state
    # set by background task that generates the thumbnails; if an error condition exists, then this prevents repeated attempts to generate the
    # thumbnail
    thumbnail_error = db.Column(db.Boolean(), default=False, nullable=False)

    # thumbnail error message
    thumbnail_error_message = db.Column(
        db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin")
    )

    # could consider setting an explicit timestamp, but that is really captured by the ThumbnailAsset timestamp


class GeneratedAsset(
    db.Model,
    AssetExpiryMixin,
    AssetDownloadDataMixin,
    InstrumentedAssetMixinFactory(generated_acl, generated_acr),
    AssetThumbnailMixin,
):
    """
    Track generated assets
    """

    __tablename__ = "generated_assets"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # optional link to SubmittedAsset from which this asset was generated
    parent_asset_id = db.Column(
        db.Integer(), db.ForeignKey("submitted_assets.id"), default=None
    )
    parent_asset = db.relationship(
        "SubmittedAsset",
        foreign_keys=[parent_asset_id],
        uselist=False,
        backref=db.backref("generated_assets", lazy="dynamic"),
    )

    # optional license applied to this asset
    license_id = db.Column(
        db.Integer(), db.ForeignKey("asset_licenses.id"), default=None
    )
    license = db.relationship(
        "AssetLicense",
        foreign_keys=[license_id],
        uselist=False,
        backref=db.backref("generated_assets", lazy="dynamic"),
    )

    @classmethod
    def get_type(cls):
        return "GeneratedAsset"

    @property
    def number_downloads(self):
        # 'downloads' data member provided by back reference from GeneratedAssetDownloadRecord
        return get_count(self.downloads)

    @property
    def verb_label(self):
        return "generated"


class SubmittedAsset(
    db.Model,
    AssetExpiryMixin,
    AssetDownloadDataMixin,
    InstrumentedAssetMixinFactory(submitted_acl, submitted_acr),
    AssetThumbnailMixin,
):
    """
    Track submitted assets: these may be uploaded project reports, but they can be other things too,
    such as attachments
    """

    __tablename__ = "submitted_assets"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # report uploaded by
    uploaded_id = db.Column(db.Integer(), db.ForeignKey("users.id"), default=None)
    uploaded_by = db.relationship(
        "User",
        foreign_keys=[uploaded_id],
        uselist=False,
        backref=db.backref("uploaded_assets", lazy="dynamic"),
    )

    # (optional) license applied to this asset
    license_id = db.Column(
        db.Integer(), db.ForeignKey("asset_licenses.id"), default=None
    )
    license = db.relationship(
        "AssetLicense",
        foreign_keys=[license_id],
        uselist=False,
        backref=db.backref("submitted_assets", lazy="dynamic"),
    )

    @classmethod
    def get_type(cls):
        return "SubmittedAsset"

    @property
    def number_downloads(self):
        # 'downloads' data member provided by back reference from SubmittedAssetDownloadRecord
        return get_count(self.downloads)

    @property
    def verb_label(self):
        return "uploaded"


class SubmittedAssetDownloadRecord(db.Model):
    """
    Serves as a log of downloads for a particular SubmittedAsset
    """

    __tablename__ = "submitted_downloads"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # asset downloaded
    asset_id = db.Column(
        db.Integer(), db.ForeignKey("submitted_assets.id"), default=None
    )
    asset = db.relationship(
        "SubmittedAsset",
        foreign_keys=[asset_id],
        uselist=False,
        backref=db.backref("downloads", lazy="dynamic"),
    )

    # downloaded by
    downloader_id = db.Column(db.Integer(), db.ForeignKey("users.id"), default=None)
    downloader = db.relationship(
        "User",
        foreign_keys=[downloader_id],
        uselist=False,
        backref=db.backref("submitted_downloads", lazy="dynamic"),
    )

    # download time
    timestamp = db.Column(db.DateTime(), index=True)


class GeneratedAssetDownloadRecord(db.Model):
    """
    Serves as a log of downloads for a particular SubmittedAsset
    """

    __tablename__ = "generated_downloads"

    # primary key id
    id = db.Column(db.Integer(), primary_key=True)

    # asset downloaded
    asset_id = db.Column(
        db.Integer(), db.ForeignKey("generated_assets.id"), default=None
    )
    asset = db.relationship(
        "GeneratedAsset",
        foreign_keys=[asset_id],
        uselist=False,
        backref=db.backref("downloads", lazy="dynamic"),
    )

    # downloaded by
    downloader_id = db.Column(db.Integer(), db.ForeignKey("users.id"), default=None)
    downloader = db.relationship(
        "User",
        foreign_keys=[downloader_id],
        uselist=False,
        backref=db.backref("generated_downloads", lazy="dynamic"),
    )

    # download time
    timestamp = db.Column(db.DateTime(), index=True)


class DownloadCentreItem(db.Model):
    """
    Model an element in a user's download centre
    """

    __tablename__ = "download_centre_item"

    # primary key ids
    id = db.Column(db.Integer(), primary_key=True)

    # user id
    user_id = db.Column(db.Integer(), db.ForeignKey("users.id"), default=None)
    user = db.relationship(
        "User",
        foreign_keys=[user_id],
        backref=db.backref("download_centre_items", lazy="dynamic"),
    )

    # generated asset item
    asset_id = db.Column(
        db.Integer(), db.ForeignKey("generated_assets.id"), default=None
    )
    asset = db.relationship(
        "GeneratedAsset",
        foreign_keys=[asset_id],
        uselist=False,
        backref=db.backref("download_centre_items", lazy="dynamic"),
    )

    # generated time
    generated_at = db.Column(db.DateTime(), index=True, default=None)

    # last downloaded time
    last_downloaded_at = db.Column(db.DateTime(), index=True, default=None)

    # expiry time (optional)
    expire_at = db.Column(db.DateTime(), index=True, default=None)

    # total number of downloads
    number_downloads = db.Column(db.Integer(), default=0)

    # text description
    description = db.Column(db.String(DEFAULT_STRING_LENGTH, collation="utf8_bin"))

    @classmethod
    def _build(
        cls,
        asset: GeneratedAsset,
        user: Union[int, User],
        description: Optional[str] = None,
    ):
        if asset is None:
            raise RuntimeError(f"asset must not be None in DownloadCentreItem._build")

        if user is None:
            raise RuntimeError(f"user must not be None in DownloadCentreItem._build")

        user_id: int
        if isinstance(user, int):
            user_id = user
        elif isinstance(user, User):
            user_id = user.id

        return cls(
            user_id=user_id,
            asset_id=asset.id,
            generated_at=datetime.now(),
            last_downloaded_at=None,
            expire_at=asset.expiry,
            number_downloads=0,
            description=description,
        )
