from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.audit_service import to_json_safe


class EventKind(str, Enum):
    CREATED = "created"


class Payload(BaseModel):
    occurred_at: datetime


@dataclass
class Details:
    amount: Decimal


def test_to_json_safe_normalizes_supported_audit_metadata_recursively():
    identifier = uuid.uuid4()
    value = {
        "datetime": datetime(2026, 7, 21, 10, 30),
        "date": date(2026, 7, 21),
        "uuid": identifier,
        "decimal": Decimal("12.50"),
        "enum": EventKind.CREATED,
        "nested": [Details(Decimal("2.00")), {"model": Payload(occurred_at=datetime(2026, 7, 22, 8))}],
    }

    assert to_json_safe(value) == {
        "datetime": "2026-07-21T10:30:00",
        "date": "2026-07-21",
        "uuid": str(identifier),
        "decimal": "12.50",
        "enum": "created",
        "nested": [{"amount": "2.00"}, {"model": {"occurred_at": "2026-07-22T08:00:00"}}],
    }


def test_to_json_safe_rejects_unknown_objects():
    with pytest.raises(TypeError, match="Unsupported audit metadata type"):
        to_json_safe({"unexpected": object()})
