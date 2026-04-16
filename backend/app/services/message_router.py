def handle_incoming_message(db, message, conversation):
    mode = conversation.mode or "human"
    print(f"[ROUTER] mode={mode}")

    if mode == "human":
        return

    elif mode == "bot":
        return

    elif mode == "ai":
        return

    return
