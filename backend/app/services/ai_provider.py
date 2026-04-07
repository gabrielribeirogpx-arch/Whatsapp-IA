import os
import google.generativeai as genai

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise Exception("GEMINI_API_KEY não configurada")

genai.configure(api_key=GEMINI_API_KEY)

model = genai.GenerativeModel("gemini-pro")


def generate_response(message: str) -> str:
    try:
        response = model.generate_content(
            f"""
            Você é um atendente comercial profissional.
            Seja direto, educado e focado em conversão.

            Cliente: {message}
            """
        )
        return response.text
    except Exception as e:
        print("Erro Gemini:", e)
        return "Olá! Recebi sua mensagem, já vou te responder."
