from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.services.bot_service import handle_bot, handle_visual_flow_priority
from app.services.conversation_log_service import log_conversation_event
from app.services.flow_engine_service import get_active_visual_flow, is_explicit_start_trigger
from app.services.flow_session_service import FlowSessionService


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

    session_service = FlowSessionService(db)

    def _check_finalized_flow_block(active_flow):
        if not active_flow:
            return False
        latest_session = session_service.get_latest_session_for_flow(
            tenant_id=conversation.tenant_id,
            user_identifier=conversation.phone_number,
            flow_id=active_flow.id,
        )
        session_status = ((getattr(latest_session, "status", "") or "").strip().lower())
        session_exists = latest_session is not None
        session_finalized = session_status in {"completed", "finalized", "expired"}
        session_active = session_exists and not session_finalized
        print(
            f"[FLOW ROUTING] session_exists={session_exists} "
            f"session_active={session_active} "
            f"session_finalized={session_finalized} "
            f"session_id={getattr(latest_session, 'id', 'none')}"
        )
        if not session_finalized:
            return False

        incoming_text = message.text or ""
        if is_explicit_start_trigger(incoming_text):
            print(
                "[ROUTER EXPLICIT FLOW RESTART] "
                f"tenant_id={conversation.tenant_id} "
                f"phone={conversation.phone_number} "
                f"flow_id={active_flow.id} "
                f"session_id={latest_session.id} "
                f"status={session_status} "
                f"incoming_text={incoming_text}"
            )
            return False

        print(
            "[ROUTER FINALIZED FLOW IGNORE] "
            f"tenant_id={conversation.tenant_id} "
            f"phone={conversation.phone_number} "
            f"flow_id={active_flow.id} "
            f"session_id={latest_session.id} "
            f"status={session_status} "
            f"incoming_text={incoming_text}"
        )
        return True

    if mode == "flow":
        active_flow = get_active_visual_flow(db=db, tenant_id=conversation.tenant_id)
        if _check_finalized_flow_block(active_flow):
            return None

        print("[FLOW MODE LOCK] mode=flow never_switch_to_bot=true")
        if conversation.current_node_id:
            print("[MODE PROTECTED] mantendo modo flow durante execução")
        else:
            print("[FLOW MODE] sem node ativo, mantendo flow e tentando retomar")

        print("[FLOW MODE] usuário em fluxo")
        result = handle_visual_flow_priority(db=db, message=message, conversation=conversation)
        if not result or not result.get("response"):
            print("[LEGACY FALLBACK HARD BLOCKED]")
            return None
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
            if _check_finalized_flow_block(active_flow):
                return None
            print("[FLOW MODE] iniciando fluxo")
            conversation.mode = "flow"
            db.commit()
            db.refresh(conversation)
            print("[MODE SET] flow")
            result = handle_visual_flow_priority(db=db, message=message, conversation=conversation)
            if not result or not result.get("response"):
                print("[LEGACY FALLBACK HARD BLOCKED]")
                return None
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
