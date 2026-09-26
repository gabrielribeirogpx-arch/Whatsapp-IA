"""Opaque, stable references for identities persisted in external systems."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

APPOINTMENT_PATIENT = "appointment_patient"

_NAMESPACE = "asa"
_PURPOSE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,63}$")
_DIGEST_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
_MINIMUM_SECRET_BYTES = 32


class ExternalReferenceError(ValueError):
    """Base error for external-reference configuration and input failures."""


class ExternalIdentitySecretError(ExternalReferenceError):
    """The dedicated derivation secret is absent or too weak."""


class InvalidExternalReferenceError(ExternalReferenceError):
    """A value is not a supported canonical external reference."""


class ExternalReferenceVersion(str, Enum):
    V1 = "v1"


@dataclass(frozen=True)
class ParsedExternalReference:
    version: ExternalReferenceVersion
    opaque_value: str


def _uuid(value: UUID | str, *, field: str) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ExternalReferenceError(f"{field} must be a valid UUID") from exc


def _purpose(value: str) -> str:
    if not isinstance(value, str) or not _PURPOSE_PATTERN.fullmatch(value):
        raise ExternalReferenceError(
            "purpose must be 3-64 lowercase ASCII letters, digits, or underscores"
        )
    return value


def _secret() -> bytes:
    # Read lazily: deployments which do not derive external identities remain
    # compatible, while the operation itself always fails closed.
    value = os.getenv("EXTERNAL_IDENTITY_SECRET", "")
    encoded = value.encode("utf-8")
    if not value.strip():
        raise ExternalIdentitySecretError("EXTERNAL_IDENTITY_SECRET is not configured")
    if len(encoded) < _MINIMUM_SECRET_BYTES:
        raise ExternalIdentitySecretError(
            f"EXTERNAL_IDENTITY_SECRET must contain at least {_MINIMUM_SECRET_BYTES} bytes"
        )
    return encoded


def derive_external_reference(
    *, tenant_id: UUID | str, subject_id: UUID | str, purpose: str
) -> str:
    """Derive a versioned HMAC reference without exposing either internal UUID."""
    version = ExternalReferenceVersion.V1
    canonical_message = json.dumps(
        {
            "namespace": _NAMESPACE,
            "purpose": _purpose(purpose),
            "subject_id": str(_uuid(subject_id, field="subject_id")),
            "tenant_id": str(_uuid(tenant_id, field="tenant_id")),
            "version": version.value,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    digest = hmac.new(_secret(), canonical_message, hashlib.sha256).digest()
    opaque_value = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return f"{_NAMESPACE}:{version.value}:{opaque_value}"


def parse_external_reference(reference: str) -> ParsedExternalReference:
    """Validate a reference and return its recognized version and opaque value."""
    if not isinstance(reference, str):
        raise InvalidExternalReferenceError("external reference must be a string")
    parts = reference.split(":")
    if len(parts) != 3 or parts[0] != _NAMESPACE:
        raise InvalidExternalReferenceError("invalid external reference format")
    try:
        version = ExternalReferenceVersion(parts[1])
    except ValueError as exc:
        raise InvalidExternalReferenceError("unsupported external reference version") from exc
    opaque_value = parts[2]
    if not _DIGEST_PATTERN.fullmatch(opaque_value):
        raise InvalidExternalReferenceError("invalid external reference digest")
    return ParsedExternalReference(version=version, opaque_value=opaque_value)


def is_valid_external_reference(reference: object) -> bool:
    """Return whether a value has a supported canonical reference format."""
    try:
        parse_external_reference(reference)  # type: ignore[arg-type]
    except InvalidExternalReferenceError:
        return False
    return True
