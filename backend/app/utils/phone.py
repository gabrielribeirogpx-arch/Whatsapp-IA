def normalize_phone(phone: str) -> str:
    import re

    phone = re.sub(r"\D", "", phone)

    # garante padrão internacional sem +
    if phone.startswith("0"):
        phone = phone[1:]

    if not phone.startswith("55"):
        phone = "55" + phone

    return phone
