from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.flow_v2.models import FlowV2Session


def _row_to_dict(row: FlowV2Session) -> dict[str, str | None]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "flow_version_id": str(row.flow_version_id),
        "conversation_id": str(row.conversation_id) if row.conversation_id else None,
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "external_user_id": row.external_user_id,
        "status": row.status,
        "current_node_id": row.current_node_id,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def find_duplicates(*, tenant_id: str | None = None, conversation_id: str | None = None, flow_version_id: str | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        filters = []
        if tenant_id:
            filters.append(FlowV2Session.tenant_id == tenant_id)
        if conversation_id:
            filters.append(FlowV2Session.conversation_id == conversation_id)
        if flow_version_id:
            filters.append(FlowV2Session.flow_version_id == flow_version_id)

        grouped = (
            select(
                FlowV2Session.tenant_id,
                FlowV2Session.flow_version_id,
                FlowV2Session.external_user_id,
                FlowV2Session.conversation_id,
                func.count(FlowV2Session.id).label("count"),
            )
            .where(*filters)
            .group_by(
                FlowV2Session.tenant_id,
                FlowV2Session.flow_version_id,
                FlowV2Session.external_user_id,
                FlowV2Session.conversation_id,
            )
            .having(func.count(FlowV2Session.id) > 1)
            .order_by(func.count(FlowV2Session.id).desc())
        )

        results: list[dict] = []
        for group in db.execute(grouped).mappings().all():
            sessions = db.execute(
                select(FlowV2Session)
                .where(
                    FlowV2Session.tenant_id == group["tenant_id"],
                    FlowV2Session.flow_version_id == group["flow_version_id"],
                    FlowV2Session.external_user_id == group["external_user_id"],
                    FlowV2Session.conversation_id == group["conversation_id"],
                )
                .order_by(FlowV2Session.updated_at.desc(), FlowV2Session.started_at.desc())
            ).scalars().all()
            results.append({"identity": {key: str(value) if value is not None else None for key, value in group.items()}, "sessions": [_row_to_dict(item) for item in sessions]})
        return results
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="List duplicate Runtime V2 sessions by tenant/conversation/flow identity.")
    parser.add_argument("--tenant-id")
    parser.add_argument("--conversation-id")
    parser.add_argument("--flow-version-id")
    args = parser.parse_args()
    print(json.dumps(find_duplicates(tenant_id=args.tenant_id, conversation_id=args.conversation_id, flow_version_id=args.flow_version_id), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
