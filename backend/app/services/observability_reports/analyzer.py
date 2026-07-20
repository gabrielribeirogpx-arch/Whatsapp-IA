"""Pure deterministic analysis rules. No external AI or availability inference."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

THRESHOLDS = {"minimum_executions": 2, "error_rate_warning": 5, "error_rate_critical": 15, "p95_warning_ms": 2000, "p95_critical_ms": 5000, "retries_warning": 1, "lock_contention_warning": 1}


@dataclass(frozen=True)
class Health:
    label: str
    tone: str
    explanation: str
    criteria: list[str]


def analyse(summary: dict[str, Any]) -> Health:
    executions = int(summary.get("executions") or 0)
    if executions < THRESHOLDS["minimum_executions"]:
        return Health("Dados insuficientes", "muted", "O volume observado não é suficiente para uma avaliação confiável.", [f"Menos de {THRESHOLDS['minimum_executions']} execuções no período"])
    errors, p95 = float(summary.get("error_rate") or 0), summary.get("p95")
    if errors >= THRESHOLDS["error_rate_critical"] or (p95 is not None and p95 >= THRESHOLDS["p95_critical_ms"]):
        return Health("Crítico", "critical", "Há métricas que exigem atenção imediata.", ["Taxa de erro ou latência p95 acima do limite crítico"])
    criteria: list[str] = []
    if errors >= THRESHOLDS["error_rate_warning"]: criteria.append("Taxa de erro acima do limite de atenção")
    if p95 is not None and p95 >= THRESHOLDS["p95_warning_ms"]: criteria.append("Latência p95 acima do limite de atenção")
    if int(summary.get("retries") or 0) >= THRESHOLDS["retries_warning"]: criteria.append("Retries registrados no período")
    if int(summary.get("lock_contention") or 0) >= THRESHOLDS["lock_contention_warning"]: criteria.append("Contenção de lock registrada")
    if criteria: return Health("Atenção", "warning", "Uma ou mais métricas estão degradadas.", criteria)
    return Health("Saudável", "success", "As métricas disponíveis estão dentro dos limites configurados.", ["Taxa de erro, p95, retries e locks avaliados"])


def executive_summary(summary: dict[str, Any]) -> str:
    executions = int(summary.get("executions") or 0)
    if not executions: return "Nenhuma execução foi encontrada no período selecionado. Não há dados suficientes para conclusões operacionais."
    text = f"Durante o período analisado, o Wazza processou {executions} execução(ões), com taxa de sucesso de {summary.get('success_rate', 0)}%."
    text += " Não foram registrados erros." if not summary.get("errors") else f" Foram registrados {summary['errors']} evento(s) de erro."
    if summary.get("p95") is not None: text += f" A latência p95 foi de {summary['p95']} ms."
    text += " Não foram registrados retries." if not summary.get("retries") else f" Foram registrados {summary['retries']} retries."
    if summary.get("lock_contention"): text += f" Foram registradas {summary['lock_contention']} contenções de lock."
    if executions < THRESHOLDS["minimum_executions"]: text += " O volume observado é insuficiente para avaliar tendências."
    return text


def conclusions(summary: dict[str, Any], health: Health) -> tuple[list[str], list[str]]:
    findings = [health.explanation]
    if not summary.get("errors"): findings.append("Nenhum erro foi registrado no período.")
    if summary.get("p95") is not None and summary["p95"] >= THRESHOLDS["p95_warning_ms"]: findings.append("A latência p95 ficou acima do limite configurado.")
    recommendations = []
    if int(summary.get("executions") or 0) < THRESHOLDS["minimum_executions"]: recommendations.append("Colete mais dados antes de avaliar tendências.")
    if summary.get("p95") and summary["p95"] >= THRESHOLDS["p95_warning_ms"]: recommendations.append("Investigue os traces mais lentos.")
    if summary.get("lock_contention"): recommendations.append("Revise locks quando a contenção ultrapassar o limite configurado.")
    if summary.get("retries"): recommendations.append("Revise os traces com retries registrados.")
    return findings, recommendations or ["Continue acompanhando as métricas do período."]
