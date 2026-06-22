import uuid

from app.services.google_sheets_service import GoogleSheetsService
from app.tools.adapters.google_sheets_tool_adapter import GoogleSheetsToolAdapter
from app.tools.context import ToolContext


class FakeSheetsService:
    def __init__(self):
        self.calls = []

    def list_spreadsheets(self, **kwargs):
        self.calls.append(("list", kwargs)); return {"ok": True, "spreadsheets": []}

    def read_sheet(self, **kwargs):
        self.calls.append(("read", kwargs)); return {"ok": True, "sheet": {"rows": []}}

    def append_row(self, **kwargs):
        self.calls.append(("append", kwargs)); return {"ok": True, "append": {"updated_range": "A1", "updated_rows": 1}}

    def update_row(self, **kwargs):
        self.calls.append(("update", kwargs)); return {"ok": True, "update": {"updated_range": "A1", "updated_rows": 1}}

    def create_spreadsheet(self, **kwargs):
        self.calls.append(("create", kwargs)); return {"ok": True, "existing": False, "spreadsheet": {"name": kwargs.get("title"), "spreadsheet_id": "s1"}}


def _adapter_with(fake):
    GoogleSheetsToolAdapter._idempotency_results.clear()
    return GoogleSheetsToolAdapter(object(), service_factory=lambda db, tenant_id: fake)


def test_google_sheets_create_spreadsheet_duplicate_tool_blocked_reuses_result():
    fake = FakeSheetsService()
    adapter = _adapter_with(fake)
    ctx = ToolContext(tenant_id=uuid.uuid4(), metadata={"execution_id": "exec-1"})

    first = adapter.execute("google_sheets_create_spreadsheet", {"title": "Clientes"}, ctx, {})
    second = adapter.execute("google_sheets_create_spreadsheet", {"title": "Clientes"}, ctx, {})

    assert first.ok is True and second.ok is True
    assert fake.calls == [("create", {"title": "Clientes"})]
    assert second.output == first.output


def test_google_sheets_append_row_does_not_duplicate_after_confirmation():
    fake = FakeSheetsService()
    adapter = _adapter_with(fake)
    ctx = ToolContext(tenant_id=uuid.uuid4(), metadata={"execution_id": "exec-2"})
    payload = {"spreadsheet_id": "s1", "range": "A1", "values": ["a"]}

    adapter.execute("google_sheets_append_row", payload, ctx, {"confirmed_pending_action": True})
    adapter.execute("google_sheets_append_row", payload, ctx, {"confirmed_pending_action": True})

    assert fake.calls == [("append", payload)]


def test_google_sheets_update_row_does_not_duplicate_after_confirmation():
    fake = FakeSheetsService()
    adapter = _adapter_with(fake)
    ctx = ToolContext(tenant_id=uuid.uuid4(), metadata={"execution_id": "exec-3"})
    payload = {"spreadsheet_id": "s1", "range": "A1:C1", "values": ["a"]}

    adapter.execute("google_sheets_update_row", payload, ctx, {"confirmed_pending_action": True})
    adapter.execute("google_sheets_update_row", payload, ctx, {"confirmed_pending_action": True})

    assert fake.calls == [("update", payload)]


def test_google_sheets_append_update_require_pending_action_confirmation():
    fake = FakeSheetsService()
    adapter = _adapter_with(fake)
    ctx = ToolContext(tenant_id=uuid.uuid4(), metadata={"execution_id": "exec-4"})

    result = adapter.execute("google_sheets_append_row", {"spreadsheet_id": "s1", "values": ["a"]}, ctx, {})

    assert result.ok is False
    assert fake.calls == []
    assert result.error_code == "google_sheets_error"


def test_google_sheets_existing_spreadsheet_returns_existing_true(monkeypatch):
    service = GoogleSheetsService.__new__(GoogleSheetsService)
    monkeypatch.setattr(service, "find_spreadsheet_by_name", lambda title: {"spreadsheet_name": title, "spreadsheet_url": "https://docs.google.com/sheets/d/s1", "spreadsheet_id": "s1"})

    result = service.create_spreadsheet(title="Clientes")

    assert result == {"ok": True, "existing": True, "spreadsheet_name": "Clientes", "spreadsheet_url": "https://docs.google.com/sheets/d/s1", "spreadsheet_id": "s1"}


def test_ai_agent_google_sheets_mutating_tool_finalizes_without_second_llm(monkeypatch):
    from app.services import ai_agent_service as svc
    from app.tools.base import NormalizedToolResult, ToolResult

    llm_calls = []
    execute_calls = []

    def fake_llm(*args, **kwargs):
        llm_calls.append(args)
        return '{"tool":"chamar_mcp","arguments":{"tool_id":"google_sheets_create_spreadsheet","input":{"title":"Clientes"}}}'

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        execute_calls.append((tool_type, tool_id, input))
        output = {"ok": True, "existing": False, "spreadsheet": {"name": input["title"], "spreadsheet_id": "s1"}}
        return ToolResult(True, "google_sheets", tool_id=tool_id, output=output, normalized_result=NormalizedToolResult(True, tool_id, type="google_sheets.create_spreadsheet", data=output))

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)

    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "crie planilha", "instr", ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "google_sheets_create_spreadsheet", "name": "Criar planilha"}]}, options={"max_steps": 3, "execution_id": "exec-finalize"},
    )

    assert len(llm_calls) == 1
    assert execute_calls == [("google_sheets", "google_sheets_create_spreadsheet", {"title": "Clientes"})]
    assert result.message == "Planilha criada no Google Sheets: Clientes."
