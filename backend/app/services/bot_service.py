from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotRule, Conversation, Message, Tenant
from app.services.flow_orchestrator import handle_flow
from app.services.whatsapp_service import WhatsAppConfigError, enviar_mensagem
from app.utils.text import normalize_text, tokenize

STATE_INICIO = "inicio"
STATE_ESCOLHA_AREA = "escolha_area"
STATE_TIPO_ATENDIMENTO = "tipo_atendimento"
STATE_APRESENTANDO_VALOR = "apresentando_valor"
STATE_APRESENTANDO_PLANOS = "apresentando_planos"
STATE_ESCOLHA_PLANO = "escolha_plano"
STATE_FECHAMENTO = "fechamento"


def _set_state(conversation: Conversation, new_state: str | None) -> None:
    previous_state = conversation.conversation_state or "sem_estado"
    next_state = new_state or "sem_estado"
    print(f"[STATE TRANSITION] {previous_state} → {next_state}")
    conversation.conversation_state = new_state


def _state_fallback_response() -> str:
    return (
        "Me confirma rapidinho 👇\n"
        "Você quer:\n"
        "1️⃣ Ver planos\n"
        "2️⃣ Entender como funciona"
    )


def _handle_state_machine(conversation: Conversation, incoming_text: str) -> tuple[str | None, bool]:
    message_normalized = normalize_text(incoming_text)
    state = conversation.conversation_state or STATE_INICIO
    print(f"[STATE] atual={state}")

    if state == STATE_INICIO:
        _set_state(conversation, STATE_ESCOLHA_AREA)
        return ("Olá! Pra te atender melhor, você quer falar com vendas, suporte ou atendimento?", True)

    if state == STATE_ESCOLHA_AREA:
        if "vendas" in message_normalized or "suporte" in message_normalized or "atendimento" in message_normalized:
            _set_state(conversation, STATE_TIPO_ATENDIMENTO)
            return ("Perfeito 👌 Você prefere atendimento manual ou automático?", True)
        if message_normalized in {"sim", "quero"}:
            return ("Show! Você quer seguir com vendas, suporte ou atendimento?", True)
        return (_state_fallback_response(), True)

    if state == STATE_TIPO_ATENDIMENTO:
        if "manual" in message_normalized:
            _set_state(conversation, STATE_APRESENTANDO_VALOR)
            return ("Perfeito! Atendimento manual funciona bem para começar. Quer ver os planos agora?", True)
        if "automatico" in message_normalized or "automático" in message_normalized:
            _set_state(conversation, STATE_APRESENTANDO_VALOR)
            return ("Top 🔥 automação total! Quer ver os planos agora?", True)
        if message_normalized in {"sim", "quero"}:
            return ("Você prefere manual ou automático?", True)
        return (_state_fallback_response(), True)

    if state == STATE_APRESENTANDO_VALOR:
        _set_state(conversation, STATE_APRESENTANDO_PLANOS)
        return ("Quer ver os planos? Posso te mostrar as opções agora.", True)

    if state == STATE_APRESENTANDO_PLANOS:
        if message_normalized in {"sim", "quero"}:
            return (
                "Perfeito! Temos algumas opções de planos ativas para você.\n\n"
                "Qual você quer conhecer melhor?",
                True,
            )
        if "basico" in message_normalized or "básico" in message_normalized:
            _set_state(conversation, STATE_ESCOLHA_PLANO)
            return ("Ótima escolha! Esse plano é enxuto e eficiente. Quer fechar com ele?", True)
        if "essencial" in message_normalized:
            _set_state(conversation, STATE_ESCOLHA_PLANO)
            return ("Excelente! Esse plano costuma ser muito escolhido. Quer fechar com ele?", True)
        if "pro" in message_normalized:
            _set_state(conversation, STATE_ESCOLHA_PLANO)
            return ("Perfeito! Esse plano entrega automação completa. Quer fechar com ele?", True)
        if "plano" in message_normalized or "planos" in message_normalized:
            return (
                "Temos planos ativos disponíveis para seu tenant.\n\n"
                "Qual você quer escolher?",
                True,
            )
        return (_state_fallback_response(), True)

    if state == STATE_ESCOLHA_PLANO:
        if message_normalized in {"sim", "quero", "fechar"}:
            _set_state(conversation, STATE_FECHAMENTO)
            return ("Fechou! 🎉 Vou te passar os próximos passos para conclusão do atendimento.", True)
        if "basico" in message_normalized or "básico" in message_normalized or "essencial" in message_normalized or "pro" in message_normalized:
            _set_state(conversation, STATE_FECHAMENTO)
            return ("Perfeito, plano escolhido! 🎯 Posso seguir com o fechamento?", True)
        return (_state_fallback_response(), True)

    if state == STATE_FECHAMENTO:
        if message_normalized in {"sim", "quero", "ok", "fechar"}:
            _set_state(conversation, None)
            return ("Maravilha! Atendimento concluído ✅ Se precisar, é só me chamar.", True)
        return ("Estamos no fechamento. Se estiver tudo certo, me responde 'sim' que eu concluo para você.", True)

    _set_state(conversation, STATE_ESCOLHA_AREA)
    return ("Vamos retomar do início. Você quer vendas, suporte ou atendimento?", True)


