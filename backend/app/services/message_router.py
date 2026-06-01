from sqlalchemy.orm import Session

from sqlalchemy import select

from app.models import Conversation, Flow, Message
from app.services.bot_service import handle_bot, handle_visual_flow_priority
from app.services.conversation_log_service import log_conversation_event
from app.services.flow_engine_service import get_active_visual_flow, is_flow_trigger
from app.services.flow_session_service import FlowSessionService




def _resolve_triggered_flow(db: Session, tenant_id, incoming_text: str, *, allow_default_auto_start: bool = False):
    flows = db.execute(
        select(Flow)
        .where(
            Flow.tenant_id == tenant_id,
            Flow.is_active.is_(True),
            Flow.is_deleted.is_(False),
            Flow.deleted_at.is_(None),
            Flow.status.in_(["active", "published"]),
        )
        .order_by(Flow.priority.desc(), Flow.created_at.asc(), Flow.id.asc())
    ).scalars().all()

    default_flow = None
    for flow in flows:
        trigger_type = (flow.trigger_type or "default").strip().lower()
        if trigger_type == "keyword" and is_flow_trigger(flow, incoming_text):
            return flow
        if trigger_type == "default" and default_flow is None:
            default_flow = flow

    if default_flow and is_flow_trigger(default_flow, incoming_text):
        return default_flow
    if default_flow and allow_default_auto_start:
        return default_flow
    return None
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
    active_flow_for_state = get_active_visual_flow(db=db, tenant_id=conversation.tenant_id)
    if active_flow_for_state:
        state = session_service.get_runtime_session_state(
            tenant_id=conversation.tenant_id,
            phone=conversation.phone_number,
            flow_id=active_flow_for_state.id,
        )
        latest_session = state["session"]
        session_node_id = getattr(latest_session, "current_node_id", None) if latest_session else None
        variables_node_id = (
            latest_session.variables.get("current_node_id")
            if latest_session and isinstance(latest_session.variables, dict)
            else None
        )
        context_node_id = (
            (conversation.context or {}).get("flow_current_node_id")
            if isinstance(conversation.context, dict)
            else None
        )
        resolved_node_id = session_node_id or variables_node_id or context_node_id
        resolution_source = "session" if session_node_id else ("variables" if variables_node_id else ("context" if context_node_id else "none"))
        if session_node_id:
            print(f"[FLOW CONTINUE USING_SESSION_NODE] session_node_id={session_node_id}")
        if resolved_node_id:
            print(f"[CONVERSATION CURRENT_NODE SKIPPED_FOR_VERSIONED_FLOW] resolved_node_id={resolved_node_id} source={resolution_source}")
            print(
                f"[SESSION NODE BEFORE] session_id={getattr(latest_session, 'id', None)} "
                f"current_node_id={session_node_id} flow_current_node_id={context_node_id} "
                f"node_id_executado=None next_node_id={resolved_node_id} "
                f"status={getattr(latest_session, 'status', None)} reason=message_router_context_sync"
            )
            if not isinstance(conversation.context, dict):
                conversation.context = {}
            conversation.context["flow_current_node_id"] = str(resolved_node_id)
            print(
                f"[SESSION NODE AFTER] session_id={getattr(latest_session, 'id', None)} "
                f"current_node_id={session_node_id} flow_current_node_id={conversation.context.get('flow_current_node_id')} "
                f"node_id_executado=None next_node_id={resolved_node_id} "
                f"status={getattr(latest_session, 'status', None)} reason=message_router_context_sync"
            )
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
            print(
                f"[SESSION NODE PERSIST] session_id={getattr(latest_session, 'id', None)} "
                f"current_node_id={session_node_id} flow_current_node_id={(conversation.context or {}).get('flow_current_node_id') if isinstance(conversation.context, dict) else None} "
                f"node_id_executado=None next_node_id={resolved_node_id} "
                f"status={getattr(latest_session, 'status', None)} reason=message_router_context_sync"
            )
        elif not resolved_node_id and session_node_id:
            print("[FLOW CONTINUE USING_SESSION_NODE] keeping session current_node_id precedence")
        if resolution_source == "context" and session_node_id:
            print("[FLOW CONTINUE USING_SESSION_NODE] context_node_ignored_due_to_session_precedence=true")

    def _check_finalized_flow_block(active_flow):
        if not active_flow:
            return False
        state = session_service.get_runtime_session_state(
            tenant_id=conversation.tenant_id,
            phone=conversation.phone_number,
            flow_id=active_flow.id,
        )
        latest_session = state["session"]
        session_status = state["status"]
        session_exists = state["exists"]
        session_active = state["is_active"]
        session_finalized = state["is_finalized"]
        print(
            f"[FLOW ROUTING] session_exists={session_exists} "
            f"session_active={session_active} "
            f"session_finalized={session_finalized} "
            f"session_id={getattr(latest_session, 'id', 'none')}"
        )
        if not session_finalized:
            return False

        incoming_text = message.text or ""
        if is_flow_trigger(active_flow, incoming_text):
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
        result = handle_visual_flow_priority(db=db, message=message, conversation=conversation, session_node_id=session_node_id)
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
        incoming_text = message.text or ""
        active_flow = _resolve_triggered_flow(db=db, tenant_id=conversation.tenant_id, incoming_text=incoming_text, allow_default_auto_start=False)
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
            result = handle_visual_flow_priority(db=db, message=message, conversation=conversation, session_node_id=session_node_id)
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
