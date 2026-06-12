from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.lead import Lead, LeadStatus
from app.services.lead_service import soft_delete_lead_by_phone
from app.utils.phone import normalize_phone


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Soft-delete only one test Lead for a tenant-scoped phone number, "
            "preserving Contact, Conversation, pipelines, stages and settings."
        )
    )
    parser.add_argument(
        "--tenant-id", required=True, help="Tenant UUID that owns the test lead"
    )
    parser.add_argument(
        "--phone", required=True, help="Phone number used by the Flow Builder test"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Persist the soft delete. Without this flag the command runs as dry-run and rolls back.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    tenant_id = UUID(args.tenant_id)
    normalized_phone = normalize_phone(args.phone)
    if not normalized_phone:
        print("Invalid phone: normalization returned an empty value", file=sys.stderr)
        return 2

    with SessionLocal() as db:
        result = soft_delete_lead_by_phone(
            db,
            tenant_id=tenant_id,
            phone=normalized_phone,
            audit_event="Lead de teste do Flow Builder removido",
        )
        if result is None:
            db.rollback()
            print(f"No lead found for tenant_id={tenant_id} phone={normalized_phone}")
            return 0

        pipeline_visible_after = db.execute(
            select(Lead.id).where(
                Lead.tenant_id == tenant_id,
                Lead.phone == normalized_phone,
                Lead.status != LeadStatus.DELETED.value,
            )
        ).scalars().first() is not None

        print("Lead cleanup preview")
        print(f"  tenant_id: {tenant_id}")
        print(f"  phone: {normalized_phone}")
        print(f"  lead_id: {result.lead.id}")
        print(f"  status_after: {result.lead.status}")
        print(f"  already_deleted: {result.already_deleted}")
        print(f"  contact_preserved: {result.contact is not None}")
        print(f"  contact_id: {result.lead.contact_id}")
        print(f"  conversation_preserved: {result.conversation is not None}")
        print(f"  conversation_id: {result.lead.conversation_id}")
        print(f"  pipeline_visible_after: {pipeline_visible_after}")
        print(
            "  recreate_policy: "
            "future Create Lead actions reactivate/update the same tenant-scoped lead"
        )

        if args.execute:
            db.commit()
            print("Committed soft delete.")
        else:
            db.rollback()
            print("Dry-run only; rolled back. Re-run with --execute to apply.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