def detect_intent(message: str) -> str | None:
    normalized_message = normalize_text(message)

    if "plano" in normalized_message or "planos" in normalized_message:
        return "planos"

    if (
        "preco" in normalized_message
        or "valor" in normalized_message
        or "quanto custa" in normalized_message
    ):
        return "preco"

    if (
        "oi" in normalized_message
        or "ola" in normalized_message
        or "bom dia" in normalized_message
    ):
        return "saudacao"

    if (
        "contratar" in normalized_message
        or "fechar" in normalized_message
        or "assinar" in normalized_message
    ):
        return "fechamento"

    return None


def update_lead_score(conversation: Conversation, message: str) -> None:
    normalized_message = normalize_text(message)
    score_increment = 0

    if "preco" in normalized_message:
        score_increment += 10

    if "plano" in normalized_message:
        score_increment += 20

    if "comparar" in normalized_message or "qual melhor" in normalized_message:
        score_increment += 15

    if "contratar" in normalized_message or "fechar" in normalized_message:
        score_increment += 50

    conversation.lead_score = min(100, (conversation.lead_score or 0) + score_increment)


def update_context(conversation: Conversation, intent: str | None) -> None:
    if intent is None:
        return

    now = datetime.utcnow()
    conversation.last_intent = intent
    conversation.last_intent_at = now

    history = list(conversation.intent_history or [])
    history.append({"intent": intent, "ts": now.isoformat() + "Z"})
    conversation.intent_history = history[-5:]


def get_active_intent(conversation: Conversation) -> str | None:
    now = datetime.utcnow()
    if (
        conversation.last_intent
        and conversation.last_intent_at
        and now - conversation.last_intent_at < timedelta(minutes=10)
    ):
        return conversation.last_intent

    recent_items = (conversation.intent_history or [])[-3:]
    intents = [item.get("intent") for item in recent_items if isinstance(item, dict) and item.get("intent")]
    if not intents:
        return None

    frequency = Counter(intents)
    max_freq = max(frequency.values())
    most_frequent = {intent for intent, count in frequency.items() if count == max_freq}

    for item in reversed(recent_items):
        if isinstance(item, dict) and item.get("intent") in most_frequent:
            return item["intent"]

    return None


def _last_bot_message_within_cooldown(db: Session, conversation: Conversation, seconds: int = 10) -> bool:
    last_bot_message = (
        db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation.id,
                Message.tenant_id == conversation.tenant_id,
                Message.from_me.is_(True),
            )
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not last_bot_message:
        return False

    return datetime.utcnow() - last_bot_message.created_at < timedelta(seconds=seconds)


def _match_score(rule: BotRule, incoming_text: str) -> tuple[int, int] | None:
    trigger_normalized = normalize_text(rule.trigger)
    message_normalized = normalize_text(incoming_text)

    if not trigger_normalized or not message_normalized:
        return None

    if rule.match_type == "exact":
        score = 100 if trigger_normalized == message_normalized else 0
        if score:
            print(f"[BOT MATCH] trigger={trigger_normalized} score={score}")
            return (3, score)
        return None

    trigger_tokens = tokenize(trigger_normalized)
    message_tokens = set(tokenize(message_normalized))
    token_score = sum(1 for token in trigger_tokens if token in message_tokens)

    phrase_match = trigger_normalized in message_normalized
    if phrase_match:
        score = max(token_score, len(trigger_tokens), 1)
        print(f"[BOT MATCH] trigger={trigger_normalized} score={score}")
        return (2, score)

    if token_score >= 1:
        print(f"[BOT MATCH] trigger={trigger_normalized} score={token_score}")
        return (1, token_score)

    return None


def _create_outbound_message(db: Session, conversation_id, tenant_id, text: str) -> Message:
    reply_message = Message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        text=text,
        from_me=True,
        created_at=datetime.utcnow(),
    )
    db.add(reply_message)
    return reply_message


