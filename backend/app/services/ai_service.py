import logging
import os
from typing import Sequence

from openai import OpenAI

from backend.app.models import AIConfig, Message

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "Você é um vendedor especialista em conversão via WhatsApp. "
    "Seu objetivo é conduzir cada conversa até conversão (lead qualificado ou venda). "
    "Responda sempre de forma humana, natural, curta e direta, no estilo WhatsApp. "
    "Use o nome do cliente quando estiver disponível no contexto. "
    "Faça perguntas estratégicas para entender intenção e objetivo principal. "
    "Prenda atenção com abertura envolvente e linguagem persuasiva, sem exageros. "
    "Crie leve urgência quando fizer sentido (ex.: disponibilidade, condição por tempo limitado), "
    "de forma ética e verdadeira. "
    "Sempre avance a conversa para o próximo passo da venda com clareza."
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


async def generate_ai_response(user_message: str) -> str:
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Olá! Recebi sua mensagem e já vou te ajudar da melhor forma possível."

    client = genai.Client(api_key=api_key)

    prompt = f"""
    Você é um atendente comercial via WhatsApp.

    Cliente disse:
    "{user_message}"

    Responda de forma natural, humana e persuasiva.
    """

    try:
        response = client.models.generate_content(
            model="gemma-3-2b-it",
            contents=prompt,
        )
        text = getattr(response, "text", None)
        return text.strip() if text else "Não consegui responder agora, tenta de novo?"
    except Exception:
        logger.exception("Erro ao gerar resposta de IA com Gemini")
        return "Não consegui responder agora, tenta de novo?"
