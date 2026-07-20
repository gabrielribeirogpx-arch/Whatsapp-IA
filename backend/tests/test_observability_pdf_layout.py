from datetime import datetime, timedelta

from app.services.observability_reports.analyzer import executive_summary
from app.services.observability_reports.layout import FlowLayout, PageContext, Section
from app.services.observability_reports.pdf_renderer import PDF, render_report


def test_flow_layout_moves_keep_together_section_before_footer():
    pdf = PDF("footer")
    context = PageContext()
    context.set_cursor(context.content_bottom + 60)
    flow = FlowLayout(pdf, context)
    assert flow.begin(Section("findings", estimated_height=90, keep_together=True, allow_split=False))
    assert len(pdf.pages) == 2
    assert context.cursor_y == context.content_top
    assert not flow.begin(Section("findings", estimated_height=90, keep_together=True))


def test_summary_uses_pluralization_and_local_percent_formatting():
    assert "1 execução," in executive_summary({"executions": 1, "success_rate": 100})
    assert "execução(ões)" not in executive_summary({"executions": 2, "success_rate": 100})
    assert "100%" in executive_summary({"executions": 2, "success_rate": 100})


def test_report_has_footer_on_every_page_and_translates_status():
    start = datetime(2026, 1, 1)
    data = render_report(
        tenant={"id": "layout", "name": "Organização com nome muito longo para validar a grade de metadata"},
        summary={"executions": 1, "success_rate": 100, "errors": 0, "retries": 0, "lock_contention": 0, "p50": 1, "p95": 2, "p99": 3, "throughput_per_minute": 1, "alerts_active": 0},
        records=[{"trace_id": "trace", "status": "success", "duration_ms": 4}], start=start, end=start + timedelta(hours=1), timezone_name="America/Argentina/Buenos_Aires",
    )
    assert data.count(b"Pagina") == 0  # cp1252 keeps the accented page label below
    assert data.count(b"P\xe1gina") >= 1
    assert b"Sucesso" in data
