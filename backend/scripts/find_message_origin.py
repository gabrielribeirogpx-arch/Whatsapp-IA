from __future__ import annotations

import argparse
import json
from typing import Any

from sqlalchemy import text

from app.db.session import SessionLocal

DEFAULT_NEEDLE = "Sem problemas! Posso te mostrar nossos planos."

SEARCH_QUERIES = [
    (
        "flow_versions.nodes",
        """
        SELECT id::text AS record_id, flow_id::text AS flow_id, version::text AS version, nodes::text AS payload
        FROM flow_versions
        WHERE nodes::text ILIKE :pattern
        ORDER BY created_at DESC
        """,
    ),
    (
        "flow_versions.snapshot",
        """
        SELECT id::text AS record_id, flow_id::text AS flow_id, version::text AS version, snapshot::text AS payload
        FROM flow_versions
        WHERE snapshot::text ILIKE :pattern
        ORDER BY created_at DESC
        """,
    ),
    (
        "flows/default_flows",
        """
        SELECT id::text AS record_id, id::text AS flow_id, version::text AS version,
               jsonb_build_object('name', name, 'nodes', nodes, 'nodes_json', nodes_json, 'description', description)::text AS payload
        FROM flows
        WHERE name ILIKE :pattern
           OR COALESCE(description, '') ILIKE :pattern
           OR nodes::text ILIKE :pattern
           OR nodes_json::text ILIKE :pattern
        ORDER BY updated_at DESC
        """,
    ),
    (
        "flow_nodes",
        """
        SELECT id::text AS record_id, flow_id::text AS flow_id, type AS version,
               jsonb_build_object('content', content, 'metadata', metadata)::text AS payload
        FROM flow_nodes
        WHERE COALESCE(content, '') ILIKE :pattern OR metadata::text ILIKE :pattern
        ORDER BY created_at DESC
        """,
    ),
    (
        "bot_service/bot_rules",
        """
        SELECT id::text AS record_id, NULL::text AS flow_id, trigger AS version, response AS payload
        FROM bot_rules
        WHERE trigger ILIKE :pattern OR response ILIKE :pattern
        ORDER BY updated_at DESC
        """,
    ),
    (
        "templates/whatsapp_message_templates",
        """
        SELECT id::text AS record_id, NULL::text AS flow_id, name AS version,
               jsonb_build_object('body_text', body_text, 'footer_text', footer_text, 'buttons', buttons_json, 'metadata', metadata_json)::text AS payload
        FROM whatsapp_message_templates
        WHERE name ILIKE :pattern
           OR body_text ILIKE :pattern
           OR COALESCE(footer_text, '') ILIKE :pattern
           OR buttons_json::text ILIKE :pattern
           OR metadata_json::text ILIKE :pattern
        ORDER BY updated_at DESC
        """,
    ),
]


def _preview(payload: Any, needle: str, limit: int = 500) -> str:
    value = str(payload or "")
    index = value.lower().find(needle.lower())
    if index < 0:
        return value[:limit]
    start = max(0, index - 160)
    end = min(len(value), index + len(needle) + 160)
    return value[start:end]


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca literal de mensagem fantasma nos emissores persistidos.")
    parser.add_argument("needle", nargs="?", default=DEFAULT_NEEDLE)
    args = parser.parse_args()
    pattern = f"%{args.needle}%"
    results: list[dict[str, Any]] = []
    with SessionLocal() as db:
        for source, sql in SEARCH_QUERIES:
            rows = db.execute(text(sql), {"pattern": pattern}).mappings().all()
            for row in rows:
                results.append(
                    {
                        "source": source,
                        "record_id": row.get("record_id"),
                        "flow_id": row.get("flow_id"),
                        "version_or_label": row.get("version"),
                        "preview": _preview(row.get("payload"), args.needle),
                    }
                )
    print(json.dumps({"needle": args.needle, "matches": results, "match_count": len(results)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