def _infer_last_bot_question_from_response(response: str) -> str | None:
    normalized = normalize_text(response)
    if "quer ver os planos" in normalized:
        return "interesse_planos"
    if "manual ou automatico" in normalized or "manual ou automático" in normalized:
        return "tipo_atendimento"
    if "qual voce quer conhecer melhor" in normalized or "qual você quer conhecer melhor" in normalized:
        return "plano"
    if "agora me diz" in normalized:
        return "follow_up"
    if "?" in response:
        return "follow_up"
    return None


def handle_bot(db: Session, message: Message, conversation) -> dict[str, str | bool | None] | None:
    print(f"[MODE CHECK] current mode={conversation.mode}")
    if conversation.mode != "bot":
        print("[BOT] envio automático bloqueado: modo diferente de bot")
        return False

    tenant = db.execute(select(Tenant).where(Tenant.id == conversation.tenant_id)).scalars().first()

    flow_response = handle_flow(db=db, message=message, conversation=conversation)
    selected_response = flow_response if flow_response else None
    matched_rule: str | None = "flow_orchestrator" if flow_response else None

    message_normalized = normalize_text(message.text)
    intent = detect_intent(message_normalized)
    update_context(conversation, intent)
    print("[INTENT DETECTED]", intent)
    print("[INTENT HISTORY]", conversation.intent_history)

    update_lead_score(conversation, message.text)
    print("[LEAD SCORE]", conversation.lead_score)

    state_response: str | None = None
    state_handled = bool(selected_response)
    if conversation.conversation_state and not selected_response:
        state_response, state_handled = _handle_state_machine(conversation, message.text)
        selected_response = state_response if (state_handled and state_response) else None
        if selected_response:
            matched_rule = "state_machine"

    if not state_handled:
        rules = (
            db.execute(
                select(BotRule)
                .where(BotRule.tenant_id == conversation.tenant_id)
                .order_by(BotRule.created_at.asc(), BotRule.id.asc())
            )
            .scalars()
            .all()
        )
        best_match: tuple[int, int] | None = None
        for rule in rules:
            match = _match_score(rule, message.text)
            if not match:
                continue

            if best_match is None or match > best_match:
                best_match = match
                selected_response = rule.response
                matched_rule = rule.trigger

    if not selected_response and not state_handled:
        active_intent = get_active_intent(conversation)
        print("[ACTIVE INTENT]", active_intent)
        if active_intent == "planos":
            selected_response = "Temos planos ativos para você. Quer ver os detalhes de algum?"
            matched_rule = "active_intent:planos"
        elif active_intent == "preco":
            selected_response = "Os valores variam por plano. Quer que eu te explique cada um?"
            matched_rule = "active_intent:preco"
        elif active_intent == "fechamento":
            selected_response = "Posso te ajudar a fechar agora. Quer seguir com qual plano?"
            matched_rule = "active_intent:fechamento"
        elif active_intent == "saudacao":
            selected_response = "Olá! Em que posso te ajudar hoje?"
            matched_rule = "active_intent:saudacao"
        else:
            print("[BOT FALLBACK]")
            selected_response = "Não entendi muito bem 😅\n\nVocê pode me dizer melhor se quer:\n1️⃣ Ver planos\n2️⃣ Entender como funciona\n3️⃣ Falar com atendente"
            matched_rule = "fallback_default"

    if not selected_response:
        return None

    if _last_bot_message_within_cooldown(db=db, conversation=conversation, seconds=10):
        conversation.updated_at = datetime.utcnow()
        return None

    if tenant:
        try:
            print(f"[MODE CHECK] current mode={conversation.mode}")
            enviar_mensagem(
                conversation.phone_number,
                selected_response,
                token=tenant.whatsapp_token,
                phone_number_id=tenant.phone_number_id,
            )
        except WhatsAppConfigError:
            pass

    _create_outbound_message(
        db=db,
        conversation_id=conversation.id,
        tenant_id=conversation.tenant_id,
        text=selected_response,
    )
    inferred_question = _infer_last_bot_question_from_response(selected_response)
    if inferred_question:
        conversation.last_bot_question = inferred_question
    if not message.from_me:
        conversation.last_bot_triggered_message_id = message.id
    conversation.updated_at = datetime.utcnow()
    return {
        "response": selected_response,
        "matched_rule": matched_rule,
        "intent": intent,
        "fallback": bool(matched_rule == "fallback_default"),
    }


def get_last_message(db: Session, conversation_id, tenant_id) -> Message | None:
    return (
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.tenant_id == tenant_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def handle_bot_activation(db: Session, conversation: Conversation) -> bool:
    if conversation.mode != "bot":
        return False

    last_message = get_last_message(db, conversation.id, conversation.tenant_id)
    if not last_message:
        return False

    if last_message.from_me:
        return False

    if conversation.last_bot_triggered_message_id == last_message.id:
        return False

    return bool(handle_bot(db=db, message=last_message, conversation=conversation))
