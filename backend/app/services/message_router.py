from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.services.bot_service import handle_bot, handle_visual_flow_priority
from app.services.conversation_log_service import log_conversation_event
from app.services.flow_engine_service import tenant_has_active_visual_flow


def handle_incoming_message(db: Session, message: Message, conversation: Conversation):
    mode = conversation.mode or "human"
    base_log_data = {
        "tenant_id": conversation.tenant_id,
        "conversation_id": conversation.id,
        "message": message.text,
        "mode": mode,
    }

    print(f"[ROUTER] mode={mode}")

    if mode == "human":
        print("[ROUTER] human mode ativo: mensagem salva sem resposta automática")
        log_conversation_event(
            db,
            {
                **base_log_data,
                "flow_step": conversation.conversation_state,
            },
        )
        return None
    elif mode == "bot":
        has_active_visual_flow = tenant_has_active_visual_flow(db=db, tenant_id=conversation.tenant_id)
        if has_active_visual_flow:
            print("[FLOW PRIORITY] executando fluxo antes do bot")
            result = handle_visual_flow_priority(db=db, message=message, conversation=conversation)
            log_conversation_event(
                db,
                {
                    **base_log_data,
                    "intent": result.get("intent"),
                    "matched_rule": result.get("matched_rule"),
                    "flow_step": conversation.conversation_state,
                    "used_fallback": bool(result.get("fallback")),
                    "response": result.get("response"),
                },
            )
            return True

        print("[BOT FALLBACK] executando bot")
        result = handle_bot(db, message, conversation)
        print(f"[BOT] matched={bool(result)} mode={conversation.mode}")
        if not result:
            log_conversation_event(
                db,
                {
                    **base_log_data,
                    "flow_step": conversation.conversation_state,
                },
            )
            return None
        log_conversation_event(
            db,
            {
                **base_log_data,
                "intent": result.get("intent"),
                "matched_rule": result.get("matched_rule"),
                "flow_step": conversation.conversation_state,
                "used_fallback": bool(result.get("fallback")),
                "response": result.get("response"),
            },
        )
        return True

    log_conversation_event(
        db,
        {
            **base_log_data,
            "flow_step": conversation.conversation_state,
        },
    )
    return None
