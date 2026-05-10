import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

_PREFIX = "enc:v1:"


def _get_fernet() -> Fernet:
    raw_key = (os.getenv("WHATSAPP_SECRET_ENCRYPTION_KEY", "") or "").strip()
    if not raw_key:
        raise ValueError("WHATSAPP_SECRET_ENCRYPTION_KEY não configurada")

    try:
        key_bytes = raw_key.encode("utf-8")
        if len(raw_key) == 44:
            return Fernet(key_bytes)
    except Exception:
        pass

    digest = hashlib.sha256(raw_key.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    plain = value.strip()
    if not plain:
        return None
    if plain.startswith(_PREFIX):
        return plain
    token = _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: str | None) -> str | None:
    if value is None:
        return None
    item = value.strip()
    if not item:
        return None
    if not item.startswith(_PREFIX):
        return item

    encrypted = item[len(_PREFIX) :]
    try:
        return _get_fernet().decrypt(encrypted.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None
