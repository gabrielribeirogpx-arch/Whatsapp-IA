"""Editorial, dependency-free A4 PDF reports.

The former renderer used one global ``y`` value and fixed row heights.  It
therefore wrapped neither cells nor sections before deciding page breaks,
which caused orphan headings, footer collisions and duplicate technical
sections.  This compositor delegates geometry and preventive pagination to
``layout`` and records each section id once per document.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from math import ceil
import os
from typing import Any

from . import styles as s
from .analyzer import analyse, conclusions, executive_summary
from .formatter import date, duration, number, percent
from .layout import FlowLayout, Section, text_height, wrap_text
from .layout.page_context import PageContext

W, H, M = 595, 842, 42


def _rgb(c): return "%.3f %.3f %.3f" % tuple(x / 255 for x in c)
def _esc(text: Any) -> str:
    return str(text).encode("cp1252", "replace").decode("latin1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
def _status_color(tone): return {"success": s.SUCCESS, "warning": s.WARNING, "critical": s.CRITICAL}.get(tone, s.MUTED)
def _status(value): return {"success": "Sucesso", "failed": "Falha", "failure": "Falha"}.get(str(value).lower(), str(value or "—"))
def _report_id(tenant, start, end, mode): return "OBS-" + hashlib.sha256(f"{tenant.get('id')}|{start.isoformat()}|{end.isoformat()}|{mode}".encode()).hexdigest()[:10].upper()


class PDF:
    def __init__(self, footer: str): self.pages = [[]]; self.footer = footer
    @property
    def c(self): return self.pages[-1]
    def page(self): self.pages.append([])
    def text(self, x, y, value, size=9, color=s.TEXT, bold=False): self.c.append(f"BT /F{'2' if bold else '1'} {size} Tf {_rgb(color)} rg {x:.1f} {y:.1f} Td ({_esc(value)}) Tj ET")
    def rect(self, x, y, w, h, fill=s.WHITE, stroke=s.BORDER): self.c.append(f"q {_rgb(fill)} rg {x:.1f} {y:.1f} {w:.1f} {h:.1f} re f {_rgb(stroke)} RG .5 w {x:.1f} {y:.1f} {w:.1f} {h:.1f} re S Q")
    def line(self, x1, y1, x2, y2, color=s.BORDER, width=1): self.c.append(f"q {_rgb(color)} RG {width} w {x1} {y1} m {x2} {y2} l S Q")


class ReportLayout:
    """Components built on a single safe flow cursor and spacing scale."""
    def __init__(self, pdf):
        self.pdf, self.flow = pdf, FlowLayout(pdf, PageContext())
        self.debug = os.getenv("OBSERVABILITY_PDF_DEBUG_LAYOUT", "").lower() == "true"

    @property
    def y(self): return self.flow.y
    def _debug(self, label, height):
        if self.debug:
            self.pdf.rect(M, self.y - height, W - 2*M, height, (255, 255, 255), s.CRITICAL)
            self.pdf.text(M + 2, self.y - 8, label, 6, s.CRITICAL)
    def block(self, height, *, keep=True, split=False, label="block"):
        self.flow.ensure_space(height, keep_together=keep, allow_split=split); self._debug(label, height)
    def gap(self, amount=s.SPACE_SM): self.flow.move(amount)
    def text_lines(self, value, x, width, size=9, color=s.MUTED, bold=False, leading=None):
        leading = leading or size * 1.42
        lines = wrap_text(value, width, size)
        for line in lines:
            self.pdf.text(x, self.y, line, size, color, bold); self.flow.move(leading)
        return len(lines) * leading
    def section(self, section_id, title, min_content=28):
        sec = Section(section_id, title, s.SPACE_LG + s.FONT["heading"] * 1.2 + s.SPACE_SM + min_content, True, False)
        if not self.flow.begin(sec): return False
        self.gap(s.SPACE_LG); self.pdf.text(M, self.y, title, s.FONT["heading"], s.TEXT, True); self.gap(20 + s.SPACE_SM)
        return True
    def draw_kpi_card(self, title, value, hint, x, y, width, height, tone=s.MUTED):
        """Draw one KPI cell at an explicit position without moving the flow cursor."""
        self.pdf.rect(x, y - height, width, height, s.SUBTLE)
        self.pdf.text(x + 15, y - 17, title, 8, s.MUTED)
        self.pdf.text(x + 15, y - 41, value, s.FONT["kpi"], s.TEXT, True)
        self.pdf.text(x + 15, y - 59, hint, 7, tone)

    def draw_kpi_grid(self, cards, *, columns=3, gap_x=s.SPACE_SM,
                      gap_y=s.SPACE_MD, card_height=76):
        """Render fixed-size KPI cards as a deterministic, keep-together grid."""
        rows = ceil(len(cards) / columns)
        card_width = (W - 2 * M - gap_x * (columns - 1)) / columns
        grid_height = rows * card_height + max(0, rows - 1) * gap_y
        self.block(grid_height, label="kpi-grid")

        grid_top = self.y
        for index, card in enumerate(cards):
            row, column = divmod(index, columns)
            x = M + column * (card_width + gap_x)
            y = grid_top - row * (card_height + gap_y)
            self.draw_kpi_card(
                *card[:3], x=x, y=y, width=card_width, height=card_height,
                tone=card[3],
            )

        # The grid is a single flow block: individual cards never affect y.
        self.flow.move(grid_height)
        return grid_height
    def empty_state(self, text):
        height = max(52, text_height(text, W - 2*M - 32, 9) + 28); self.block(height, label="empty-state")
        self.pdf.rect(M, self.y-height, W-2*M, height, s.SUBTLE); self.text_lines(text, M+16, W-2*M-32, 9); self.flow.move(height - text_height(text, W-2*M-32, 9))
        self.gap(s.SPACE_LG)
    def editorial(self, text, *, bullet=False):
        x, width = (M + 28, W - 2*M - 44) if bullet else (M + 16, W - 2*M - 32)
        height = max(58, text_height(text, width, 9) + 28)
        self.block(height, keep=True, label="editorial-card"); self.pdf.rect(M, self.y-height, W-2*M, height, s.SUBTLE)
        if bullet: self.pdf.text(M + 14, self.y - 17, "•", 11, s.PRIMARY, True)
        self.text_lines(text, x, width); self.flow.move(height - text_height(text, width, 9)); self.gap(s.SPACE_SM)
    def table(self, headers, rows, widths):
        header_h, pad = 22, 6
        measured = []
        for row in rows:
            h = max(24, max(text_height(cell, width - pad*2, 7, 9) for cell, width in zip(row, widths)) + pad*2)
            measured.append(h)
        self.block(header_h + measured[0] if measured else header_h, label="table-start")
        def draw_header():
            x = M
            for name, width in zip(headers, widths): self.pdf.rect(x, self.y-header_h, width, header_h, s.SUBTLE); self.pdf.text(x+pad, self.y-14, name, 7, s.MUTED, True); x += width
            self.flow.move(header_h)
        draw_header()
        for row, height in zip(rows, measured):
            if self.flow.context.available_height() < height + FlowLayout.safety_buffer:
                self.flow.add_page(); draw_header()
            x = M
            for cell, width in zip(row, widths):
                self.pdf.rect(x, self.y-height, width, height)
                baseline = self.y - 11
                for line in wrap_text(cell, width-pad*2, 7): self.pdf.text(x+pad, baseline, line, 7); baseline -= 9
                x += width
            self.flow.move(height)
        self.gap(s.SPACE_LG)


def _header(l, *, tenant, start, end, timezone_name, mode, report_id, health, locale):
    labels = [("Organização", tenant.get("name") or tenant.get("slug") or "Não disponível"), ("Período analisado", f"{date(start, timezone_name, locale)} até {date(end, timezone_name, locale)}"), ("Gerado em", date(end, timezone_name, locale)), ("Fuso horário", timezone_name), ("Identificador", report_id)]
    # Metadata is a two-column grid; grow the keep-together block for long
    # tenant names or timezone values instead of letting values overlap.
    value_width = W-M-128
    metadata_rows = [max(16, text_height(value, value_width, 7, 10) + 4) for _, value in labels]
    height = 100 + sum(metadata_rows) + s.SPACE_MD
    l.block(height, label="header")
    l.pdf.rect(M, l.y-height, W-2*M, height, s.WHITE)
    l.pdf.text(M+16, l.y-25, "WAZZA", 13, s.PRIMARY, True); l.pdf.text(M+16, l.y-55, "Relatório de Observabilidade", s.FONT["title"], s.TEXT, True); l.pdf.text(M+16, l.y-75, "Executivo" if mode == "executive" else "Técnico", 10, s.MUTED)
    color = _status_color(health.tone); l.pdf.rect(W-M-130, l.y-38, 114, 23, color, color); l.pdf.text(W-M-120, l.y-31, health.label, 9, s.WHITE, True)
    y = l.y-100
    for (label, value), row_height in zip(labels, metadata_rows):
        l.pdf.text(M+16, y, label, 7, s.MUTED, True)
        for index, line in enumerate(wrap_text(value, value_width, 7)):
            l.pdf.text(M+112, y-index*10, line, 7, s.TEXT)
        y -= row_height
    l.flow.move(height); l.gap(s.SPACE_XL)


def _kpis(l, summary, health, comparison, locale):
    items = [("Execuções", number(summary.get("executions"), locale), "execuções"), ("Taxa de sucesso", percent(summary.get("success_rate"), locale), "eventos concluídos"), ("Latência p95", duration(summary.get("p95"), locale), "percentil de duração"), ("Erros", number(summary.get("errors"), locale), "erros registrados"), ("Throughput", f"{number(summary.get('throughput_per_minute'), locale, 2)}/min", "eventos persistidos"), ("Alertas", number(summary.get("alerts_active"), locale), "alertas ativos")]
    grid_height = 2 * 76 + s.SPACE_MD
    # Reserve the title, grid and trailing spacing together so the two grid
    # rows cannot be separated by a page break.
    l.section("kpis", "Indicadores principais", grid_height + s.SPACE_SM)
    cards = [(*item, _status_color(health.tone)) for item in items]
    l.draw_kpi_grid(cards)
    l.gap(s.SPACE_SM)
    l.text_lines("Comparação com período anterior disponível." if comparison else "Comparação indisponível para o período selecionado.", M, W-2*M, 8); l.gap(s.SPACE_SM)


def _performance(l, summary, health, locale):
    l.section("performance", "Desempenho", 46)
    status = health.label if summary.get("p95") is not None else "—"
    l.table(["Métrica", "Valor", "Status", "Referência"], [["Latência p50", duration(summary.get("p50"), locale), "—", "—"], ["Latência p95", duration(summary.get("p95"), locale), status, "limite configurado"], ["Latência p99", duration(summary.get("p99"), locale), "—", "—"], ["Throughput", f"{number(summary.get('throughput_per_minute'), locale, 2)}/min", "—", "eventos persistidos"], ["Retries", number(summary.get("retries"), locale), health.label, "limite configurado"], ["Contenção de lock", number(summary.get("lock_contention"), locale), health.label, "limite configurado"]], [125, 100, 110, 176])


def _traces(l, records, technical, locale):
    l.section("traces", "Traces e eventos" if technical else "Traces principais", 70)
    if not records: return l.empty_state("Nenhuma execução foi encontrada no período selecionado.")
    if len(records) == 1:
        r = records[0]; return l.editorial(f"Execução observada\nTrace: {str(r.get('trace_id', ''))[:16]}\nStatus: {_status(r.get('status'))}   •   Duração: {duration(r.get('duration_ms'), locale)}   •   Eventos: {r.get('event_count', '—')}   •   Retries: {r.get('retry_count', '—')}")
    headers = ["Trace", "Execução", "Status", "Duração", "Eventos", "Retries"] if technical else ["Horário", "Trace", "Fluxo/Sistema", "Status", "Duração"]
    rows = []
    for r in records[:50 if technical else 8]:
        rows.append([str(r.get("trace_id", ""))[:12], str(r.get("execution_id", ""))[:10], _status(r.get("status")), duration(r.get("duration_ms"), locale), str(r.get("event_count", "")), str(r.get("retry_count", ""))] if technical else [str(r.get("started_at", ""))[:16].replace("T", " "), str(r.get("trace_id", ""))[:12], str(r.get("flow_id") or r.get("ai_system_id") or "—")[:18], _status(r.get("status")), duration(r.get("duration_ms"), locale)])
    l.table(headers, rows, [85,85,75,80,80,56] if technical else [90,95,125,75,76])


def _technical(l, summary, records, filters, locale):
    l.section("filters", "Filtros utilizados", 70)
    items = [("Período", filters.get("period") or "Período selecionado"), ("Modo", "Técnico"), ("Idioma", "Português (Brasil)" if locale == "pt-BR" else "English (United States)"), ("Timezone", filters.get("timezone") or filters.get("timezone_name") or "Não informado")]
    for label, value in items: l.editorial(f"{label}\n{value}")
    l.section("infrastructure", "Infraestrutura", 58); l.empty_state("Telemetria detalhada de infraestrutura não estava disponível neste relatório.")
    l.section("appendix", "Apêndice técnico", 58); l.editorial("IDs e metadados são exibidos somente em formato sanitizado. Segredos, prompts, respostas e payloads brutos não são incluídos.")


def _trace(l, events, record, locale):
    l.section("identity", "Identificação da execução", 55); l.editorial(f"Trace: {record.get('trace_id')}\nExecução: {record.get('execution_id') or 'Não disponível'}\nStatus: {_status(record.get('status'))}")
    l.section("timeline", "Timeline visual", 40)
    for i, event in enumerate(events):
        l.block(40, keep=True, label=f"event-{i}"); l.pdf.line(M+7, l.y-29, M+7, l.y-2, s.PRIMARY, 1.2); l.pdf.text(M+22, l.y-8, str(event.get("event_type", "")).replace("_", " ").title(), 9, s.TEXT, True); l.pdf.text(M+22, l.y-21, f"{event.get('timestamp','')} | {duration(event.get('duration_ms'), locale)} | {_status(event.get('status'))}", 7, s.MUTED); l.flow.move(40)
    l.section("sanitized", "Metadados sanitizados", 48); l.editorial("Os detalhes de eventos foram sanitizados antes da composição deste relatório.")


def render_report(*, tenant: dict[str, Any], summary: dict[str, Any], records: list[dict[str, Any]], start: datetime, end: datetime, timezone_name: str, mode="executive", locale="pt-BR", filters=None, timeline_rows=None, include_charts=True, comparison=None, trace=False) -> bytes:
    mode = "technical" if mode == "technical" else "executive"; locale = "en-US" if locale == "en-US" else "pt-BR"; health = analyse(summary); report_id = _report_id(tenant, start, end, mode)
    pdf = PDF(f"Wazza | {tenant.get('name') or tenant.get('slug') or ''} | {report_id} | {'Técnico' if mode == 'technical' else 'Executivo'}")
    l = ReportLayout(pdf); _header(l, tenant=tenant, start=start, end=end, timezone_name=timezone_name, mode=mode, report_id=report_id, health=health, locale=locale)
    if trace: _trace(l, timeline_rows or [], records[0] if records else {}, locale)
    else:
        _kpis(l, summary, health, comparison, locale)
        l.section("summary", "Resumo executivo", 65); l.editorial(executive_summary(summary))
        _performance(l, summary, health, locale); _traces(l, records, mode == "technical", locale)
        if mode == "technical": _technical(l, summary, records, filters or {}, locale)
        findings, recommendations = conclusions(summary, health)
        l.section("findings", "Constatações", 60)
        for item in findings: l.editorial(item, bullet=True)
        l.section("recommendations", "Recomendações", 60)
        for item in recommendations: l.editorial(item, bullet=True)
        l.section("interpretation", "Como interpretar este relatório", 60); l.editorial("p50, p95 e p99 mostram a duração abaixo da qual 50%, 95% e 99% das amostras ficaram. Throughput é o volume por minuto. Retry é uma nova tentativa; contenção de lock indica disputa por bloqueio; trace reúne os eventos de uma execução.")
    streams, total = [], len(pdf.pages)
    for i, commands in enumerate(pdf.pages, 1):
        commands.append(f"q {_rgb(s.BORDER)} RG .5 w {M} 48 m {W-M} 48 l S Q")
        commands.append(f"BT /F1 8 Tf {_rgb(s.MUTED)} rg {M} 29 Td ({_esc(pdf.footer)}) Tj ET")
        commands.append(f"BT /F1 8 Tf {_rgb(s.MUTED)} rg {W-M-56} 29 Td (Página {i} de {total}) Tj ET")
        streams.append("\n".join(commands))
    return _build(streams)


def _build(streams):
    objects = ["<< /Type /Catalog /Pages 2 0 R >>", f"<< /Type /Pages /Kids [{' '.join(f'{i+5} 0 R' for i in range(len(streams)))}] /Count {len(streams)} >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    pages, content, base = [], [], 5 + len(streams)
    for i, stream in enumerate(streams):
        pages.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W} {H}] /Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {base+i} 0 R >>"); content.append(f"<< /Length {len(stream.encode('latin1'))} >>\nstream\n{stream}\nendstream")
    out, offsets = "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n", [0]
    for i, obj in enumerate(objects + pages + content, 1): offsets.append(len(out.encode("latin1"))); out += f"{i} 0 obj\n{obj}\nendobj\n"
    start = len(out.encode("latin1")); out += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n" + "".join(f"{x:010d} 00000 n \n" for x in offsets[1:]) + f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF"
    return out.encode("latin1")
