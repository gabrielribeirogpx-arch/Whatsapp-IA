from __future__ import annotations

import inspect
from uuid import UUID

import pytest

from app.core.external_identity import (
    APPOINTMENT_PATIENT,
    ExternalIdentitySecretError,
    ExternalReferenceVersion,
    InvalidExternalReferenceError,
    derive_external_reference,
    is_valid_external_reference,
    parse_external_reference,
)

TENANT_A = UUID("10000000-0000-4000-8000-000000000001")
TENANT_B = UUID("10000000-0000-4000-8000-000000000002")
CONTACT_A = UUID("20000000-0000-4000-8000-000000000001")
CONTACT_B = UUID("20000000-0000-4000-8000-000000000002")
SECRET_A = "a" * 32
SECRET_B = "b" * 32


@pytest.fixture(autouse=True)
def external_identity_secret(monkeypatch):
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", SECRET_A)


def derive(*, tenant_id=TENANT_A, subject_id=CONTACT_A, purpose=APPOINTMENT_PATIENT):
    return derive_external_reference(
        tenant_id=tenant_id, subject_id=subject_id, purpose=purpose
    )


def test_derivation_is_deterministic():
    assert derive() == derive()


def test_derivation_is_tenant_bound():
    assert derive(tenant_id=TENANT_A) != derive(tenant_id=TENANT_B)


def test_derivation_is_subject_bound():
    assert derive(subject_id=CONTACT_A) != derive(subject_id=CONTACT_B)


def test_derivation_is_purpose_bound():
    assert derive() != derive(purpose="crm_customer")


def test_reference_does_not_expose_internal_identifiers():
    reference = derive()
    assert str(TENANT_A) not in reference
    assert str(CONTACT_A) not in reference


def test_derivation_is_secret_bound(monkeypatch):
    first = derive()
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", SECRET_B)
    assert derive() != first


@pytest.mark.parametrize("secret", [None, "", "short-secret"])
def test_derivation_fails_closed_without_strong_dedicated_secret(monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("EXTERNAL_IDENTITY_SECRET", raising=False)
    else:
        monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", secret)
    with pytest.raises(ExternalIdentitySecretError, match="EXTERNAL_IDENTITY_SECRET"):
        derive()


def test_reference_carries_a_parseable_version():
    reference = derive()
    parsed = parse_external_reference(reference)
    assert reference.startswith("asa:v1:")
    assert parsed.version is ExternalReferenceVersion.V1
    assert is_valid_external_reference(reference)


@pytest.mark.parametrize(
    "reference",
    [None, "", "v1:value", "asa:v2:" + "a" * 43, "asa:v1:short", "asa:v1:" + "!" * 43],
)
def test_parser_rejects_invalid_or_unsupported_references(reference):
    with pytest.raises(InvalidExternalReferenceError):
        parse_external_reference(reference)
    assert not is_valid_external_reference(reference)


def test_api_excludes_operational_context_and_pii():
    assert set(inspect.signature(derive_external_reference).parameters) == {
        "tenant_id",
        "subject_id",
        "purpose",
    }


@pytest.mark.parametrize("field", ["tenant_id", "subject_id"])
def test_derivation_rejects_non_uuid_identifiers(field):
    arguments = {"tenant_id": TENANT_A, "subject_id": CONTACT_A, "purpose": APPOINTMENT_PATIENT}
    arguments[field] = "not-a-uuid"
    with pytest.raises(ValueError, match=field):
        derive_external_reference(**arguments)


@pytest.mark.parametrize("purpose", ["", "UPPER_CASE", "has-hyphen", "ab"])
def test_derivation_rejects_invalid_purpose(purpose):
    with pytest.raises(ValueError, match="purpose"):
        derive(purpose=purpose)
