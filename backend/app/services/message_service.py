from typing import Any


def generate_response(message: str) -> str:
    return "Recebi sua mensagem"


def process_message(payload: dict[str, Any]) -> list[str]:
    entries = payload.get("entry", [])
    responses: list[str] = []

    for entry in entries:
        changes = entry.get("changes", [])
        for change in changes:
            value = change.get("value", {})
            messages = value.get("messages", [])
            for message in messages:
                text = message.get("text", {}).get("body")
                if text:
                    print(text)
                    response = generate_response(text)
                    print(response)
                    responses.append(response)

    return responses
