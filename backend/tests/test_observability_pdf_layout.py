from datetime import datetime, timedelta

from app.services.observability_reports.analyzer import executive_summary
from app.services.observability_reports.layout import FlowLayout, PageContext, Section
from app.services.observability_reports.pdf_renderer import PDF, ReportLayout, render_report


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


def test_kpi_grid_uses_fixed_three_column_two_row_geometry(monkeypatch):
    layout = ReportLayout(PDF("footer"))
    boxes = []
    cards = [(f"KPI {index}", "1", "descrição", (1, 2, 3)) for index in range(6)]

    def record_card(title, value, hint, x, y, width, height, tone):
        boxes.append((x, y, width, height))

    monkeypatch.setattr(layout, "draw_kpi_card", record_card)
    grid_height = layout.draw_kpi_grid(cards)

    first_row, second_row = boxes[:3], boxes[3:]
    assert [box[1] for box in first_row] == [first_row[0][1]] * 3
    assert [box[1] for box in second_row] == [second_row[0][1]] * 3
    assert first_row[0][1] - second_row[0][1] == 76 + 18
    assert {box[2] for box in boxes} == {first_row[0][2]}
    assert {box[3] for box in boxes} == {76}
    assert first_row[1][0] - first_row[0][0] == first_row[0][2] + 12
    assert first_row[2][0] - first_row[1][0] == first_row[0][2] + 12
    assert grid_height == 2 * 76 + 18
    assert layout.y == layout.flow.context.content_top - grid_height
