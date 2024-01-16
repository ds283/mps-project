#
# Created by David Seery on 06/10/2023.
# Copyright (c) 2023 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

import os

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305 as chacha_engine

from ..base import BytesLike, _as_bytes
from ..encryption_types import ENCRYPTION_CHACHA20_POLY1305


class ChaCha20_Poly1305:
    def __init__(self, key: BytesLike):
        if len(key) != 32:
            raise RuntimeError("ChaCha20_Poly1305 requires a 32-byte key")

        self._engine: chacha_engine = chacha_engine(key)

    @property
    def database_key(self) -> int:
        return ENCRYPTION_CHACHA20_POLY1305

    @property
    def uses_nonce(self) -> bool:
        return True

    def make_nonce(self) -> bytes:
        return os.urandom(12)

    def encrypt(self, nonce: bytes, data: BytesLike) -> bytes:
        if len(nonce) != 12:
            raise RuntimeError("ChaCha20_Poly1305 requires a 12-byte nonce")

        return self._engine.encrypt(nonce, _as_bytes(data), None)

    def decrypt(self, nonce: bytes, data: BytesLike) -> bytes:
        if len(nonce) != 12:
            raise RuntimeError("ChaCha20_Poly1305 requires a 12-byte nonce")

        return self._engine.decrypt(nonce, _as_bytes(data), None)
