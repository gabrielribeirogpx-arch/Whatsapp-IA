from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.flow_v2.actions import RuntimeAction, SendMessageAction


@runtime_checkable
class ChannelAdapter(Protocol):
    """Outbound delivery interface for Runtime V2 actions."""

    def send_text(self, *, recipient_id: str, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]: ...

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

    def send_text(self, *, recipient_id: str, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        metadata = metadata or {}
        if self.client is None:
            return {"status": "mocked", "channel": "whatsapp", "type": "text", "recipient_id": recipient_id, "text": text}
        if callable(self.client):
            return self.client(recipient_id=recipient_id, text=text, metadata=metadata)
        return self.client.send_text(recipient_id=recipient_id, text=text, metadata=metadata)

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
            return self.send_text(recipient_id=action.external_user_id, text=action.text, metadata=action.metadata)
        return {"status": "mocked", "channel": "whatsapp", "type": action.action_type, "recipient_id": action.external_user_id}
