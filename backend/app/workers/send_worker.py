from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import time
import uuid
from functools import lru_cache
from typing import Any

from rq import get_current_job

from app.db.session import SessionLocal
from app.core.redis_client import get_redis_client
from sqlalchemy import select

from app.models import Tenant
from app.models.conversation import Conversation
from app.models.message import Message
from app.services.idempotency_service import register_processed_message
from app.services.message_origin_trace import log_message_origin_trace
from app.services.whatsapp_message_service import (
    mark_provider_auth_error,
    resolve_active_meta_provider_credentials,
    send_buttons_message_via_meta,
    send_interactive_list_via_meta,
    send_text_message_via_meta,
)
from app.services.whatsapp_credentials_service import WhatsAppCredentialsNotConfiguredError, get_tenant_whatsapp_credentials
from app.integrations.meta.meta_cloud_client import MetaApiError

logger = logging.getLogger(__name__)


def _payload_summary(payload: Any, limit: int = 1200) -> str:
    try:
        encoded = json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        encoded = str(payload)
    return encoded[:limit] + ("..." if len(encoded) > limit else "")


SEND_LOCK_TTL_SECONDS = int(os.getenv("SEND_LOCK_TTL_SECONDS", "120"))
SEND_LOCK_WAIT_TIMEOUT_SECONDS = float(os.getenv("SEND_LOCK_WAIT_TIMEOUT_SECONDS", "45"))
SEND_LOCK_RETRY_INTERVAL_SECONDS = float(os.getenv("SEND_LOCK_RETRY_INTERVAL_SECONDS", "0.25"))


class SendLockNotAcquiredError(RuntimeError):
    pass


def _token_hash(token: str | None) -> str:
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


@lru_cache(maxsize=1)
def _runtime_commit() -> str:
    for env_name in (
        "WORKER_COMMIT",
        "GIT_COMMIT",
        "RENDER_GIT_COMMIT",
        "RAILWAY_GIT_COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA",
        "HEROKU_SLUG_COMMIT",
        "SOURCE_VERSION",
        "COMMIT_SHA",
    ):
        commit = str(os.getenv(env_name) or "").strip()
        if commit:
            return commit

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"

    return completed.stdout.strip() or "unknown"


def _record_outbound_message(*, db, tenant_id: uuid.UUID, phone: str, text: str, message_id: str, flow_id: Any = None, flow_version_id: Any = None, flow_session_id: Any = None, node_id: Any = None) -> None:
    if not register_processed_message(db=db, tenant_id=tenant_id, message_id=message_id):
        logger.info("[OUTBOUND MESSAGE RECORD SKIPPED_DUPLICATE] tenant_id=%s conversation_id=%s flow_id=%s node_id=%s", tenant_id, "n/a", flow_id, node_id)
        return

    conversation = (
        db.execute(
            select(Conversation)
            .where(Conversation.tenant_id == tenant_id, Conversation.phone_number == phone)
            .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )
    if not conversation:
        return

    outbound = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        text=text,
        from_me=True,
    )
    conversation.updated_at = outbound.created_at
    db.add(outbound)
    db.commit()
    logger.info(
        "[OUTBOUND MESSAGE RECORDED] tenant_id=%s conversation_id=%s flow_id=%s node_id=%s status=sent direction=outbound flow_version_id=%s flow_session_id=%s",
        tenant_id,
        conversation.id,
        flow_id,
        node_id,
        flow_version_id,
        flow_session_id,
    )


def _remaining_lock_ttl(redis_client: Any, lock_key: str) -> int | None:
    try:
        return int(redis_client.ttl(lock_key))
    except Exception:
        logger.warning("[LOCK TTL] lock_key=%s ttl_error=true", lock_key, exc_info=True)
        return None


def _lock_log_context(
    *,
    lock_key: str,
    tenant_id: str,
    phone: str,
    conversation_id: str | None,
    job_id: str,
    flow_id: Any,
    flow_version_id: Any,
    session_id: Any,
    node_id: Any,
    sequence_number: Any,
    ttl: int | None,
) -> tuple[Any, ...]:
    return (
        lock_key,
        tenant_id or "n/a",
        phone or "n/a",
        conversation_id or "n/a",
        ttl if ttl is not None else "n/a",
        job_id or "n/a",
        flow_id or "n/a",
        flow_version_id or "n/a",
        session_id or "n/a",
        node_id or "n/a",
        sequence_number if sequence_number is not None else "n/a",
    )


