import logging
import os
from typing import Sequence

from openai import OpenAI

from backend.app.models import AIConfig, Message

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "Você é um atendente comercial especialista em vendas via WhatsApp.\n\n"
    "Responda de forma natural, humana e personalizada.\n\n"
    "REGRAS:\n"
    "- Nunca responda genérico\n"
    "- Sempre responda baseado na mensagem\n"
    "- Seja direto e útil\n"
    '- Se for "oi", puxe conversa\n'
    "- Se for pergunta, responda direto\n\n"
    "RESULTADO:\n"
    "Resposta contextual e não repetitiva"
)



def _to_openai_messages(contexto: Sequence[Message], prompt: str, system_prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in contexto:
        role = item.role or ("assistant" if item.from_me else "user")
        content = item.message or item.content
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})
    return messages


def gerar_resposta(
    contexto: Sequence[Message] | None,
    prompt: str,
    ai_config: AIConfig | None = None,
) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Olá! Recebi sua mensagem e já vou te ajudar da melhor forma possível."

    system_prompt = ai_config.system_prompt if ai_config and ai_config.system_prompt else DEFAULT_SYSTEM_PROMPT
    model = ai_config.model if ai_config and ai_config.model else os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    temperature = ai_config.temperature if ai_config else 0.4

    try:
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=model,
            messages=_to_openai_messages(contexto or [], prompt, system_prompt),
            temperature=temperature,
        )
        content = completion.choices[0].message.content
        return content.strip() if content else "Obrigado pela mensagem!"
    except Exception:
        logger.exception("Erro ao gerar resposta de IA")
        return "Obrigado pela mensagem! Nosso time está avaliando sua solicitação."


async def generate_ai_response(prompt: str) -> str:
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Olá! Recebi sua mensagem e já vou te ajudar da melhor forma possível."

    client = genai.Client(api_key=api_key)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = getattr(response, "text", None)
        return text.strip() if text else "Não consegui responder agora, tenta de novo?"
    except Exception:
        logger.exception("Erro ao gerar resposta de IA com Gemini")
        return "Não consegui responder agora, tenta de novo?"
