"""Deterministic validators for the native ``data_collection`` node."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    raw_value: Any
    normalized_value: Any = None
    error: str | None = None


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _br_document(value: str, *, length: int) -> bool:
    digits = _digits(value)
    if len(digits) != length or len(set(digits)) == 1:
        return False
    if length == 11:
        weights = ((10, 9, 8, 7, 6, 5, 4, 3, 2), (11, 10, 9, 8, 7, 6, 5, 4, 3, 2))
    else:
        weights = ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    base = digits[:-2]
    for expected, weights_row in zip(digits[-2:], weights):
        remainder = sum(int(n) * w for n, w in zip(base, weights_row)) % 11
        check = "0" if remainder < 2 else str(11 - remainder)
        if expected != check:
            return False
        base += check
    return True


def _decimal(raw: str, *, currency: bool = False) -> Decimal:
    value = raw.strip()
    if currency:
        value = re.sub(r"(?i)R\$", "", value).strip()
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", value):
        raise InvalidOperation
    return Decimal(value)


def validate_data_collection(data: dict[str, Any], raw_value: Any, metadata: dict[str, Any] | None = None) -> ValidationResult:
    """Validate without fuzzy matching and return a JSON-serializable value."""
    raw = "" if raw_value is None else str(raw_value)
    value = raw.strip()
    kind = str(data.get("data_type") or "text").lower()
    if not value:
        return ValidationResult(not bool(data.get("required", True)), raw, "", "required" if data.get("required", True) else None)
    try:
        normalized: Any
        if kind == "text":
            minimum, maximum = data.get("min_length"), data.get("max_length")
            if minimum is not None and len(value) < int(minimum): raise ValueError("min_length")
            if maximum is not None and len(value) > int(maximum): raise ValueError("max_length")
            normalized = value
        elif kind == "number": normalized = float(_decimal(value)) if "." in str(_decimal(value)) else int(_decimal(value))
        elif kind == "currency": normalized = float(_decimal(value, currency=True))
        elif kind == "email":
            if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+", value): raise ValueError("email")
            normalized = value.lower() if data.get("normalize_value", True) else value
        elif kind == "phone":
            phone = ("+" if value.startswith("+") else "") + _digits(value)
            if not re.fullmatch(r"\+?[1-9]\d{7,14}", phone): raise ValueError("phone")
            normalized = phone
        elif kind == "date": normalized = datetime.strptime(value.replace("-", "/"), "%d/%m/%Y").date().isoformat()
        elif kind == "time": normalized = datetime.strptime(value, "%H:%M").strftime("%H:%M")
        elif kind in {"cpf", "cnpj"}:
            if not _br_document(value, length=11 if kind == "cpf" else 14): raise ValueError(kind)
            normalized = _digits(value)
        elif kind == "url":
            candidate = value if "://" in value else f"https://{value}"
            parsed = urlparse(candidate)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc or "." not in parsed.netloc: raise ValueError("url")
            normalized = candidate
        elif kind == "boolean":
            folded = value.casefold()
            if folded in {"sim", "yes", "true"}: normalized = True
            elif folded in {"não", "nao", "no", "false"}: normalized = False
            else: raise ValueError("boolean")
        elif kind == "choice":
            reply_id = next((str((metadata or {}).get(key)).strip() for key in ("button_reply_id", "interactive_reply_id", "selected_row_id", "row_id", "sourceHandle") if (metadata or {}).get(key)), "")
            options = [option for option in data.get("options", []) if isinstance(option, dict)]
            matched = next((option for option in options if str(option.get("id")) == reply_id), None)
            if matched is None and data.get("allow_custom_value"):
                matched = next((option for option in options if value == str(option.get("label") or option.get("value") or "")), None)
                normalized = matched.get("value") if matched else value
            elif matched is not None: normalized = matched.get("value")
            else: raise ValueError("choice")
        else: raise ValueError("unsupported_type")
        return ValidationResult(True, raw, normalized)
    except (ValueError, InvalidOperation, OverflowError):
        return ValidationResult(False, raw, None, f"invalid_{kind}")
