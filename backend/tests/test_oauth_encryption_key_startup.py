import hashlib
import logging

import pytest
from cryptography.fernet import Fernet

from app.core.oauth_encryption_key import validate_oauth_encryption_key


def _valid_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_validate_oauth_encryption_key_accepts_valid_fernet_key(monkeypatch, caplog):
    key = _valid_key()
    expected_fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", key)

    with caplog.at_level(logging.INFO):
        result = validate_oauth_encryption_key()

    assert result == {"fingerprint": expected_fingerprint, "valid": True}
    assert "event=oauth_encryption_key_verified" in caplog.text
    assert f"fingerprint={expected_fingerprint}" in caplog.text
    assert "key_length=44" in caplog.text
    assert "valid=true" in caplog.text
    assert key not in caplog.text


def test_validate_oauth_encryption_key_rejects_missing_key(monkeypatch, caplog):
    monkeypatch.delenv("OAUTH_TOKEN_ENCRYPTION_KEY", raising=False)

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="required"):
        validate_oauth_encryption_key()

    assert "event=oauth_encryption_key_invalid" in caplog.text
    assert "reason=missing" in caplog.text


def test_validate_oauth_encryption_key_rejects_empty_key(monkeypatch, caplog):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "   ")

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="must not be empty"):
        validate_oauth_encryption_key()

    assert "event=oauth_encryption_key_invalid" in caplog.text
    assert "reason=empty" in caplog.text
    assert "key_length=0" in caplog.text


def test_validate_oauth_encryption_key_rejects_invalid_key_without_leaking_value(monkeypatch, caplog):
    invalid_key = "integration-test-secret"
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", invalid_key)

    with caplog.at_level(logging.ERROR), pytest.raises(RuntimeError, match="valid Fernet key"):
        validate_oauth_encryption_key()

    assert "event=oauth_encryption_key_invalid" in caplog.text
    assert "reason=ValueError" in caplog.text
    assert f"key_length={len(invalid_key)}" in caplog.text
    assert invalid_key not in caplog.text


def test_rq_worker_startup_fails_before_database_when_oauth_key_invalid(monkeypatch):
    database_checked = False

    def fake_wait_for_database():
        nonlocal database_checked
        database_checked = True

    try:
        import worker_rq
    except BaseException as exc:
        pytest.skip(f"worker startup import unavailable in this environment: {exc}")

    monkeypatch.setenv("DATABASE_URL", "postgresql://example")
    monkeypatch.setenv("REDIS_URL", "redis://example")
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
    monkeypatch.setattr(worker_rq, "verify_required_dependencies", lambda required: None)
    monkeypatch.setattr(worker_rq, "verify_runtime_secrets", lambda: None)
    monkeypatch.setattr(worker_rq, "wait_for_database", fake_wait_for_database)

    with pytest.raises(RuntimeError, match="valid Fernet key"):
        worker_rq.run_startup_checks()

    assert database_checked is False
