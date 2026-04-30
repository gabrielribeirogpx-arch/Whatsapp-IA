from __future__ import annotations


def normalize_input(text: str) -> str:
    return (text or "").lower().strip()


def classify_intent(text: str) -> str:
    text = normalize_input(text)

    if any(x in text for x in ["preço", "valor", "plano", "quanto custa"]):
        return "PRICE"

    if any(x in text for x in ["comprar", "contratar", "quero", "interesse"]):
        return "BUY"

    if any(x in text for x in ["como funciona", "funciona", "o que é"]):
        return "INFO"

    if any(x in text for x in ["suporte", "ajuda", "erro", "problema"]):
        return "SUPPORT"

    if any(x in text for x in ["oi", "ola", "olá", "bom dia", "boa tarde", "boa noite"]):
        return "GREETING"

    return "FALLBACK"


def route_intent(intent: str) -> str:
    if intent == "GREETING":
        return "Fala! 👋 Posso te ajudar com preço, funcionamento ou contratação."

    if intent == "PRICE":
        return "Hoje o Wazza API começa a partir de R$XX/mês. Quer ver como funciona?"

    if intent == "BUY":
        return "Perfeito 🔥 Vou te mostrar como começar agora. Quer ver o passo a passo?"

    if intent == "INFO":
        return "O Wazza API automatiza seu WhatsApp e conduz o cliente até a venda."

    if intent == "SUPPORT":
        return "Me explica o problema que você está enfrentando que eu te ajudo."

    return "Não entendi 😅 Me diga: preço, como funciona ou suporte."
