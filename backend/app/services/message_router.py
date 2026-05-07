from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.services.bot_service import handle_bot, handle_visual_flow_priority
from app.services.conversation_log_service import log_conversation_event
from app.services.flow_engine_service import get_active_visual_flow


def handle_incoming_message(db: Session, message: Message, conversation: Conversation):
    mode = conversation.mode or "bot"
    base_log_data = {
        "tenant_id": conversation.tenant_id,
        "conversation_id": conversation.id,
        "message": message.text,
        "mode": mode,
    }

    print(f"[MODE] {mode}")
    print(f"[FLOW] node={conversation.current_node_id}")
    print(
        f"[FLOW ROUTING] session_found={bool(conversation.current_node_id)} "
        f"session_id={conversation.current_node_id or 'none'}"
    )

    if mode == "flow":
        if conversation.current_node_id:
            print("[MODE PROTECTED] mantendo modo flow durante execução")
        else:
            print("[FLOW MODE] sem node ativo, mantendo flow e tentando retomar")

        print("[FLOW MODE] usuário em fluxo")
        result = handle_visual_flow_priority(db=db, message=message, conversation=conversation)
        base_log_data["mode"] = conversation.mode or mode
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

    if mode == "bot":
        active_flow = get_active_visual_flow(db=db, tenant_id=conversation.tenant_id)
        print(
            f"[FLOW ROUTING] active_flow_found={bool(active_flow)} "
            f"flow_id={active_flow.id if active_flow else 'none'}"
        )
        if active_flow:
            print("[FLOW MODE] iniciando fluxo")
            conversation.mode = "flow"
            db.commit()
            db.refresh(conversation)
            print("[MODE SET] flow")
            result = handle_visual_flow_priority(db=db, message=message, conversation=conversation)
            used_fallback = not bool(result and result.get("response"))
            print(
                f"[FLOW ROUTING] using_fallback={used_fallback} "
                f"reason={'flow_engine_empty_response' if used_fallback else 'none'}"
            )
            if used_fallback:
                print("[BOT FALLBACK] executando bot")
                result = handle_bot(db, message, conversation)
            base_log_data["mode"] = conversation.mode or mode
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
        print("[FLOW ROUTING] using_fallback=true reason=no_active_flow")
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
