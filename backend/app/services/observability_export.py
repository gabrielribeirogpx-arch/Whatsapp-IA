"""Safe serializers for observability exports.

This module is intentionally independent of HTTP and of the event producer: an
export is always made from persisted ``ExecutionTrace`` rows, never from an
incoming webhook payload or a queue job payload.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from html import escape
from typing import Any, Iterable

SENSITIVE = re.compile(r"token|authorization|secret|password|credential|redis_url|postgres|prompt|response|payload", re.I)
FORMULA = re.compile(r"^\s*[=+\-@]")
TRACE_COLUMNS = ["trace_id", "correlation_id", "tenant_id", "conversation_id", "contact_id", "message_id", "execution_id", "job_id", "flow_id", "flow_version_id", "ai_system_id", "source", "status", "started_at", "finished_at", "duration_ms", "event_count", "retry_count", "error_type", "error_message_sanitized"]


def safe_value(value: Any, *, limit: int = 500) -> Any:
    """Remove credentials and reduce arbitrary metadata to a safe preview."""
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if SENSITIVE.search(str(k)) else safe_value(v, limit=limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_value(v, limit=limit) for v in value[:20]]
    if isinstance(value, str):
        return value.replace("\x00", "")[:limit]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:limit]


def safe_cell(value: Any) -> str:
    value = "" if value is None else (json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value))
    return "'" + value if FORMULA.match(value) else value


def iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def trace_records(rows: Iterable[Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row.trace_id), []).append(row)
    result = []
    for trace_id, events in grouped.items():
        events.sort(key=lambda r: (getattr(r, "timestamp", None) or datetime.min, getattr(r, "created_at", None) or datetime.min))
        first, last = events[0], events[-1]
        metadata = [getattr(row, "metadata_json", None) or {} for row in events]
        merged = {k: v for item in metadata for k, v in item.items() if not SENSITIVE.search(str(k))}
        types = [str(getattr(row, "event_type", "")) for row in events]
        error = next((str(m.get("error") or m.get("error_message") or "") for m in reversed(metadata) if m.get("error") or m.get("error_message")), "")
        status = "failed" if any("FAILED" in item for item in types) else "success" if any("FINISHED" in item or "SENT" in item for item in types) else "running"
        result.append({
            "trace_id": trace_id, "correlation_id": merged.get("correlation_id") or trace_id,
            "tenant_id": str(getattr(first, "tenant_id", "") or ""), "conversation_id": str(getattr(first, "conversation_id", "") or "") or None,
            "contact_id": str(getattr(first, "contact_id", "") or "") or None, "message_id": merged.get("message_id"),
            "execution_id": str(getattr(first, "execution_id", "") or ""), "job_id": merged.get("job_id"), "flow_id": str(getattr(first, "flow_id", "") or "") or None,
            "flow_version_id": merged.get("flow_version_id"), "ai_system_id": merged.get("ai_system_id"), "source": merged.get("source"), "status": status,
            "started_at": iso(getattr(first, "timestamp", None)), "finished_at": iso(getattr(last, "timestamp", None)),
            "duration_ms": sum(int(getattr(x, "duration_ms", 0) or 0) for x in events) or None, "event_count": len(events),
            "retry_count": sum(1 for item in types if "RETRY" in item), "error_type": merged.get("error_type") or ("execution_error" if error else None),
            "error_message_sanitized": safe_value(error, limit=300) or None,
        })
    return result


def timeline(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [{"timestamp": iso(r.timestamp), "event_type": r.event_type, "duration_ms": r.duration_ms,
             "component": safe_value((r.metadata_json or {}).get("component")), "node": safe_value((r.metadata_json or {}).get("node_id")),
             "specialist": safe_value((r.metadata_json or {}).get("specialist")), "tool": safe_value((r.metadata_json or {}).get("tool_id")),
             "queue": safe_value((r.metadata_json or {}).get("queue")), "attempt": safe_value((r.metadata_json or {}).get("attempt")),
             "status": "failed" if "FAILED" in r.event_type else "ok", "metadata": safe_value(r.metadata_json or {})} for r in rows]


def json_export(*, tenant: dict[str, Any], filters: dict[str, Any], summary: dict[str, Any], data: Any, timezone_name: str) -> bytes:
    return json.dumps({"schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(), "timezone": timezone_name, "tenant": tenant, "filters": safe_value(filters), "summary": safe_value(summary), "data": safe_value(data)}, ensure_ascii=False, default=str).encode()


def csv_export(records: list[dict[str, Any]]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=TRACE_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in records: writer.writerow({key: safe_cell(row.get(key)) for key in TRACE_COLUMNS})
    return out.getvalue().encode("utf-8-sig")


def xlsx_export(records: list[dict[str, Any]], summary: dict[str, Any]) -> bytes:
    """Create a dependency-free XLSX workbook; cells are inline strings and safe."""
    import zipfile
    def sheet(rows: list[list[Any]]) -> str:
        cells = []
        for r, values in enumerate(rows, 1):
            cells.append("<row r=\"%d\">" % r + "".join("<c t=\"inlineStr\"><is><t>%s</t></is></c>" % escape(safe_cell(v)) for v in values) + "</row>")
        return "<?xml version=\"1.0\"?><worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetViews><sheetView workbookViewId=\"0\"><pane ySplit=\"1\" topLeftCell=\"A2\" state=\"frozen\"/></sheetView></sheetViews><sheetData>" + "".join(cells) + "</sheetData><autoFilter ref=\"A1:T%d\"/></worksheet>" % max(1, len(rows))
    traces = [TRACE_COLUMNS] + [[row.get(c) for c in TRACE_COLUMNS] for row in records]
    summary_rows = [["metric", "value"]] + [[k, v] for k, v in summary.items()]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<?xml version=\"1.0\"?><Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\"><Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/><Default Extension=\"xml\" ContentType=\"application/xml\"/><Override PartName=\"/xl/workbook.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml\"/><Override PartName=\"/xl/worksheets/sheet1.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/><Override PartName=\"/xl/worksheets/sheet2.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml\"/></Types>")
        z.writestr("_rels/.rels", "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"xl/workbook.xml\"/></Relationships>")
        z.writestr("xl/workbook.xml", "<workbook xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\" xmlns:r=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships\"><sheets><sheet name=\"Resumo\" sheetId=\"1\" r:id=\"rId1\"/><sheet name=\"Traces\" sheetId=\"2\" r:id=\"rId2\"/></sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels", "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\"><Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet1.xml\"/><Relationship Id=\"rId2\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet\" Target=\"worksheets/sheet2.xml\"/></Relationships>")
        z.writestr("xl/worksheets/sheet1.xml", sheet(summary_rows)); z.writestr("xl/worksheets/sheet2.xml", sheet(traces))
    return buffer.getvalue()


def pdf_export(title: str, summary: dict[str, Any], records: list[dict[str, Any]]) -> bytes:
    """Backward-compatible PDF entry point used by older callers."""
    from datetime import datetime
    from app.services.observability_reports import render_report
    start = datetime.fromisoformat(summary.get("period_start", datetime.utcnow().isoformat()))
    end = datetime.fromisoformat(summary.get("period_end", datetime.utcnow().isoformat()))
    return render_report(tenant={"name": "Wazza"}, summary=summary, records=records, start=start, end=end, timezone_name="UTC")
