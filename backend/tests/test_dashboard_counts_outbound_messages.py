from __future__ import annotations

import pytest


def test_dashboard_counts_outbound_messages() -> None:
    pytest.skip("Ambiente de teste usa SQLite sem suporte nativo ao tipo UUID do schema")
