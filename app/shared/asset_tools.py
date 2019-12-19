#
# Created by David Seery on 17/12/2019.
# Copyright (c) 2019 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

from os import path, makedirs
from uuid import uuid4

from flask import current_app

from pathlib import Path


def _make_asset_filename(asset_folder=None, subfolder=None, ext=None):
    """
    Generate a unique filename for an asset
    """
    if asset_folder is None:
        raise RuntimeError('asset folder not specified in _make_asset_filename')
    if subfolder is None:
        raise RuntimeError('subfolder not specified in _make_asset_filename')

    if ext is not None:
        if not ext.startswith('.'):
            ext = "." + ext
        filename = Path(str(uuid4())).with_suffix(ext)
    else:
        filename = Path(str(uuid4()))

    if not isinstance(asset_folder, Path):
        asset_folder = Path(asset_folder)
    if not isinstance(subfolder, Path):
        subfolder = Path(subfolder)

    # make sure destination folder exists
    destination = asset_folder / subfolder
    destination.mkdir(parents=True, exist_ok=True)

    return filename, destination/filename


def _make_canonical_asset_filename(filename, asset_folder=None, subfolder=None):
    """
    Turn a relative asset filename into an absolute path
    """
    if asset_folder is None:
        raise RuntimeError('asset folder not specified in _make_canonical_asset_filename')
    if subfolder is None:
        raise RuntimeError('subfolder not specified in _make_canonical_asset_filename')

    if not isinstance(filename, Path):
        filename = Path(filename)
    if not isinstance(asset_folder, Path):
        asset_folder = Path(asset_folder)
    if not isinstance(subfolder, Path):
        subfolder = Path(subfolder)

    return asset_folder / subfolder / filename


def make_generated_asset_filename(ext=None):
    """
    Generate a unique filename for a newly-generated asset
    :return:
    """
    return _make_asset_filename(asset_folder=current_app.config.get('ASSETS_FOLDER'),
                                subfolder=current_app.config.get('ASSETS_GENERATED_SUBFOLDER'), ext=ext)


def canonical_generated_asset_filename(filename):
    """
    Turn a unique filename for a generated asset into an absolute path
    :param filename:
    :return:
    """
    return _make_canonical_asset_filename(filename, asset_folder=current_app.config.get('ASSETS_FOLDER'),
                                          subfolder=current_app.config.get('ASSETS_GENERATED_SUBFOLDER'))


def make_temporary_asset_filename(ext=None):
    """
    Generate a unique filename for an uploaded asset
    :return:
    """
    return _make_asset_filename(asset_folder=current_app.config.get('ASSETS_FOLDER'),
                                subfolder=current_app.config.get('ASSETS_UPLOADED_SUBFOLDER'), ext=ext)


def canonical_temporary_asset_filename(filename):
    """
    Turn a unique filename for an temporary asset into an absolute path
    :param filename:
    :return:
    """
    return _make_canonical_asset_filename(filename, asset_folder=current_app.config.get('ASSETS_FOLDER'),
                                          subfolder=current_app.config.get('ASSETS_UPLOADED_SUBFOLDER'))


def make_submitted_asset_filename(ext=None, subpath=None):
    """
    Generate a unique filename for a submitted asset
    """
    if not isinstance(subpath, Path):
        subpath = Path(subpath)

    name, path = _make_asset_filename(asset_folder=current_app.config.get('ASSETS_FOLDER'),
                                      subfolder=Path(current_app.config.get('ASSETS_SUBMITTED_SUBFOLDER') / subpath),
                                      ext=ext)

    return name, path


def canonical_submitted_asset_filename(filename):
    """
    Turn a unique filename for a submitted asset into an absolute path
    """
    return _make_canonical_asset_filename(filename, asset_folder=current_app.config.get('ASSETS_FOLDER'),
                                          subfolder=current_app.config.get('ASSETS_SUBMITTED_SUBFOLDER'))
