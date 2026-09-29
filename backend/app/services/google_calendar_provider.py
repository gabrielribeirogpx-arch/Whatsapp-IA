"""Google implementation of the internal calendar provider boundary."""

from __future__ import annotations

from typing import Any, Callable

from app.services.calendar_provider import CalendarResult
from app.services.google_calendar_service import GoogleCalendarService


class GoogleCalendarProvider:
    """Thin delegation layer over the existing, authoritative Google service."""

    def __init__(
        self,
        db: Any,
        tenant_id: Any,
        integration_connection_id: Any | None = None,
        *,
        service_factory: Callable[..., GoogleCalendarService] = GoogleCalendarService,
    ) -> None:
        self._service = service_factory(db, tenant_id, integration_connection_id)

    def check_availability(self, **kwargs: Any) -> CalendarResult:
        return self._service.check_availability(**kwargs)

    def create_event(self, *, asa_private_metadata: dict[str, str] | None = None, **kwargs: Any) -> CalendarResult:
        if asa_private_metadata is None:
            return self._service.create_event(**kwargs)
        return self._service.create_event(asa_private_metadata=asa_private_metadata, **kwargs)

    def find_managed_appointments(self, **kwargs: Any) -> CalendarResult:
        return self._service.find_managed_appointments(**kwargs)

    def update_event(self, event_id: str, **kwargs: Any) -> CalendarResult:
        return self._service.update_event(event_id, **kwargs)

    def delete_event(self, event_id: str) -> CalendarResult:
        return self._service.delete_event(event_id)

    def list_events(self, **kwargs: Any) -> CalendarResult:
        return self._service.list_events(**kwargs)
