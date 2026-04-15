import os

from google import genai


def generate_response(message: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "Olá! Recebi sua mensagem, já vou te responder."

    client = genai.Client(api_key=api_key)

    prompt = f"""
    Você é um atendente comercial profissional.
    Seja direto, educado e focado em conversão.

    Cliente: {message}
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = getattr(response, "text", None)
        return text.strip() if text else "Não consegui responder agora, tenta de novo?"
    except Exception:
        return "Olá! Recebi sua mensagem, já vou te responder."


def classificar_lead(mensagem: str) -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "morno"

    client = genai.Client(api_key=api_key)

    prompt = f"""
    Classifique o nível de interesse do cliente:

    Mensagem:
    "{mensagem}"

    Responda apenas com:
    - frio
    - morno
    - quente
    """

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = getattr(response, "text", None)
        return text.strip().lower() if text else "morno"
    except Exception:
        return "morno"
