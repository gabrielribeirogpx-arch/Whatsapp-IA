from __future__ import annotations

import inspect
import logging
from typing import Any, Protocol, runtime_checkable

from app.flow_v2.actions import RuntimeAction, SendMessageAction

logger = logging.getLogger(__name__)


@runtime_checkable
class ChannelAdapter(Protocol):
    """Outbound delivery interface for Runtime V2 actions."""

    def send_text(
        self,
        *,
        recipient_id: str,
        text: str,
        tenant_id: Any | None = None,
        session_id: Any | None = None,
        conversation_id: Any | None = None,
        contact_id: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def send_image(self, *, recipient_id: str, image_url: str, caption: str | None = None,
                   metadata: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def send_document(self, *, recipient_id: str, document_url: str, filename: str | None = None,
                      metadata: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def send_buttons(self, *, recipient_id: str, text: str, buttons: list[dict[str, Any]],
                     metadata: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def send_list(self, *, recipient_id: str, text: str, sections: list[dict[str, Any]],
                  metadata: dict[str, Any] | None = None) -> dict[str, Any]: ...

    def dispatch(self, action: RuntimeAction) -> dict[str, Any]: ...


class WhatsAppAdapter:
    """WhatsApp ChannelAdapter for Flow Runtime V2.

    `client` is deliberately injected so this module does not import V1 services.
    A production client only needs a `send_text(...)` method or to be callable.
    """

    def __init__(self, *, client: Any | None = None) -> None:
        self.client = client
        self.sent_actions: list[RuntimeAction] = []

    @staticmethod
    def _invoke_text_client(client: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        try:
            signature = inspect.signature(client)
        except (TypeError, ValueError):
            return client(**kwargs)

        if any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()):
            return client(**kwargs)

        accepted_kwargs = {key: value for key, value in kwargs.items() if key in signature.parameters}
        return client(**accepted_kwargs)

    def send_text(
        self,
        *,
        recipient_id: str,
        text: str,
        tenant_id: Any | None = None,
        session_id: Any | None = None,
        conversation_id: Any | None = None,
        contact_id: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metadata = dict(metadata or {})
        logger.info(
            "[V2 CHANNEL ADAPTER] tenant_id=%s provider_id=%s session_id=%s conversation_id=%s contact_id=%s recipient_id=%s metadata_keys=%s",
            tenant_id,
            metadata.get("provider_id"),
            session_id,
            conversation_id,
            contact_id,
            recipient_id,
            sorted(metadata.keys()),
        )
        if self.client is None:
            return {
                "status": "mocked",
                "channel": "whatsapp",
                "type": "text",
                "recipient_id": recipient_id,
                "text": text,
                "tenant_id": str(tenant_id) if tenant_id is not None else None,
                "session_id": str(session_id) if session_id is not None else None,
                "conversation_id": str(conversation_id) if conversation_id is not None else None,
                "contact_id": str(contact_id) if contact_id is not None else None,
                "metadata": metadata,
            }
        kwargs = {
            "recipient_id": recipient_id,
            "text": text,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "conversation_id": conversation_id,
            "contact_id": contact_id,
            "metadata": metadata,
        }
        if callable(self.client):
            return self._invoke_text_client(self.client, kwargs)
        return self._invoke_text_client(self.client.send_text, kwargs)

    def send_image(self, *, recipient_id: str, image_url: str, caption: str | None = None,
                   metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": "mocked", "channel": "whatsapp", "type": "image", "recipient_id": recipient_id, "image_url": image_url}

    def send_document(self, *, recipient_id: str, document_url: str, filename: str | None = None,
                      metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": "mocked", "channel": "whatsapp", "type": "document", "recipient_id": recipient_id, "document_url": document_url}

    def send_buttons(self, *, recipient_id: str, text: str, buttons: list[dict[str, Any]],
                     metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": "mocked", "channel": "whatsapp", "type": "buttons", "recipient_id": recipient_id, "buttons": buttons}

    def send_list(self, *, recipient_id: str, text: str, sections: list[dict[str, Any]],
                  metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"status": "mocked", "channel": "whatsapp", "type": "list", "recipient_id": recipient_id, "sections": sections}

    def dispatch(self, action: RuntimeAction) -> dict[str, Any]:
        self.sent_actions.append(action)
        if isinstance(action, SendMessageAction):
            logger.info(
                "[V2 CHANNEL ADAPTER] dispatch action_type=%s tenant_id=%s provider_id=%s session_id=%s conversation_id=%s contact_id=%s metadata_keys=%s",
                action.action_type,
                action.tenant_id,
                action.metadata.get("provider_id"),
                action.session_id,
                action.conversation_id,
                action.contact_id,
                sorted(action.metadata.keys()),
            )
            return self.send_text(
                recipient_id=action.external_user_id,
                text=action.text,
                tenant_id=action.tenant_id,
                session_id=action.session_id,
                conversation_id=action.conversation_id,
                contact_id=action.contact_id,
                metadata=action.metadata,
            )
        return {"status": "mocked", "channel": "whatsapp", "type": action.action_type, "recipient_id": action.external_user_id}
