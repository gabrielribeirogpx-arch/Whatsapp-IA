from app.routers import webhook
from app.utils.text import normalize_text


def test_find_start_node_accepts_all_supported_flags():
    nodes = [
        {"id": "n1", "type": "message", "data": {"is_start": True}},
        {"id": "n2", "type": "message", "isStart": True},
        {"id": "start", "type": "message"},
    ]
    start = webhook._find_start_node(nodes)
    assert start is not None
    assert start["id"] == "n1"


def test_greeting_normalization_triggers_force_start():
    normalized = normalize_text("Olá")
    assert normalized == "ola"
    assert normalized in {"oi", "ola", "menu", "iniciar", "inicio", "reiniciar", "reset"}