def _log_lock_ttl(
    redis_client: Any,
    *,
    lock_key: str,
    tenant_id: str,
    phone: str,
    conversation_id: str | None,
    job_id: str,
    flow_id: Any,
    flow_version_id: Any,
    session_id: Any,
    node_id: Any,
    sequence_number: Any,
) -> int | None:
    ttl = _remaining_lock_ttl(redis_client, lock_key)
    logger.info(
        "[LOCK TTL] lock_key=%s tenant_id=%s phone=%s conversation_id=%s ttl_remaining=%s job_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s",
        *_lock_log_context(
            lock_key=lock_key,
            tenant_id=tenant_id,
            phone=phone,
            conversation_id=conversation_id,
            job_id=job_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            session_id=session_id,
            node_id=node_id,
            sequence_number=sequence_number,
            ttl=ttl,
        ),
    )
    return ttl


def _send_lock_value(
    *,
    lock_token: str,
    job_id: str,
    tenant_id: str,
    phone: str,
    conversation_id: str | None,
    flow_id: Any,
    flow_version_id: Any,
    session_id: Any,
    node_id: Any,
    sequence_number: Any,
) -> str:
    return json.dumps(
        {
            "token": lock_token,
            "job_id": job_id,
            "tenant_id": tenant_id,
            "phone": phone,
            "conversation_id": conversation_id,
            "flow_id": str(flow_id) if flow_id else None,
            "flow_version_id": str(flow_version_id) if flow_version_id else None,
            "session_id": str(session_id) if session_id else None,
            "node_id": str(node_id) if node_id else None,
            "sequence_number": str(sequence_number) if sequence_number is not None else None,
            "created_at": time.time(),
        },
        sort_keys=True,
    )


def _lock_value_matches_token(current_value: Any, lock_token: str) -> bool:
    if current_value == lock_token:
        return True
    try:
        decoded = json.loads(str(current_value or ""))
    except (TypeError, ValueError):
        return False
    return decoded.get("token") == lock_token


