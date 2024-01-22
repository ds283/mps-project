#
# Created by David Seery on 02/08/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# from io import BytesIO
# from uuid import uuid4

# from object_store import ObjectStore

from app import create_app

# from app.models import SubmittedAsset, GeneratedAsset, TemporaryAsset
# from app.shared.asset_tools import canonical_submitted_asset_filename, canonical_generated_asset_filename, \
#     canonical_temporary_asset_filename


# def migrate_object_storage(AssetModel, canonicalize):
#     storage: ObjectStore = app.config['OBJECT_STORAGE_ASSETS']
#
#     assets = db.session.query(AssetModel).all()
#
#     for asset in assets:
#         # generate a new UUID for this asset; the UUID will become the unique identifier within
#         # our storage bucket
#         asset.unique_name = str(uuid4())
#
#         filename = canonicalize(asset.filename)
#         with open(filename, 'rb') as f:
#             storage.put(asset.unique_name, BytesIO(f.read()))
#
#     db.session.commit()


app = create_app()

# with app.app_context():
#     def make_canonical_submitted(name):
#         return canonical_submitted_asset_filename(name, root_folder='ASSETS_SUBMITTED_SUBFOLDER')
#
#     def make_canonical_generated(name):
#         return canonical_generated_asset_filename(name)
#
#     def make_canonical_temporary(name):
#         return canonical_temporary_asset_filename(name)
#
#     migrate_object_storage(SubmittedAsset, make_canonical_submitted)
#     migrate_object_storage(GeneratedAsset, make_canonical_generated)
#     migrate_object_storage(TemporaryAsset, make_canonical_temporary)
