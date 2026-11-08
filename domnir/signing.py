"""Ed25519 signatures for offline-checkable provenance.

The server signs two kinds of statement:

* a **controller generation attestation**: "this server called Vultr
  inference with model M and received controller source with SHA-256 H", and
* a **mission Court Record seal**: the record's ``content_sha256``.

Anyone holding the server's public key can check both offline. What a valid
signature proves is that the holder of the signing key made the statement.
It does not prove the inference provider's behaviour independently: Vultr's
API responses are not signed, so the attestation is the server's claim.

Key management:
* ``DOMNIR_PROVENANCE_SIGNING_KEY``: base64 of a 32-byte Ed25519 private
  seed. Set it as a deployment secret so the key survives restarts and can
  be pinned by verifiers. Generate one with
  ``python -m domnir.signing generate-key``.
* Without it the server generates an **ephemeral** key at startup. Signatures
  still verify, but the key changes on every restart, so verifiers should not
  pin it. ``GET /provenance/keys`` reports ``ephemeral: true`` in that case.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import threading
from dataclasses import dataclass
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

def _canonical_json(payload: Any) -> bytes:
    from domnir.court_record import canonical_json
    return canonical_json(payload)

ALGORITHM = "Ed25519"
SIGNING_KEY_ENV = "DOMNIR_PROVENANCE_SIGNING_KEY"

AUTHENTIC = "AUTHENTIC"
SIGNED_UNTRUSTED_KEY = "SIGNED_UNTRUSTED_KEY"
INVALID_SIGNATURE = "INVALID_SIGNATURE"
UNSIGNED = "UNSIGNED"


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"), validate=True)


def public_key_bytes(key: Ed25519PublicKey) -> bytes:
    return key.public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id_for(public_raw: bytes) -> str:
    return hashlib.sha256(public_raw).hexdigest()[:16]


@dataclass(frozen=True)
class PublicKeyInfo:
    key_id: str
    public_key: str
    algorithm: str
    ephemeral: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "public_key": self.public_key,
            "algorithm": self.algorithm,
            "ephemeral": self.ephemeral,
        }


class ProvenanceSigner:
    def __init__(self, private_key: Ed25519PrivateKey, *, ephemeral: bool) -> None:
        self._private = private_key
        raw = public_key_bytes(private_key.public_key())
        self.info = PublicKeyInfo(key_id_for(raw), _b64(raw), ALGORITHM, ephemeral)

    @classmethod
    def from_env(cls) -> ProvenanceSigner:
        seed = os.environ.get(SIGNING_KEY_ENV, "").strip()
        if seed:
            raw = _unb64(seed)
            if len(raw) != 32:
                raise ValueError(f"{SIGNING_KEY_ENV} must be base64 of a 32-byte Ed25519 seed")
            return cls(Ed25519PrivateKey.from_private_bytes(raw), ephemeral=False)
        return cls(Ed25519PrivateKey.generate(), ephemeral=True)

    def sign(self, payload: Any) -> dict[str, Any]:
        message = _canonical_json(payload)
        return {
            "algorithm": ALGORITHM,
            "key_id": self.info.key_id,
            "public_key": self.info.public_key,
            "ephemeral_key": self.info.ephemeral,
            "payload_sha256": hashlib.sha256(message).hexdigest(),
            "signature": _b64(self._private.sign(message)),
        }


_signer: ProvenanceSigner | None = None
_signer_lock = threading.Lock()


def get_signer() -> ProvenanceSigner:
    global _signer
    with _signer_lock:
        if _signer is None:
            _signer = ProvenanceSigner.from_env()
        return _signer


def set_signer(signer: ProvenanceSigner | None) -> None:
    """Replace the process signer (tests and key rotation)."""
    global _signer
    with _signer_lock:
        _signer = signer


def parse_trusted_keys(values: Iterable[str]) -> dict[str, str]:
    """Accept base64 public keys, or JSON from ``GET /provenance/keys``.

    Returns ``{key_id: public_key_b64}``.
    """
    trusted: dict[str, str] = {}
    for value in values:
        value = value.strip()
        if not value:
            continue
        if value.startswith("{") or value.startswith("["):
            data = json.loads(value)
            entries = data.get("keys", [data]) if isinstance(data, dict) else data
            for entry in entries:
                raw = _unb64(entry["public_key"])
                trusted[key_id_for(raw)] = _b64(raw)
        else:
            raw = _unb64(value)
            if len(raw) != 32:
                raise ValueError("Trusted public key must be base64 of 32 raw Ed25519 bytes")
            trusted[key_id_for(raw)] = _b64(raw)
    return trusted


def check_signature(
    payload: Any,
    signature_block: Any,
    trusted_keys: dict[str, str] | None,
) -> tuple[str, str]:
    """Return ``(authenticity, reason)`` for a signed payload.

    The signature is checked against the public key embedded in the block,
    and the block's key must hash to its ``key_id``. Authenticity is
    ``AUTHENTIC`` only if that key is also in ``trusted_keys``; a valid
    signature under any other key is ``SIGNED_UNTRUSTED_KEY``, because anyone
    can sign with a key of their own.
    """
    if not signature_block:
        return UNSIGNED, "No signature present"
    if not isinstance(signature_block, dict) or signature_block.get("algorithm") != ALGORITHM:
        return INVALID_SIGNATURE, "Unsupported or malformed signature block"
    try:
        public_raw = _unb64(signature_block["public_key"])
        signature = _unb64(signature_block["signature"])
        if key_id_for(public_raw) != signature_block.get("key_id"):
            return INVALID_SIGNATURE, "key_id does not match the embedded public key"
        message = _canonical_json(payload)
        if hashlib.sha256(message).hexdigest() != signature_block.get("payload_sha256"):
            return INVALID_SIGNATURE, "Signed payload hash does not match the payload"
        Ed25519PublicKey.from_public_bytes(public_raw).verify(signature, message)
    except (KeyError, TypeError, ValueError, InvalidSignature) as exc:
        return INVALID_SIGNATURE, f"Signature does not verify ({type(exc).__name__})"
    key_id = signature_block["key_id"]
    if trusted_keys and trusted_keys.get(key_id) == signature_block["public_key"]:
        return AUTHENTIC, f"Valid signature by trusted key {key_id}"
    return SIGNED_UNTRUSTED_KEY, f"Valid signature by key {key_id}, which is not in the trusted key set"


def _main(argv: list[str]) -> int:
    if argv[:1] != ["generate-key"]:
        print("usage: python -m domnir.signing generate-key", file=sys.stderr)
        return 2
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes_raw()
    raw_pub = public_key_bytes(key.public_key())
    print(f"{SIGNING_KEY_ENV}={_b64(seed)}")
    print(f"public_key={_b64(raw_pub)}")
    print(f"key_id={key_id_for(raw_pub)}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
