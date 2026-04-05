import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)


def gerar_resposta(texto: str) -> str:
    """
    Estrutura preparada para integração futura com provedores de IA (OpenAI/Gemini).
    Atualmente retorna fallback simples quando não há chave configurada.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "Olá! Recebi sua mensagem e em breve te ajudo com mais detalhes."

    try:
        client = OpenAI(api_key=api_key)
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[
                {
                    "role": "system",
                    "content": "Você é um atendente cordial de WhatsApp para uma empresa SaaS.",
                },
                {"role": "user", "content": texto},
            ],
            temperature=0.5,
        )
        content = completion.choices[0].message.content
        return content.strip() if content else "Obrigado pela mensagem!"
    except Exception:
        logger.exception("Erro ao gerar resposta de IA")
        return "Obrigado pela mensagem! Nosso time está avaliando sua solicitação."


def generate_ai_response(message: str) -> str:
    """Compatibilidade retroativa com código existente."""
    return gerar_resposta(message)
