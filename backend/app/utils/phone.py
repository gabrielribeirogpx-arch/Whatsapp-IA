import re


def normalize_phone(phone: str) -> str:
    # remover espaços, +, -, ()
    phone = re.sub(r"\D", "", phone or "")

    # garantir padrão brasileiro
    if phone and not phone.startswith("55"):
        phone = "55" + phone

    return phone
