"""Ed25519 trust roots for fail-closed ARCHEON plugin packages."""

from __future__ import annotations

import base64
import binascii
import re
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key


_PUBLISHER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,63}$")


class TrustedPublisherVerifier:
    """Verify a manifest against a locally provisioned publisher public key."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory.resolve()

    @property
    def configured(self) -> bool:
        return self.directory.is_dir() and any(self.directory.glob("*.pem"))

    def __call__(self, payload: bytes, signature: str, publisher: str) -> bool:
        if not _PUBLISHER.fullmatch(publisher):
            return False
        key_path = (self.directory / f"{publisher}.pem").resolve()
        if key_path.parent != self.directory or not key_path.is_file() or key_path.stat().st_size > 16_384:
            return False
        try:
            encoded = base64.b64decode(signature, validate=True)
            public_key = load_pem_public_key(key_path.read_bytes())
            if not isinstance(public_key, Ed25519PublicKey):
                return False
            public_key.verify(encoded, payload)
        except (OSError, ValueError, TypeError, binascii.Error, InvalidSignature):
            return False
        return True
