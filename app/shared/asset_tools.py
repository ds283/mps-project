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


def make_generated_asset_filename(ext=None):
    """
    Generate a unique filename for a newly-generated asset
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    generated_subfolder = current_app.config.get('ASSETS_GENERATED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if generated_subfolder is None:
        raise RuntimeError('ASSETS_GENERATED_SUBFOLDER configuration variable is not set')

    if ext is not None:
        filename = '{leaf}.{ext}'.format(leaf=uuid4(), ext=ext)
    else:
        filename = '{leaf}'.format(leaf=uuid4())

    abs_generated_path = path.join(asset_folder, generated_subfolder)
    makedirs(abs_generated_path, exist_ok=True)

    return filename, path.join(abs_generated_path, filename)


def canonical_generated_asset_filename(filename):
    """
    Turn a unique filename for a generated asset into an absolute path
    :param filename:
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    generated_subfolder = current_app.config.get('ASSETS_GENERATED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if generated_subfolder is None:
        raise RuntimeError('ASSETS_GENERATED_SUBFOLDER configuration variable is not set')

    abs_generated_path = path.join(asset_folder, generated_subfolder)
    return path.join(abs_generated_path, filename)


def make_temporary_asset_filename(ext=None):
    """
    Generate a unique filename for an uploaded asset
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    uploaded_subfolder = current_app.config.get('ASSETS_UPLOADED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if uploaded_subfolder is None:
        raise RuntimeError('ASSETS_UPLOADED_SUBFOLDER configuration variable is not set')

    if ext is not None:
        filename = '{leaf}.{ext}'.format(leaf=uuid4(), ext=ext)
    else:
        filename = '{leaf}'.format(leaf=uuid4())

    abs_generated_path = path.join(asset_folder, uploaded_subfolder)
    makedirs(abs_generated_path, exist_ok=True)

    return filename, path.join(abs_generated_path, filename)


def canonical_temporary_asset_filename(filename):
    """
    Turn a unique filename for an temporary asset into an absolute path
    :param filename:
    :return:
    """
    asset_folder = current_app.config.get('ASSETS_FOLDER')
    uploaded_subfolder = current_app.config.get('ASSETS_UPLOADED_SUBFOLDER')

    if asset_folder is None:
        raise RuntimeError('ASSETS_FOLDER configuration variable is not set')
    if uploaded_subfolder is None:
        raise RuntimeError('ASSETS_UPLOADED_SUBFOLDER configuration variable is not set')

    abs_generated_path = path.join(asset_folder, uploaded_subfolder)
    return path.join(abs_generated_path, filename)