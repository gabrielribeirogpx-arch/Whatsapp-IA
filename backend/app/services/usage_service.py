from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing.usage_metrics import STOCK_METRICS, UsageMetric
from app.models import (Flow, IntegrationConnection, KnowledgeSource, TenantUser,
                        TenantWhatsAppProvider, UsageCounter, UsageEvent)

logger = logging.getLogger(__name__)


def utc_month(now: datetime | None = None) -> tuple[datetime, datetime]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    end = datetime(now.year + (now.month == 12), 1 if now.month == 12 else now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


class UsageService:
    """Best-effort observational accounting; this service never authorizes work."""
    def __init__(self, db: Session): self.db = db

    def increment(self, tenant_id: UUID, metric: UsageMetric, amount: float = 1, *, source_type: str | None = None, source_id: str | None = None, now: datetime | None = None) -> bool:
        start, end = utc_month(now)
        try:
            if source_type and source_id:
                event = UsageEvent(tenant_id=tenant_id, metric_key=metric.value, source_type=source_type, source_id=str(source_id), amount=amount, period_start=start)
                try:
                    # A savepoint prevents an idempotent duplicate from rolling
                    # back the caller's operational transaction.
                    with self.db.begin_nested():
                        self.db.add(event)
                        self.db.flush()
                except IntegrityError:
                    return False
            result = self.db.execute(update(UsageCounter).where(UsageCounter.tenant_id == tenant_id, UsageCounter.metric_key == metric.value, UsageCounter.period_start == start, UsageCounter.period_end == end).values(used_value=UsageCounter.used_value + amount, updated_at=datetime.now(timezone.utc)))
            if not result.rowcount:
                try:
                    with self.db.begin_nested():
                        self.db.add(UsageCounter(tenant_id=tenant_id, metric_key=metric.value, period_type="monthly", period_start=start, period_end=end, used_value=amount))
                        self.db.flush()
                except IntegrityError:
                    self.db.execute(update(UsageCounter).where(UsageCounter.tenant_id == tenant_id, UsageCounter.metric_key == metric.value, UsageCounter.period_start == start, UsageCounter.period_end == end).values(used_value=UsageCounter.used_value + amount))
            logger.info("usage_increment_success tenant_id=%s metric_key=%s amount=%s", tenant_id, metric.value, amount)
            return True
        except Exception:
            logger.exception("USAGE_RECORDING_FAILED tenant_id=%s metric_key=%s", tenant_id, metric.value)
            return False

    def decrement(self, tenant_id: UUID, metric: UsageMetric, amount: float = 1) -> bool:
        return self.increment(tenant_id, metric, -amount)

    def set_current(self, tenant_id: UUID, metric: UsageMetric, value: float) -> bool:
        """Set a reconciled rollup; stock metrics remain query-derived."""
        start, end = utc_month()
        try:
            row = self.db.scalar(select(UsageCounter).where(UsageCounter.tenant_id == tenant_id, UsageCounter.metric_key == metric.value, UsageCounter.period_start == start, UsageCounter.period_end == end))
            if row is None:
                self.db.add(UsageCounter(tenant_id=tenant_id, metric_key=metric.value, period_type="monthly", period_start=start, period_end=end, used_value=value))
            else:
                row.used_value = value
            return True
        except Exception:
            logger.exception("USAGE_RECORDING_FAILED tenant_id=%s metric_key=%s", tenant_id, metric.value)
            return False

    def reserve(self, tenant_id: UUID, metric: UsageMetric, amount: float = 1) -> bool:
        # Preparation for future enforcement only: reservations always succeed.
        return self.increment(tenant_id, metric, 0)

    def commit(self, tenant_id: UUID, metric: UsageMetric, amount: float = 1, **kwargs) -> bool:
        return self.increment(tenant_id, metric, amount, **kwargs)

    def release(self, tenant_id: UUID, metric: UsageMetric, amount: float = 1) -> bool:
        return True

    def rebuild(self, tenant_id: UUID) -> dict[str, float]:
        return self.current_snapshot(tenant_id)

    def reconcile(self, tenant_id: UUID) -> dict[str, float]:
        logger.info("usage_reconciliation_started tenant_id=%s", tenant_id)
        snapshot = self.rebuild(tenant_id)
        logger.info("usage_reconciliation_completed tenant_id=%s", tenant_id)
        return snapshot

    def get_period_usage(self, tenant_id: UUID, metric: UsageMetric, now: datetime | None = None) -> float:
        start, end = utc_month(now)
        return float(self.db.scalar(select(UsageCounter.used_value).where(UsageCounter.tenant_id == tenant_id, UsageCounter.metric_key == metric.value, UsageCounter.period_start == start, UsageCounter.period_end == end)) or 0)

    def current_snapshot(self, tenant_id: UUID) -> dict[str, float]:
        # Stock values are derived, avoiding duplicated operational state.
        return {
            UsageMetric.ACTIVE_USERS.value: float(self.db.scalar(select(func.count()).select_from(TenantUser).where(TenantUser.tenant_id == tenant_id, TenantUser.status == "active")) or 0),
            UsageMetric.WHATSAPP_NUMBERS.value: float(self.db.scalar(select(func.count()).select_from(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id, TenantWhatsAppProvider.is_active.is_(True))) or 0),
            UsageMetric.PUBLISHED_FLOWS.value: float(self.db.scalar(select(func.count()).select_from(Flow).where(Flow.tenant_id == tenant_id, Flow.status == "published", Flow.is_deleted.is_(False))) or 0),
            UsageMetric.ACTIVE_INTEGRATIONS.value: float(self.db.scalar(select(func.count()).select_from(IntegrationConnection).where(IntegrationConnection.tenant_id == tenant_id, IntegrationConnection.status == "active")) or 0),
            UsageMetric.KNOWLEDGE_DOCUMENTS.value: float(self.db.scalar(select(func.count()).select_from(KnowledgeSource).where(KnowledgeSource.tenant_id == tenant_id)) or 0),
        }

    def usage_view(self, tenant_id: UUID, limits: dict[str, dict]) -> dict:
        start, end = utc_month()
        values = self.current_snapshot(tenant_id)
        for metric in UsageMetric:
            if metric not in STOCK_METRICS: values[metric.value] = self.get_period_usage(tenant_id, metric)
        metrics = []
        for key, used in values.items():
            limit = limits.get(key, {}).get("limit_value")
            unlimited = limit is None
            percentage = None if unlimited else round(used / limit * 100, 2) if limit else 100
            status = "unlimited" if unlimited else ("exceeded_observationally" if used > limit else "approaching" if percentage >= 80 else "normal")
            metrics.append({"metric_key": key, "used_value": used, "limit": limit, "unlimited": unlimited, "percentage": percentage, "status": status})
        return {"current_period": {"type": "monthly", "start": start, "end": end}, "metrics": metrics, "last_updated_at": datetime.now(timezone.utc)}
