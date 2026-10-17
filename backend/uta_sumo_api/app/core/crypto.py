"""Authenticated application-level encryption for personal/free-text fields."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import PII_ENCRYPTION_KEY

_PREFIX = "enc:v1:"
_AAD = b"uta-sumo-pii:v1"


@lru_cache(maxsize=1)
def _key() -> bytes:
    try:
        value = base64.urlsafe_b64decode(PII_ENCRYPTION_KEY + "=" * (-len(PII_ENCRYPTION_KEY) % 4))
    except Exception as exc:
        raise RuntimeError("PII_ENCRYPTION_KEY debe ser base64url de 32 bytes.") from exc
    if len(value) != 32:
        raise RuntimeError("PII_ENCRYPTION_KEY debe ser base64url de 32 bytes.")
    return value


def encrypt_text(value: str | None) -> str | None:
    if value is None or value.startswith(_PREFIX):
        return value
    nonce = os.urandom(12)
    encrypted = AESGCM(_key()).encrypt(nonce, value.encode("utf-8"), _AAD)
    encoded = base64.urlsafe_b64encode(nonce + encrypted).decode("ascii").rstrip("=")
    return _PREFIX + encoded


def decrypt_text(value: str | None) -> str | None:
    if value is None or not value.startswith(_PREFIX):
        return value
    raw = value[len(_PREFIX):]
    packed = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    return AESGCM(_key()).decrypt(packed[:12], packed[12:], _AAD).decode("utf-8")


def is_encrypted(value: str | None) -> bool:
    return value is None or value.startswith(_PREFIX)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def email_lookup_hash(email: str) -> str:
    # Derive a distinct keyed index from the encryption key to prevent offline
    # dictionary attacks against common email addresses in database dumps.
    key = hmac.new(_key(), b"uta-sumo-email-index:v1", hashlib.sha256).digest()
    return hmac.new(key, normalize_email(email).encode("utf-8"), hashlib.sha256).hexdigest()


def encrypt_bytes(value: bytes) -> bytes:
    nonce = os.urandom(12)
    return b"UTAENC1" + nonce + AESGCM(_key()).encrypt(nonce, value, _AAD)


def decrypt_bytes(value: bytes) -> bytes:
    if not value.startswith(b"UTAENC1"):
        return value
    nonce = value[7:19]
    return AESGCM(_key()).decrypt(nonce, value[19:], _AAD)
