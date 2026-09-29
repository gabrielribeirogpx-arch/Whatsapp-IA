"""Internal calendar provider boundary.

This module deliberately mirrors the operations already used by the calendar
tool adapter.  It is not a public tool contract and contains no Google API
types, credentials, or persistence choices.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


CalendarResult = dict[str, Any]


@runtime_checkable
class CalendarProvider(Protocol):
    """Capabilities required by the existing calendar tools."""

    def check_availability(self, **kwargs: Any) -> CalendarResult: ...

    def create_event(self, *, asa_private_metadata: dict[str, str] | None = None, **kwargs: Any) -> CalendarResult: ...

    def find_managed_appointments(
        self,
        *,
        start: str,
        end: str,
        timezone: str | None,
        patient_ref: str,
        metadata_schema: str,
    ) -> CalendarResult: ...

    def update_event(self, event_id: str, **kwargs: Any) -> CalendarResult: ...

    def delete_event(self, event_id: str) -> CalendarResult: ...

    def list_events(self, **kwargs: Any) -> CalendarResult: ...
