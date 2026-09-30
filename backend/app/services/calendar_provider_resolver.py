"""Server-side resolution of the calendar implementation."""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy import select

from app.models.integration_connection import IntegrationConnection
from app.services.calendar_provider import CalendarProvider
from app.services.google_calendar_provider import GoogleCalendarProvider
from app.services.google_calendar_service import GoogleCalendarService
from app.services.wazza_native_calendar_provider import WazzaNativeCalendarProvider
from app.tools.context import ToolContext

GOOGLE_CALENDAR_PROVIDER = "google_calendar"
WAZZA_NATIVE_PROVIDER = "wazza_native"


class CalendarProviderResolutionError(RuntimeError):
    """A safe, stable failure raised when a provider binding is invalid."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class CalendarProviderResolver:
    """Resolve only server-selected providers from trusted ``ToolContext``."""

    def __init__(
        self,
        db: Any,
        *,
        service_factory: Callable[..., GoogleCalendarService] = GoogleCalendarService,
        validate_binding: bool = True,
        native_calendar_id: Any | None = None,
        native_resource_id: Any | None = None,
    ) -> None:
        self._db = db
        self._service_factory = service_factory
        self._validate_binding = validate_binding
        self._native_calendar_id = native_calendar_id
        self._native_resource_id = native_resource_id

    def resolve(
        self,
        context: ToolContext,
        *,
        provider: str = GOOGLE_CALENDAR_PROVIDER,
    ) -> CalendarProvider:
        if provider == WAZZA_NATIVE_PROVIDER:
            # Native selection is enabled only by a server-owned binding supplied
            # while constructing the resolver; tool/LLM arguments are never read.
            if (context.tenant_id is None or context.contact_id is None
                    or self._native_calendar_id is None or self._native_resource_id is None):
                raise CalendarProviderResolutionError("wazza_native_binding_required")
            return WazzaNativeCalendarProvider(
                self._db, context.tenant_id, context.contact_id,
                self._native_calendar_id, self._native_resource_id,
            )
        if provider != GOOGLE_CALENDAR_PROVIDER:
            raise CalendarProviderResolutionError("calendar_provider_unsupported")
        if context.tenant_id is None:
            raise CalendarProviderResolutionError("google_calendar_connection_required")

        # The binding comes exclusively from ToolContext. Tool arguments never
        # participate in provider, tenant, contact, or connection resolution.
        if self._validate_binding and context.integration_connection_id is not None:
            connection = self._db.execute(
                select(IntegrationConnection).where(
                    IntegrationConnection.id == context.integration_connection_id,
                )
            ).scalars().first()
            if (
                connection is None
                or connection.tenant_id != context.tenant_id
                or connection.status != "active"
                or connection.provider != GOOGLE_CALENDAR_PROVIDER
                or connection.auth_type != "oauth2"
            ):
                raise CalendarProviderResolutionError("google_calendar_connection_required")

        return GoogleCalendarProvider(
            self._db,
            context.tenant_id,
            context.integration_connection_id,
            service_factory=self._service_factory,
        )