def _acquire_send_lock(
    redis_client: Any,
    *,
    lock_key: str,
    lock_token: str,
    tenant_id: str,
    phone: str,
    conversation_id: str | None,
    job_id: str,
    flow_id: Any,
    flow_version_id: Any,
    session_id: Any,
    node_id: Any,
    sequence_number: Any,
    wait_timeout_seconds: float = SEND_LOCK_WAIT_TIMEOUT_SECONDS,
    retry_interval_seconds: float = SEND_LOCK_RETRY_INTERVAL_SECONDS,
    lock_ttl_seconds: int = SEND_LOCK_TTL_SECONDS,
) -> bool:
    lock_value = _send_lock_value(
        lock_token=lock_token,
        job_id=job_id,
        tenant_id=tenant_id,
        phone=phone,
        conversation_id=conversation_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        session_id=session_id,
        node_id=node_id,
        sequence_number=sequence_number,
    )
    deadline = time.monotonic() + max(0.0, wait_timeout_seconds)
    attempt = 0

    while True:
        attempt += 1
        ttl_before = _remaining_lock_ttl(redis_client, lock_key)
        logger.info(
            "[LOCK ACQUIRE ATTEMPT] lock_key=%s tenant_id=%s phone=%s conversation_id=%s ttl_remaining=%s job_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s attempt=%s",
            *_lock_log_context(
                lock_key=lock_key,
                tenant_id=tenant_id,
                phone=phone,
                conversation_id=conversation_id,
                job_id=job_id,
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                session_id=session_id,
                node_id=node_id,
                sequence_number=sequence_number,
                ttl=ttl_before,
            ),
            attempt,
        )
        if redis_client.set(lock_key, lock_value, ex=lock_ttl_seconds, nx=True):
            ttl_after = _log_lock_ttl(
                redis_client,
                lock_key=lock_key,
                tenant_id=tenant_id,
                phone=phone,
                conversation_id=conversation_id,
                job_id=job_id,
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                session_id=session_id,
                node_id=node_id,
                sequence_number=sequence_number,
            )
            logger.info(
                "[LOCK ACQUIRE SUCCESS] lock_key=%s tenant_id=%s phone=%s conversation_id=%s ttl_remaining=%s job_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s attempt=%s",
                *_lock_log_context(
                    lock_key=lock_key,
                    tenant_id=tenant_id,
                    phone=phone,
                    conversation_id=conversation_id,
                    job_id=job_id,
                    flow_id=flow_id,
                    flow_version_id=flow_version_id,
                    session_id=session_id,
                    node_id=node_id,
                    sequence_number=sequence_number,
                    ttl=ttl_after,
                ),
                attempt,
            )
            return True

        ttl_after = _log_lock_ttl(
            redis_client,
            lock_key=lock_key,
            tenant_id=tenant_id,
            phone=phone,
            conversation_id=conversation_id,
            job_id=job_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            session_id=session_id,
            node_id=node_id,
            sequence_number=sequence_number,
        )
        holder = redis_client.get(lock_key)
        if time.monotonic() >= deadline:
            logger.warning(
                "[LOCK ACQUIRE FAILURE] lock_key=%s tenant_id=%s phone=%s conversation_id=%s ttl_remaining=%s job_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s attempt=%s holder=%s",
                *_lock_log_context(
                    lock_key=lock_key,
                    tenant_id=tenant_id,
                    phone=phone,
                    conversation_id=conversation_id,
                    job_id=job_id,
                    flow_id=flow_id,
                    flow_version_id=flow_version_id,
                    session_id=session_id,
                    node_id=node_id,
                    sequence_number=sequence_number,
                    ttl=ttl_after,
                ),
                attempt,
                holder,
            )
            return False

        logger.info(
            "[LOCK ACQUIRE FAILURE] lock_key=%s tenant_id=%s phone=%s conversation_id=%s ttl_remaining=%s job_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s attempt=%s waiting=true holder=%s",
            *_lock_log_context(
                lock_key=lock_key,
                tenant_id=tenant_id,
                phone=phone,
                conversation_id=conversation_id,
                job_id=job_id,
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                session_id=session_id,
                node_id=node_id,
                sequence_number=sequence_number,
                ttl=ttl_after,
            ),
            attempt,
            holder,
        )
        time.sleep(max(0.05, retry_interval_seconds))


def _release_send_lock(
    redis_client: Any,
    lock_key: str,
    lock_token: str,
    *,
    tenant_id: str = "n/a",
    phone: str = "n/a",
    conversation_id: str | None = None,
    job_id: str = "n/a",
    flow_id: Any = None,
    flow_version_id: Any = None,
    session_id: Any = None,
    node_id: Any = None,
    sequence_number: Any = None,
) -> None:
    try:
        ttl_before = _remaining_lock_ttl(redis_client, lock_key)
        current = redis_client.get(lock_key)
        released = False
        if _lock_value_matches_token(current, lock_token):
            redis_client.delete(lock_key)
            released = True
        ttl_after = _remaining_lock_ttl(redis_client, lock_key)
        logger.info(
            "[LOCK RELEASE] lock_key=%s tenant_id=%s phone=%s conversation_id=%s ttl_remaining=%s job_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s released=%s ttl_before=%s current_value=%s",
            *_lock_log_context(
                lock_key=lock_key,
                tenant_id=tenant_id,
                phone=phone,
                conversation_id=conversation_id,
                job_id=job_id,
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                session_id=session_id,
                node_id=node_id,
                sequence_number=sequence_number,
                ttl=ttl_after,
            ),
            released,
            ttl_before if ttl_before is not None else "n/a",
            current,
        )
    except Exception:
        logger.warning("[LOCK RELEASE] lock_key=%s tenant_id=%s phone=%s conversation_id=%s job_id=%s release_error=true", lock_key, tenant_id, phone, conversation_id or "n/a", job_id, exc_info=True)


