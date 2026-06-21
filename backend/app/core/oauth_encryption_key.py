from __future__ import annotations

import hashlib
import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

OAUTH_TOKEN_ENCRYPTION_KEY_ENV = "OAUTH_TOKEN_ENCRYPTION_KEY"


def validate_oauth_encryption_key() -> dict[str, object]:
    """Validate the shared OAuth token Fernet key without logging secret material."""
    raw_key = os.getenv(OAUTH_TOKEN_ENCRYPTION_KEY_ENV)
    if raw_key is None:
        reason = "missing"
        logger.error("event=oauth_encryption_key_invalid reason=%s", reason)
        raise RuntimeError(f"{OAUTH_TOKEN_ENCRYPTION_KEY_ENV} is required")

    key = raw_key.strip()
    key_length = len(key)
    if not key:
        reason = "empty"
        logger.error("event=oauth_encryption_key_invalid reason=%s key_length=%s", reason, key_length)
        raise RuntimeError(f"{OAUTH_TOKEN_ENCRYPTION_KEY_ENV} must not be empty")

    try:
        Fernet(key.encode("utf-8"))
    except Exception as exc:
        reason = type(exc).__name__
        logger.error("event=oauth_encryption_key_invalid reason=%s key_length=%s", reason, key_length)
        raise RuntimeError(f"{OAUTH_TOKEN_ENCRYPTION_KEY_ENV} must be a valid Fernet key") from exc

    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    logger.info(
        "event=oauth_encryption_key_verified fingerprint=%s key_length=%s valid=true",
        fingerprint,
        key_length,
    )
    return {"fingerprint": fingerprint, "valid": True}
