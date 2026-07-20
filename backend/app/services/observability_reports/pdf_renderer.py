"""Small dependency-free A4 PDF compositor with vector cards, tables and charts."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from .analyzer import analyse, conclusions, executive_summary
from .formatter import date, duration, number, percent
from . import styles as s

W, H, M = 595, 842, 42


def _rgb(c: tuple[int, int, int]) -> str: return "%.3f %.3f %.3f" % tuple(x / 255 for x in c)
def _esc(text: Any) -> str:
    # WinAnsi covers pt-BR and avoids a runtime font dependency.
    return str(text).encode("cp1252", "replace").decode("latin1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class PDF:
    def __init__(self, footer: str): self.pages: list[list[str]] = [[]]; self.y = H - M; self.footer = footer
    @property
    def c(self): return self.pages[-1]
    def page(self): self.pages.append([]); self.y = H - M
    def text(self, x: float, y: float, value: Any, size: int = 9, color=s.TEXT, bold=False):
        self.c.append(f"BT /F{'2' if bold else '1'} {size} Tf {_rgb(color)} rg {x:.1f} {y:.1f} Td ({_esc(value)}) Tj ET")
    def rect(self, x, y, w, h, fill=s.WHITE, stroke=s.BORDER): self.c.append(f"q {_rgb(fill)} rg {x} {y} {w} {h} re f {_rgb(stroke)} RG .5 w {x} {y} {w} {h} re S Q")
    def line(self, x1, y1, x2, y2, color=s.BORDER, width=1): self.c.append(f"q {_rgb(color)} RG {width} w {x1} {y1} m {x2} {y2} l S Q")
    def need(self, h):
        if self.y - h < 64: self.page()
    def heading(self, value): self.need(30); self.text(M, self.y, value, s.FONT['heading'], bold=True); self.y -= 23
    def paragraph(self, value, width=92):
        words, line = str(value).split(), ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if len(candidate) > width:
                self.need(13); self.text(M, self.y, line, s.FONT['body'], s.MUTED); self.y -= 13; line = word
            else: line = candidate
        if line: self.need(13); self.text(M, self.y, line, s.FONT['body'], s.MUTED); self.y -= 15
    def table(self, headers: list[str], rows: list[list[str]], widths: list[int]):
        self.need(30); x = M
        for h, width in zip(headers, widths): self.rect(x, self.y - 17, width, 17, s.SUBTLE); self.text(x + 5, self.y - 12, h, 7, s.MUTED, True); x += width
        self.y -= 17
        for row in rows:
            self.need(21)
            x = M
            for cell, width in zip(row, widths): self.rect(x, self.y - 19, width, 19); self.text(x + 5, self.y - 13, str(cell)[:max(8, width // 5)], 7); x += width
            self.y -= 19
        self.y -= 10


def _status_color(tone: str): return {"success": s.SUCCESS, "warning": s.WARNING, "critical": s.CRITICAL}.get(tone, s.MUTED)
def _report_id(tenant: dict[str, Any], start: datetime, end: datetime, mode: str) -> str: return "OBS-" + hashlib.sha256(f"{tenant.get('id')}|{start.isoformat()}|{end.isoformat()}|{mode}".encode()).hexdigest()[:10].upper()


def _header(pdf: PDF, *, tenant, start, end, timezone_name, mode, report_id, health, locale):
    pdf.rect(M, pdf.y - 137, W - 2*M, 137, s.WHITE)
    pdf.text(M + 15, pdf.y - 27, "WAZZA", 13, s.PRIMARY, True)
    pdf.text(M + 15, pdf.y - 56, "Relatório de Observabilidade", s.FONT['title'], s.TEXT, True)
    pdf.text(M + 15, pdf.y - 74, "Executivo" if mode == "executive" else "Técnico", 10, s.MUTED)
    color = _status_color(health.tone); pdf.rect(W - M - 120, pdf.y - 39, 105, 22, color, color); pdf.text(W - M - 110, pdf.y - 32, health.label, 9, s.WHITE, True)
    labels = [("Organização", tenant.get("name") or tenant.get("slug") or "Não disponível"), ("Período analisado", f"{date(start, timezone_name, locale)} até {date(end, timezone_name, locale)}"), ("Gerado em", date(end, timezone_name, locale)), ("Fuso horário", timezone_name), ("Identificador", report_id)]
    y = pdf.y - 96
    for label, value in labels: pdf.text(M + 15, y, label, 7, s.MUTED); pdf.text(M + 100, y, value, 7); y -= 12
    pdf.y -= 153


def _kpis(pdf, summary, health, comparison, locale):
    pdf.heading("Indicadores principais")
    items = [("Execuções", number(summary.get("executions"), locale), "execuções"), ("Taxa de sucesso", percent(summary.get("success_rate"), locale), "eventos concluídos"), ("Latência p95", duration(summary.get("p95"), locale), "percentil de duração"), ("Erros", number(summary.get("errors"), locale), "erros registrados"), ("Throughput", f"{number(summary.get('throughput_per_minute'), locale, 2)}/min", "eventos persistidos"), ("Alertas", number(summary.get("alerts_active"), locale), "alertas ativos")]
    width, x = 82, M
    for i, (label, value, hint) in enumerate(items):
        if i and i % 3 == 0: pdf.y -= 70; x = M
        pdf.rect(x, pdf.y - 58, width, 55, s.SUBTLE); pdf.text(x+7, pdf.y-15, label, 7, s.MUTED); pdf.text(x+7, pdf.y-35, value, 14, s.TEXT, True); pdf.text(x+7, pdf.y-48, hint, 6, _status_color(health.tone)); x += width + 8
    pdf.y -= 76
    if comparison:
        pdf.paragraph("Comparação com período anterior: valores apresentados com base em eventos persistidos no intervalo imediatamente anterior.")
    else: pdf.paragraph("Comparação indisponível para o período selecionado.")


def _chart(pdf, records):
    pdf.heading("Execuções ao longo do tempo")
    if len(records) < 2: pdf.paragraph("Não há volume suficiente para representar uma tendência temporal."); return
    pdf.need(125); x, y, w, h = M, pdf.y - 105, W - 2*M, 85; pdf.rect(x, y, w, h, s.SUBTLE); pdf.line(x+20, y+15, x+20, y+h-10); pdf.line(x+20, y+15, x+w-10, y+15)
    values = [1 if r.get("status") == "success" else 0 for r in records[:24]]; maximum = max(1, max(values)); points = []
    for i, value in enumerate(values): points.append((x+25+i*(w-40)/max(1,len(values)-1), y+15+value*(h-30)/maximum))
    for a, b in zip(points, points[1:]): pdf.line(*a, *b, s.PRIMARY, 1.5)
    pdf.text(x+25, y+h-5, "Sucesso por trace (série observada)", 7, s.MUTED); pdf.y -= 120


def _performance(pdf, summary, health, locale):
    pdf.heading("Desempenho")
    status = health.label if summary.get("p95") is not None else "—"
    pdf.table(["Métrica", "Valor", "Status", "Referência"], [["Latência p50", duration(summary.get("p50"), locale), "—", "—"], ["Latência p95", duration(summary.get("p95"), locale), status, "limite configurado"], ["Latência p99", duration(summary.get("p99"), locale), "—", "—"], ["Throughput", f"{number(summary.get('throughput_per_minute'), locale, 2)}/min", "—", "eventos persistidos"], ["Retries", number(summary.get("retries"), locale), health.label, "limite configurado"], ["Lock contention", number(summary.get("lock_contention"), locale), health.label, "limite configurado"]], [125, 100, 110, 176])


def _traces(pdf, records, technical=False, locale="pt-BR"):
    pdf.heading("Traces principais" if not technical else "Traces e eventos")
    if not records: pdf.paragraph("Nenhuma execução foi encontrada no período selecionado."); return
    if len(records) == 1 and not technical:
        r = records[0]; pdf.paragraph(f"Execução observada: trace {r.get('trace_id','')[:16]}, status {r.get('status')}, duração {duration(r.get('duration_ms'), locale)}."); return
    headers = ["Horário", "Trace", "Fluxo/Sistema", "Status", "Duração"] if not technical else ["Trace", "Execução", "Status", "Duração", "Eventos", "Retries"]
    rows = []
    for r in records[:50 if technical else 8]:
        if technical: rows.append([str(r.get("trace_id", ""))[:12], str(r.get("execution_id", ""))[:10], r.get("status", ""), duration(r.get("duration_ms"), locale), str(r.get("event_count", "")), str(r.get("retry_count", ""))])
        else: rows.append([str(r.get("started_at", ""))[0:16].replace("T", " "), str(r.get("trace_id", ""))[:12], str(r.get("flow_id") or r.get("ai_system_id") or "—")[:15], str(r.get("status", "")), duration(r.get("duration_ms"), locale)])
    pdf.table(headers, rows, [90, 95, 125, 75, 76] if not technical else [85, 85, 75, 80, 80, 56])


def _technical(pdf, summary, records, filters, locale):
    pdf.heading("Filtros utilizados"); pdf.paragraph("; ".join(f"{k}: {v}" for k, v in filters.items() if v is not None) or "Sem filtros adicionais.")
    _performance(pdf, summary, analyse(summary), locale); _traces(pdf, records, True, locale)
    pdf.heading("Infraestrutura"); pdf.paragraph("Telemetria detalhada de infraestrutura não estava disponível neste relatório.")
    pdf.heading("Apêndice técnico"); pdf.paragraph("IDs e metadados são exibidos somente em formato sanitizado. Segredos, prompts, respostas e payloads brutos não são incluídos.")


def _trace(pdf, timeline_rows, record, locale):
    pdf.heading("Identificação da execução"); pdf.paragraph(f"Trace: {record.get('trace_id')} | Execução: {record.get('execution_id') or 'Não disponível'} | Status: {record.get('status')}")
    pdf.heading("Timeline visual")
    for event in timeline_rows:
        pdf.need(32); pdf.line(M+7, pdf.y-22, M+7, pdf.y+5, s.PRIMARY, 1.2); pdf.rect(M+3, pdf.y-1, 8, 8, s.PRIMARY, s.PRIMARY); pdf.text(M+22, pdf.y, str(event.get("event_type", "")).replace("_", " ").title(), 9, s.TEXT, True); pdf.text(M+22, pdf.y-12, f"{event.get('timestamp','')} | {duration(event.get('duration_ms'), locale)} | {event.get('status','')}", 7, s.MUTED); pdf.y -= 31
    pdf.heading("Metadados sanitizados"); pdf.paragraph("Os detalhes de eventos foram sanitizados antes da composição deste relatório.")


def render_report(*, tenant: dict[str, Any], summary: dict[str, Any], records: list[dict[str, Any]], start: datetime, end: datetime, timezone_name: str, mode: str = "executive", locale: str = "pt-BR", filters: dict[str, Any] | None = None, timeline_rows: list[dict[str, Any]] | None = None, include_charts: bool = True, comparison: dict[str, Any] | None = None, trace: bool = False) -> bytes:
    mode = "technical" if mode == "technical" else "executive"; locale = "en-US" if locale == "en-US" else "pt-BR"; health = analyse(summary); report_id = _report_id(tenant, start, end, mode)
    pdf = PDF(f"Wazza Observabilidade Enterprise | {tenant.get('name') or tenant.get('slug') or ''} | {report_id}")
    _header(pdf, tenant=tenant, start=start, end=end, timezone_name=timezone_name, mode=mode, report_id=report_id, health=health, locale=locale)
    if trace: _trace(pdf, timeline_rows or [], records[0] if records else {}, locale)
    else:
        _kpis(pdf, summary, health, comparison, locale); pdf.heading("Resumo executivo"); pdf.paragraph(executive_summary(summary))
        if include_charts: _chart(pdf, records)
        _performance(pdf, summary, health, locale); _traces(pdf, records, mode == "technical", locale)
        if mode == "technical": _technical(pdf, summary, records, filters or {}, locale)
        findings, recommendations = conclusions(summary, health); pdf.heading("Constatações"); [pdf.paragraph(f"• {x}") for x in findings]; pdf.heading("Recomendações"); [pdf.paragraph(f"• {x}") for x in recommendations]
        pdf.heading("Como interpretar este relatório"); pdf.paragraph("p50, p95 e p99 mostram a duração abaixo da qual 50%, 95% e 99% das amostras ficaram. Throughput é o volume por minuto. Retry é uma nova tentativa; lock contention indica disputa por bloqueio; trace reúne os eventos de uma execução.")
    streams = []
    total = len(pdf.pages)
    for i, commands in enumerate(pdf.pages, 1):
        commands.append(f"BT /F1 7 Tf {_rgb(s.MUTED)} rg {M} 28 Td ({_esc(pdf.footer)}) Tj ET")
        commands.append(f"BT /F1 7 Tf {_rgb(s.MUTED)} rg {W-M-55} 28 Td (Página {i} de {total}) Tj ET")
        streams.append("\n".join(commands))
    return _build(streams)


def _build(streams: list[str]) -> bytes:
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{' '.join(f'{i+5} 0 R' for i in range(len(streams)))}] /Count {len(streams)} >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    page_objects, content_objects = [], []
    base = 5 + len(streams)
    for i, stream in enumerate(streams):
        page_objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {base+i} 0 R >>")
        raw = stream.encode("latin1"); content_objects.append(f"<< /Length {len(raw)} >>\nstream\n{stream}\nendstream")
    objects += page_objects + content_objects; out = "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"; offsets = [0]
    for i, obj in enumerate(objects, 1): offsets.append(len(out.encode("latin1"))); out += f"{i} 0 obj\n{obj}\nendobj\n"
    start = len(out.encode("latin1")); out += f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n" + "".join(f"{x:010d} 00000 n \n" for x in offsets[1:]) + f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF"
    return out.encode("latin1")
