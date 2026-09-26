"""Trusted metadata attached to Asa-managed Google Calendar appointments."""

from __future__ import annotations

from typing import Final
from uuid import UUID

from app.core.external_identity import APPOINTMENT_PATIENT, derive_external_reference

ASA_METADATA_PREFIX: Final = "asa_"
ASA_MANAGED_KEY: Final = f"{ASA_METADATA_PREFIX}managed"
ASA_SCHEMA_KEY: Final = f"{ASA_METADATA_PREFIX}schema"
ASA_PATIENT_REF_KEY: Final = f"{ASA_METADATA_PREFIX}patient_ref"
APPOINTMENT_METADATA_SCHEMA: Final = "appointment-v1"


def build_appointment_private_metadata(
    *, tenant_id: UUID | str, contact_id: UUID | str
) -> dict[str, str]:
    """Build the complete, server-controlled metadata for an identified appointment."""
    patient_ref = derive_external_reference(
        tenant_id=tenant_id,
        subject_id=contact_id,
        purpose=APPOINTMENT_PATIENT,
    )
    return {
        ASA_MANAGED_KEY: "true",
        ASA_SCHEMA_KEY: APPOINTMENT_METADATA_SCHEMA,
        ASA_PATIENT_REF_KEY: patient_ref,
    }
