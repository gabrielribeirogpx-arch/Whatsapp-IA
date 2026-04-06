import logging
import os
from typing import Sequence

from openai import OpenAI

from backend.app.models import AIConfig, Message

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "Você é um atendente profissional de WhatsApp para uma empresa de tecnologia. "
    "Responda de forma objetiva, cordial e com foco em resolver o problema do cliente. "
    "Se faltar contexto, faça perguntas curtas para avançar no atendimento."
)


def _build_context_messages(history: Sequence[Message], inbound_text: str, system_prompt: str) -> list[dict[str, str]]:
    context: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in history:
        role = "assistant" if item.from_me else "user"
        context.append({"role": role, "content": item.content})
    context.append({"role": "user", "content": inbound_text})
    return context


def gerar_resposta(texto: str, history: Sequence[Message] | None = None, ai_config: AIConfig | None = None) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Olá! Recebi sua mensagem e já vou te ajudar da melhor forma possível."

    prompt = ai_config.system_prompt if ai_config and ai_config.system_prompt else DEFAULT_SYSTEM_PROMPT
    model = ai_config.model if ai_config and ai_config.model else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature = ai_config.temperature if ai_config else 0.4

    try:
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            messages=_build_context_messages(history or [], texto, prompt),
            temperature=temperature,
        )
        content = completion.choices[0].message.content
        return content.strip() if content else "Obrigado pela mensagem!"
    except Exception:
        logger.exception("Erro ao gerar resposta de IA")
        return "Obrigado pela mensagem! Nosso time está avaliando sua solicitação."


def generate_ai_response(message: str) -> str:
    return gerar_resposta(message)
