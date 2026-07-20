#
# Created by David Seery on 22/06/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Provider registry — maps provider name strings to CloudStorageProvider subclasses.
Import get_provider_class() to resolve a name at runtime.
"""

from typing import Dict, Type

from .base import CloudStorageProvider

# Populated below once the concrete providers are imported.
_providers: Dict[str, Type[CloudStorageProvider]] = {}


def register_provider(name: str, cls: Type[CloudStorageProvider]) -> None:
    _providers[name] = cls


def get_provider_class(name: str) -> Type[CloudStorageProvider]:
    if name not in _providers:
        available = ", ".join(sorted(_providers.keys())) or "(none)"
        raise KeyError(f"cloud_storage: unknown provider '{name}'. Registered providers: {available}")
    return _providers[name]


# ---------------------------------------------------------------------------
# Register built-in providers
# ---------------------------------------------------------------------------

from .providers.box import BoxCloudStorageProvider  # noqa: E402

register_provider("box", BoxCloudStorageProvider)
