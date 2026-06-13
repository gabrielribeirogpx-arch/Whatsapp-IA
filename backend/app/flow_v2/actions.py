from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID


@dataclass(frozen=True)
class RuntimeAction:
    """Base immutable command emitted by Runtime V2.

    Runtime V2 produces actions only. Side effects such as WhatsApp delivery are
    handled later by channel adapters/workers.
    """

    tenant_id: UUID
    session_id: UUID
    external_user_id: str
    conversation_id: UUID | None = None
    contact_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def action_type(self) -> str:
        raise NotImplementedError

    def as_effect(self) -> dict[str, Any]:
        payload = {
            "type": self.action_type,
            "external_user_id": self.external_user_id,
            "metadata": dict(self.metadata),
        }
        if self.conversation_id is not None:
            payload["conversation_id"] = str(self.conversation_id)
        if self.contact_id is not None:
            payload["contact_id"] = str(self.contact_id)
        return payload


@dataclass(frozen=True)
class SendMessageAction(RuntimeAction):
    text: str = ""
    media_url: str | None = None

    @property
    def action_type(self) -> Literal["send_message"]:
        return "send_message"

    def as_effect(self) -> dict[str, Any]:
        payload = super().as_effect()
        payload.update({"text": self.text})
        if self.media_url:
            payload["media_url"] = self.media_url
        return payload


@dataclass(frozen=True)
class SendMediaAction(RuntimeAction):
    media_type: Literal["image", "document"] = "image"
    media_url: str = ""
    caption: str | None = None
    filename: str | None = None

    @property
    def action_type(self) -> Literal["send_media"]:
        return "send_media"

    def as_effect(self) -> dict[str, Any]:
        payload = super().as_effect()
        payload.update({"media_type": self.media_type, "media_url": self.media_url})
        if self.caption:
            payload["caption"] = self.caption
        if self.filename:
            payload["filename"] = self.filename
        return payload


@dataclass(frozen=True)
class SendChoiceButtonsAction(RuntimeAction):
    text: str = ""
    node_id: str = ""
    options: tuple[dict[str, Any], ...] = ()
    buttons: tuple[dict[str, Any], ...] = ()
    sections: tuple[dict[str, Any], ...] = ()
    display_mode: Literal["buttons", "list"] = "buttons"

    @property
    def action_type(self) -> Literal["send_choice_buttons"]:
        return "send_choice_buttons"

    def as_effect(self) -> dict[str, Any]:
        payload = super().as_effect()
        buttons = [dict(button) for button in self.buttons]
        sections = [dict(section) for section in self.sections]
        interactive = (
            {
                "type": "list",
                "body": {"text": self.text},
                "action": {"button": "Ver opções", "sections": sections},
            }
            if self.display_mode == "list"
            else {
                "type": "button",
                "body": {"text": self.text},
                "action": {"buttons": buttons},
            }
        )
        payload.update(
            {
                "text": self.text,
                "node_id": self.node_id,
                "options": [dict(option) for option in self.options],
                "buttons": buttons,
                "sections": sections,
                "display_mode": self.display_mode,
                "interactive": interactive,
            }
        )
        return payload


@dataclass(frozen=True)
class WaitChoiceAction(RuntimeAction):
    node_id: str = ""
    option_ids: tuple[str, ...] = ()
    prompt: str | None = None

    @property
    def action_type(self) -> Literal["wait_choice"]:
        return "wait_choice"

    def as_effect(self) -> dict[str, Any]:
        payload = super().as_effect()
        payload.update({"node_id": self.node_id, "option_ids": list(self.option_ids)})
        if self.prompt is not None:
            payload["prompt"] = self.prompt
        return payload


@dataclass(frozen=True)
class ScheduleDelayAction(RuntimeAction):
    job_id: UUID | None = None
    resume_node_id: str = ""
    run_at: datetime | None = None
    seconds: int | float = 0

    @property
    def action_type(self) -> Literal["schedule_delay"]:
        return "schedule_delay"

    def as_effect(self) -> dict[str, Any]:
        payload = super().as_effect()
        payload.update(
            {
                "job_id": str(self.job_id),
                "resume_node_id": self.resume_node_id,
                "run_at": self.run_at.isoformat() if self.run_at is not None else None,
                "seconds": self.seconds,
            }
        )
        return payload


@dataclass(frozen=True)
class CompleteFlowAction(RuntimeAction):
    reason: str = "completed"

    @property
    def action_type(self) -> Literal["complete_flow"]:
        return "complete_flow"

    def as_effect(self) -> dict[str, Any]:
        payload = super().as_effect()
        payload.update({"reason": self.reason})
        return payload


def action_from_effect(
    *,
    effect: dict[str, Any],
    tenant_id: UUID,
    session_id: UUID,
    external_user_id: str,
    conversation_id: UUID | None = None,
    contact_id: UUID | None = None,
) -> RuntimeAction | None:
    """Compatibility bridge for legacy dict effects produced inside V2 tests.

    The operational worker dispatches RuntimeAction instances. This helper keeps
    old executor call-sites readable while the node executors move to actions.
    """

    effect_type = effect.get("type")
    if effect_type == "send_message":
        return SendMessageAction(
            tenant_id=tenant_id,
            session_id=session_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            text=str(effect.get("text") or ""),
            metadata={k: v for k, v in effect.items() if k not in {"type", "text"}},
        )
    if effect_type == "send_media":
        media_type = str(effect.get("media_type") or "").strip().lower()
        if media_type not in {"image", "document"}:
            return None
        return SendMediaAction(
            tenant_id=tenant_id,
            session_id=session_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            media_type=media_type,
            media_url=str(effect.get("media_url") or ""),
            caption=str(effect.get("caption") or "") or None,
            filename=str(effect.get("filename") or "") or None,
            metadata={k: v for k, v in effect.items() if k not in {"type", "media_type", "media_url", "caption", "filename"}},
        )
    return None
