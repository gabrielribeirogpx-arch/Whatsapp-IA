from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.services.integration_connection_service import IntegrationConnectionService

PROVIDER = "suitable"
BASE_URL = "https://api.suitable.com.br"
NOT_CONNECTED_MESSAGE = "Suitable não está conectado para este workspace."
logger = logging.getLogger(__name__)


def stable_json(payload: Any) -> str:
    return json.dumps(payload if isinstance(payload, (dict, list)) else {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def suitable_fingerprint(tool_name: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(f"{tool_name}:{stable_json(payload)}".encode("utf-8")).hexdigest()


class SuitableService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | str, *, base_url: str | None = None) -> None:
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.connection_service = IntegrationConnectionService(db)
        self.base_url = (base_url or BASE_URL).rstrip("/")

    def _connection(self) -> IntegrationConnection | None:
        conn = self.connection_service.get_active_connection(self.tenant_id, PROVIDER)
        return conn if conn and conn.auth_type == "api_key" else None

    def _api_key(self) -> str | None:
        conn = self._connection()
        if not conn:
            return None
        return IntegrationConnectionService.decrypt_credential(conn.api_key_encrypted)

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> tuple[bool, Any, int]:
        api_key = self._api_key()
        if not api_key:
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        try:
            resp = requests.request(method, f"{self.base_url}{path}", headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json", "Content-Type": "application/json"}, json=json_body, timeout=15)
        except requests.RequestException as exc:
            logger.info("event=SUITABLE_REQUEST_FAILED tenant_id=%s tool_name=suitable status=request_error error=%s", self.tenant_id, type(exc).__name__)
            return False, {"message": "Falha ao chamar Suitable.", "error": type(exc).__name__}, 0
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:500]
            return False, {"message": "Erro ao chamar Suitable.", "status_code": resp.status_code, "api_error": body}, resp.status_code
        try:
            data = {} if not resp.content else resp.json()
        except Exception:
            data = {"raw": resp.text[:500]}
        return True, data, resp.status_code

    @staticmethod
    def normalize_phone(phone: Any) -> str:
        digits = re.sub(r"\D+", "", str(phone or ""))
        if digits.startswith("55"):
            return digits
        if len(digits) in (10, 11):
            return "55" + digits
        if len(digits) in (8, 9):
            return "5516" + digits
        return digits

    @staticmethod
    def _money(value: Any) -> float:
        try:
            return float(Decimal(str(value)))
        except (InvalidOperation, TypeError, ValueError):
            return 0.0

    def build_order_payload(self, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
        if not str(customer.get("name") or "").strip():
            return None, "Nome do cliente é obrigatório."
        phone = self.normalize_phone(customer.get("phone"))
        if not phone:
            return None, "Telefone do cliente é obrigatório."
        products_in = payload.get("products") if isinstance(payload.get("products"), list) else []
        if not products_in:
            return None, "Informe ao menos 1 produto."
        products: list[dict[str, Any]] = []
        products_total = 0.0
        for item in products_in:
            if not isinstance(item, dict):
                return None, "Produto inválido."
            quantity = self._money(item.get("quantity"))
            unit_price = self._money(item.get("unit_price"))
            if quantity <= 0:
                return None, "A quantidade do produto deve ser maior que zero."
            if unit_price <= 0:
                return None, "O preço unitário do produto deve ser maior que zero."
            products_total += quantity * unit_price
            products.append({**item, "quantity": quantity, "unit_price": unit_price, "total": quantity * unit_price})
        order_type = str(payload.get("order_type") or "delivery").strip().lower()
        address = payload.get("address") if isinstance(payload.get("address"), dict) else None
        if order_type == "delivery" and not address:
            return None, "Endereço é obrigatório para pedido delivery."
        delivery_fee = self._money(payload.get("delivery_fee"))
        return {
            "order_id": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "customer": {**customer, "phone": phone},
            "order_type": order_type,
            "comments": str(payload.get("comments") or ""),
            "address": address,
            "products": products,
            "products_total": products_total,
            "payment": {"paid": False, "generate_invoice": False, "products_total": products_total, "delivery_fee": delivery_fee, "service_fee": 0, "discount": 0, "additional": 0, "methods": payload.get("payment_methods") or []},
        }, None

    def check_key(self) -> dict[str, Any]:
        ok, data, status = self._request("GET", "/key/check/")
        if not ok:
            return {"success": False, "valid": False, "message": data.get("message") or "Chave Suitable inválida.", "status_code": status or None}
        return {"success": True, "valid": True}

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        built, error = self.build_order_payload(kwargs)
        if error:
            return {"ok": False, "message": error}
        assert built is not None
        ok, data, status = self._request("POST", "/order/upsert/", json_body=built)
        if not ok:
            return {"ok": False, **data}
        return {"ok": True, "order": data, "payload": built, "status_code": status}