def send_whatsapp_message(*, message_data: dict[str, Any]) -> None:
    commit = _runtime_commit()
    print("[SEND_WORKER FILE]", __file__)
    print("[SEND_WORKER COMMIT]", commit)
    print("[SEND_WORKER FUNCTION EXECUTED]")
    tenant_id = str(message_data.get("tenant_id") or "")
    phone = str(message_data.get("phone") or "")
    text = str(message_data.get("text") or "").strip()
    buttons = message_data.get("buttons")
    interactive_type = str(message_data.get("interactive_type") or ("button" if isinstance(buttons, list) and buttons else "")).strip().lower()
    sections = message_data.get("sections") if isinstance(message_data.get("sections"), list) else []
    options = message_data.get("options") if isinstance(message_data.get("options"), list) else []
    correlation_id = str(message_data.get("correlation_id") or message_data.get("message_id") or "n/a")
    current_job = get_current_job()
    job_id = str(message_data.get("job_id") or getattr(current_job, "id", None) or "n/a")
    sequence_number_raw = message_data.get("sequence_number")
    flow_id = message_data.get("flow_id")
    flow_version_id = message_data.get("flow_version_id")
    session_id = message_data.get("session_id")
    node_id = message_data.get("node_id")
    node_type = message_data.get("node_type")
    flow_engine = message_data.get("flow_engine")
    flow_executor = message_data.get("flow_executor")
    flow_send_source = message_data.get("flow_send_source")
    flow_session_id = message_data.get("session_id")
    conversation_id = str(message_data.get("conversation_id") or "") or None
    is_flow_message = bool(flow_id or flow_version_id or session_id or node_id or sequence_number_raw is not None)
    payload_provider_id = str(message_data.get("provider_id") or "unresolved")
    message_type = "interactive" if interactive_type or (isinstance(buttons, list) and buttons) else "text"
    log_message_origin_trace(
        executor=flow_executor or flow_send_source or "send_worker.send_whatsapp_message",
        flow_id=flow_id,
        node_id=node_id,
        node_type=node_type,
        message=text,
        context=message_data,
    )
    logger.info(
        "[SEND WORKER MESSAGE TYPE] flow_id=%s session_id=%s node_id=%s node_type=%s engine=%s executor=%s source=%s message_type=%s options_count=%s payload_json=%s",
        flow_id,
        session_id,
        node_id,
        node_type,
        flow_engine,
        flow_executor,
        flow_send_source,
        message_type,
        len(options or buttons or []) if isinstance(options or buttons, list) else 0,
        json.dumps(message_data, default=str, ensure_ascii=False, sort_keys=True),
    )
    if interactive_type == "list":
        logger.info(
            "[CHOICE LIST RECEIVED BY WORKER] session_id=%s node_id=%s flow_id=%s interactive_type=%s job_id=%s options_count=%s payload_summary=%s",
            session_id,
            node_id,
            flow_id,
            interactive_type,
            job_id,
            len(options or []),
            _payload_summary({"text": text, "sections": sections, "options": options}),
        )

    logger.info(
        "[WORKER ENTRY] job_id=%s message=%s flow_id=%s sequence_number=%s",
        job_id,
        text,
        flow_id,
        sequence_number_raw,
    )
    logger.info(
        "[WORKER VERSION CHECK] commit=%s provider_id=%s message_text=%s",
        commit,
        payload_provider_id,
        text,
    )
    logger.info(
        "[FLOW QUEUE DEQUEUE] job_id=%s flow_id=%s session_id=%s node_id=%s engine=%s executor=%s source=%s sequence_number=%s message_text=%s worker_commit=%s worker_file=%s queue_name=%s",
        job_id,
        flow_id,
        session_id,
        node_id,
        flow_engine or "unknown",
        flow_executor or "unknown",
        flow_send_source or "unknown",
        sequence_number_raw,
        text,
        commit,
        __file__,
        getattr(current_job, "origin", None),
    )
    logger.info("event=send_worker_start correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_start", correlation_id, tenant_id or "n/a", phone or "n/a", job_id)

    lock_key = f"wa:send-lock:{tenant_id}:{phone}"
    last_sent_key = f"wa:last-sent-seq:{tenant_id}:{phone}"
    lock_token = str(uuid.uuid4())
    redis_client = get_redis_client()
    lock_acquired = _acquire_send_lock(
        redis_client,
        lock_key=lock_key,
        lock_token=lock_token,
        tenant_id=tenant_id,
        phone=phone,
        conversation_id=conversation_id,
        job_id=job_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        session_id=session_id,
        node_id=node_id,
        sequence_number=sequence_number_raw,
    )
    if not lock_acquired:
        logger.warning("[WORKER EXIT FAILURE] job_id=%s reason=send_lock_not_acquired", job_id)
        raise SendLockNotAcquiredError(f"send lock not acquired for job_id={job_id} lock_key={lock_key}")
    logger.info("[OUTBOUND SEND LOCK ACQUIRED] tenant_id=%s phone=%s acquired=true", tenant_id, phone)

    try:
        sequence_number: int | None = None
        if sequence_number_raw is not None:
            try:
                sequence_number = int(sequence_number_raw)
            except (TypeError, ValueError):
                sequence_number = None
        last_sent_raw = redis_client.get(last_sent_key)
        last_sent_seq = int(last_sent_raw) if str(last_sent_raw or "").isdigit() else None
        logger.info("[OUTBOUND SEND SEQUENCE] tenant_id=%s phone=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s current_sequence=%s last_sent_sequence=%s", tenant_id, phone, flow_id, flow_version_id, session_id, node_id, sequence_number, last_sent_seq)
        if sequence_number is not None and last_sent_seq is not None and sequence_number < last_sent_seq:
            logger.warning("[OUTBOUND STALE MESSAGE DROPPED] tenant_id=%s phone=%s flow_id=%s session_id=%s node_id=%s sequence_number=%s last_sent_sequence=%s", tenant_id, phone, flow_id, session_id, node_id, sequence_number, last_sent_seq)
            logger.warning("[WORKER EXIT FAILURE] job_id=%s reason=stale_sequence sequence_number=%s last_sent_sequence=%s", job_id, sequence_number, last_sent_seq)
            return

        try:
            tenant_uuid = uuid.UUID(tenant_id)
        except (ValueError, TypeError):
            logger.error(
                "event=queue_send_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=invalid_tenant_id",
                correlation_id,
                tenant_id or "n/a",
                phone or "n/a",
                job_id,
            )
            logger.error("[WORKER EXIT FAILURE] job_id=%s reason=invalid_tenant_id", job_id)
            return

        with SessionLocal() as db:
            tenant = db.execute(select(Tenant).where(Tenant.id == tenant_uuid)).scalars().first()
            if not tenant:
                logger.warning(
                    "event=queue_send_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=tenant_not_found",
                    correlation_id,
                    tenant_id,
                    phone,
                    job_id,
                )
                logger.warning("[WORKER EXIT FAILURE] job_id=%s reason=tenant_not_found", job_id)
                return
            if not conversation_id:
                conversation = (
                    db.execute(
                        select(Conversation.id)
                        .where(Conversation.tenant_id == tenant_uuid, Conversation.phone_number == phone)
                        .order_by(Conversation.updated_at.desc(), Conversation.created_at.desc())
                        .limit(1)
                    )
                    .scalars()
                    .first()
                )
                conversation_id = str(conversation) if conversation else None

        provider_id: str | None = None
        with SessionLocal() as db:
            active_provider = resolve_active_meta_provider_credentials(db, tenant_id=tenant_id, conversation_id=conversation_id)

        if active_provider:
            resolved_phone_number_id = active_provider["phone_number_id"]
            resolved_token = active_provider["token"]
            provider_id = active_provider["provider_id"]
            logger.info(
                "[SEND WORKER PROVIDER] provider_id=%s tenant_id=%s provider_name=%s phone_number_id=%s waba_id=%s business_id=%s status=%s is_active=%s token_exists=%s token_length=%s updated_at=%s send_endpoint=/%s/messages",
                provider_id,
                tenant_id,
                active_provider.get("provider_name"),
                resolved_phone_number_id,
                active_provider.get("waba_id"),
                active_provider.get("business_id"),
                active_provider.get("status"),
                active_provider.get("is_active"),
                bool(resolved_token),
                len(resolved_token or ""),
                active_provider.get("updated_at"),
                resolved_phone_number_id,
            )
        else:
            try:
                credentials = get_tenant_whatsapp_credentials(tenant_id)
                resolved_phone_number_id = credentials["phone_number_id"]
                resolved_token = credentials["token"]
                logger.warning(
                    "[SEND WORKER PROVIDER] provider_id=%s tenant_id=%s provider_name=%s phone_number_id=%s waba_id=%s business_id=%s status=%s is_active=%s token_exists=%s token_length=%s source=legacy_credentials",
                    None,
                    tenant_id,
                    "legacy_credentials",
                    resolved_phone_number_id,
                    None,
                    None,
                    "legacy",
                    False,
                    bool(resolved_token),
                    len(resolved_token or ""),
                )
            except WhatsAppCredentialsNotConfiguredError:
                logger.error(
                    "event=queue_send_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=missing_whatsapp_credentials error=[WHATSAPP NOT CONFIGURED] tenant_id=%s",
                    correlation_id,
                    tenant_id,
                    phone,
                    job_id,
                    tenant_id,
                )
                logger.error("[WORKER EXIT FAILURE] job_id=%s reason=missing_whatsapp_credentials", job_id)
                return

        token_hash = _token_hash(resolved_token)
        waba_id = active_provider.get("waba_id") if active_provider else None
        business_id = active_provider.get("business_id") if active_provider else None
        business_account_id = waba_id or business_id
        provider_source = "active_provider" if active_provider else "legacy_credentials"
        meta_endpoint = f"/{resolved_phone_number_id}/messages"
        context = {
            "tenant_id": tenant_id,
            "provider_id": provider_id,
            "token_length": len(resolved_token or ""),
            "token_hash": token_hash,
            "phone_number_id": resolved_phone_number_id,
            "business_account_id": business_account_id,
            "waba_id": waba_id,
            "business_id": business_id,
            "source": provider_source,
            "flow_id": flow_id,
            "flow_version_id": flow_version_id,
            "session_id": session_id,
            "node_id": node_id,
            "node_type": node_type,
            "sequence_number": sequence_number,
            "flow_executor": flow_executor,
            "flow_send_source": flow_send_source,
        }
        if is_flow_message:
            logger.info(
                "[FLOW MESSAGE PROVIDER] tenant_id=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s sequence_number=%s provider_id=%s phone_number_id=%s business_account_id=%s waba_id=%s business_id=%s token_hash=%s provider_source=%s provider_updated_at=%s message_text=%s",
                tenant_id,
                flow_id,
                flow_version_id,
                session_id,
                node_id,
                sequence_number,
                provider_id,
                resolved_phone_number_id,
                business_account_id,
                waba_id,
                business_id,
                token_hash,
                provider_source,
                active_provider.get("updated_at") if active_provider else None,
                text,
            )
            logger.info(
                "[FLOW MESSAGE META REQUEST] endpoint=%s phone_number_id=%s provider_id=%s tenant_id=%s flow_id=%s session_id=%s node_id=%s sequence_number=%s",
                meta_endpoint,
                resolved_phone_number_id,
                provider_id,
                tenant_id,
                flow_id,
                session_id,
                node_id,
                sequence_number,
            )
        logger.info(
            "[WORKER BEFORE META] provider_id=%s phone_number_id=%s message=%s",
            provider_id,
            resolved_phone_number_id,
            text,
        )
        logger.info(
            "[META PRE REQUEST] provider_id=%s phone_number_id=%s token_hash=%s token_length=%s message=%s",
            provider_id,
            resolved_phone_number_id,
            token_hash,
            len(resolved_token or ""),
            text,
        )

        log_message_origin_trace(
            executor=flow_executor or flow_send_source or "send_worker.before_meta",
            flow_id=flow_id,
            node_id=node_id,
            node_type=node_type,
            message=text,
            context=context,
        )
        meta_response: dict[str, Any] | None = None
        try:
            if interactive_type == "list":
                logger.info(
                    "[META INTERACTIVE PAYLOAD] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s interactive_type=%s options_count=%s payload_json=%s",
                    flow_id,
                    session_id,
                    node_id,
                    node_type,
                    "interactive",
                    "list",
                    len(options or []),
                    json.dumps({"body_text": text, "sections": sections, "options": options, "interactive": {"type": "list"}}, default=str, ensure_ascii=False, sort_keys=True),
                )
                meta_response = send_interactive_list_via_meta(
                    to=phone,
                    body_text=text,
                    sections=sections,
                    token=resolved_token,
                    phone_number_id=resolved_phone_number_id,
                    context=context,
                )
                logger.info(
                    "[CHOICE LIST SENT] session_id=%s node_id=%s flow_id=%s interactive_type=%s options_count=%s meta_response=%s payload_summary=%s",
                    session_id,
                    node_id,
                    flow_id,
                    interactive_type,
                    len(options or []),
                    _payload_summary(meta_response),
                    _payload_summary({"text": text, "sections": sections, "options": options}),
                )
            elif buttons:
                logger.info(
                    "[META INTERACTIVE PAYLOAD] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s options_count=%s payload_json=%s",
                    flow_id,
                    session_id,
                    node_id,
                    node_type,
                    "interactive",
                    len(buttons or []) if isinstance(buttons, list) else 0,
                    json.dumps({"body_text": text, "buttons": buttons, "interactive": {"type": "button"}}, default=str, ensure_ascii=False, sort_keys=True),
                )
                meta_response = send_buttons_message_via_meta(
                    to=phone,
                    body_text=text,
                    buttons=buttons,
                    token=resolved_token,
                    phone_number_id=resolved_phone_number_id,
                    context=context,
                )
            else:
                meta_response = send_text_message_via_meta(
                    to=phone,
                    text=text,
                    token=resolved_token,
                    phone_number_id=resolved_phone_number_id,
                    context=context,
                )
            logger.info(
                "[WORKER AFTER META] provider_id=%s phone_number_id=%s meta_response=%s",
                provider_id,
                resolved_phone_number_id,
                meta_response,
            )
        except MetaApiError as exc:
            if interactive_type == "list":
                logger.error(
                    "[CHOICE LIST SEND ERROR] session_id=%s node_id=%s flow_id=%s interactive_type=%s status_code=%s error=%s payload_summary=%s",
                    session_id,
                    node_id,
                    flow_id,
                    interactive_type,
                    exc.status_code,
                    exc,
                    _payload_summary({"text": text, "sections": sections, "options": options}),
                )
            if exc.status_code == 401 and provider_id:
                logger.error("[WHATSAPP SEND AUTH ERROR] tenant_id=%s provider_id=%s phone=%s", tenant_id, provider_id, phone)
                with SessionLocal() as db:
                    mark_provider_auth_error(db, provider_id=provider_id, error_message=str(exc))
            logger.error("[WORKER EXIT FAILURE] job_id=%s reason=meta_api_error status_code=%s error=%s", job_id, exc.status_code, exc)
            raise

        logger.info(
            "event=queue_send_success correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_final text_len=%s has_buttons=%s",
            correlation_id,
            tenant_id,
            phone,
            job_id,
            len(text),
            bool(buttons),
        )
        if sequence_number is not None:
            redis_client.set(last_sent_key, sequence_number)

        dedupe_message_id = str(message_data.get("message_id") or message_data.get("job_id") or getattr(current_job, "id", None) or correlation_id)
        with SessionLocal() as db:
            _record_outbound_message(
                db=db,
                tenant_id=tenant_uuid,
                phone=phone,
                text=text,
                message_id=f"outbound:{dedupe_message_id}",
                flow_id=flow_id,
                flow_version_id=flow_version_id,
                flow_session_id=flow_session_id,
                node_id=node_id,
            )
        logger.info("[WORKER EXIT SUCCESS] job_id=%s", job_id)
    except Exception:
        logger.exception("[WORKER EXIT FAILURE] job_id=%s reason=unhandled_exception", job_id)
        raise
    finally:
        _release_send_lock(
            redis_client,
            lock_key,
            lock_token,
            tenant_id=tenant_id,
            phone=phone,
            conversation_id=conversation_id,
            job_id=job_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            session_id=session_id,
            node_id=node_id,
            sequence_number=sequence_number_raw,
        )
        logger.info("[OUTBOUND SEND LOCK RELEASED] tenant_id=%s phone=%s", tenant_id, phone)
