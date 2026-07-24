"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, CheckCircle2, ChevronDown, CreditCard, Loader2, RefreshCw } from "lucide-react";
import { createBillingCheckout, getCurrentBilling, listBillingPlans, openBillingPortal } from "@/lib/api";
import type { BillingPlan, CurrentBillingState, EffectiveEntitlement, PlanFeature } from "@/lib/types";

const COMPARISON_ROWS = [
  ["users", "Usuários"], ["whatsapp_numbers", "WhatsApp"], ["published_flows", "Fluxos"], ["messages", "Mensagens"],
  ["crm", "CRM"], ["inbox", "Inbox"], ["ai", "IA"], ["mcp", "MCP"], ["academy", "Academy"], ["api", "API"],
] as const;

const RESOURCE_LABELS: Record<string, string> = {
  inbox: "Inbox", crm: "CRM", ai: "IA", mcp: "MCP", academy: "Academy", observability: "Observabilidade", api: "API", knowledge_base: "Base de conhecimento",
};

const USAGE_METRICS = [
  ["messages", "Conversas", "Ilimitado"], ["users", "Usuários", "—"], ["published_flows", "Fluxos", "—"],
  ["whatsapp_numbers", "WhatsApp", "—"], ["integrations", "Integrações", "—"], ["ai", "IA", "Desativada"],
] as const;

function formatPrice(amount: number | null) {
  return amount === null ? "Sob consulta" : `R$ ${(amount / 100).toLocaleString("pt-BR", { maximumFractionDigits: 0 })}`;
}

function featureValue(feature?: PlanFeature) {
  if (!feature?.enabled) return "—";
  if (feature.limit_value === null) return "Ilimitado";
  return `${feature.limit_value}${feature.limit_unit ? ` ${feature.limit_unit}` : ""}`;
}

function getFeature(features: PlanFeature[], key: string) {
  const aliases: Record<string, string[]> = { messages: ["messages", "monthly_messages", "conversations"], integrations: ["integrations", "integration_connections"] };
  return features.find((feature) => (aliases[key] || [key]).includes(feature.feature_key));
}

function dateLabel(value?: string | null) {
  return value ? new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(value)) : "—";
}

export function PlanBadge({ status }: { status?: string | null }) {
  const trial = status === "trialing";
  return <span className="billing-status">{trial ? "Trial" : status === "legacy" ? "Acesso legado" : status || "Sem assinatura"}</span>;
}

export function SubscriptionStatusBadge({ status }: { status?: string | null }) { return <PlanBadge status={status} />; }
export function LimitDisplay({ entitlement }: { entitlement: EffectiveEntitlement }) { return <li><span>{RESOURCE_LABELS[entitlement.feature_key] || entitlement.feature_key.replaceAll("_", " ")}</span><strong>{featureValue(entitlement)}</strong></li>; }
export function EntitlementList({ entitlements }: { entitlements: EffectiveEntitlement[] }) {
  const features = entitlements.filter((item) => item.enabled).slice(0, 8);
  return <ul className="billing-features">{features.map((item) => <li key={item.feature_key}><Check size={16} />{RESOURCE_LABELS[item.feature_key] || item.feature_key.replaceAll("_", " ")}</li>)}</ul>;
}

export function CurrentPlanCard({ state, portal, changePlan }: { state: CurrentBillingState; portal: () => void; changePlan: () => void }) {
  const trial = state.trial;
  const expiresAt = state.subscription?.trial_ends_at || state.subscription?.current_period_end;
  const progress = trial ? Math.max(4, Math.min(100, ((14 - state.days_remaining) / 14) * 100)) : 100;
  return <section className="billing-card billing-current-card" aria-labelledby="current-plan-title">
    <div className="billing-current-card__top"><div><p className="billing-eyebrow">Plano atual</p><div className="billing-plan-name"><h2 id="current-plan-title">{trial ? "Growth Trial" : state.plan?.name || "Sem assinatura"}</h2>{trial && <PlanBadge status="trialing" />}</div></div><span className="billing-active-status"><i />Ativo</span></div>
    <div className="billing-plan-details"><div><span>{trial ? "Período de avaliação" : "Ciclo de cobrança"}</span><strong>{trial ? `${state.days_remaining} dias restantes` : state.subscription?.billing_interval === "annual" ? "Anual" : "Mensal"}</strong></div><div><span>{trial ? "Expira em" : "Próxima renovação"}</span><strong>{dateLabel(expiresAt)}</strong></div><div><span>Workspace</span><strong>Workspace atual</strong></div></div>
    <div className="billing-progress" aria-label={trial ? `${state.days_remaining} dias restantes no trial` : "Assinatura ativa"}><span style={{ width: `${progress}%` }} /></div>
    <div className="billing-card-actions"><button type="button" className="billing-button billing-button--primary" onClick={changePlan}>Alterar plano</button>{state.subscription?.provider === "stripe" && <button type="button" className="billing-button" onClick={portal}>Ver detalhes</button>}</div>
  </section>;
}

function UsageGrid({ state }: { state: CurrentBillingState }) {
  return <section aria-labelledby="usage-title"><div className="billing-section-heading"><div><h2 id="usage-title">Uso atual</h2><p>Limites e recursos disponíveis neste workspace.</p></div></div><div className="billing-usage-grid">{USAGE_METRICS.map(([key, label, fallback]) => {
    const feature = getFeature(state.effective_entitlements, key);
    const value = key === "ai" ? (feature?.enabled ? "Ativada" : fallback) : featureValue(feature);
    return <article className="billing-card billing-metric" key={key}><span>{label}</span><strong>{value === "—" ? fallback : value}</strong>{key === "users" || key === "published_flows" ? <small>do limite do plano</small> : null}</article>;
  })}</div></section>;
}

export function PlanComparison({ plans, enabled, currentPlanCode, isTrial, checkout }: { plans: BillingPlan[]; enabled: boolean; currentPlanCode?: string; isTrial: boolean; checkout: (code: string, interval: "monthly" | "annual") => void }) {
  const [open, setOpen] = useState(false);
  const [interval, setInterval] = useState<"monthly" | "annual">("monthly");
  const publicPlans = plans.filter((plan) => plan.code !== "growth_trial" && plan.code !== "legacy");
  const currentCode = isTrial ? "growth" : currentPlanCode;
  const planByCode = useMemo(() => new Map(publicPlans.map((plan) => [plan.code, plan])), [publicPlans]);
  return <section className="billing-comparison" aria-labelledby="plan-comparison-title"><button type="button" className="billing-comparison__trigger" aria-expanded={open} onClick={() => setOpen((value) => !value)}><span><strong id="plan-comparison-title">Comparar planos</strong><small>Consulte limites, recursos e preços por plano.</small></span><ChevronDown size={18} className={open ? "is-open" : ""} /></button>{open && <div className="billing-comparison__content"><div className="billing-interval" aria-label="Periodicidade"><button type="button" className={interval === "monthly" ? "is-active" : ""} onClick={() => setInterval("monthly")}>Mensal</button><button type="button" className={interval === "annual" ? "is-active" : ""} onClick={() => setInterval("annual")}>Anual</button></div><div className="billing-table-scroll"><table className="billing-table"><thead><tr><th>Recurso</th>{publicPlans.map((plan) => <th key={plan.code}>{plan.name}{plan.code === currentCode && <span>Plano atual</span>}</th>)}</tr></thead><tbody>{COMPARISON_ROWS.map(([key, label]) => <tr key={key}><th>{label}</th>{publicPlans.map((plan) => <td key={plan.code}>{featureValue(getFeature(planByCode.get(plan.code)?.features || [], key))}</td>)}</tr>)}<tr className="billing-table__price"><th>Preço</th>{publicPlans.map((plan) => <td key={plan.code}>{formatPrice(interval === "monthly" ? plan.monthly_price_cents : plan.annual_price_cents)}</td>)}</tr><tr className="billing-table__actions"><th><span className="sr-only">Ação</span></th>{publicPlans.map((plan) => { const current = plan.code === currentCode; const enterprise = plan.monthly_price_cents === null; return <td key={plan.code}><button type="button" className="billing-button" disabled={!enabled || current} onClick={() => !enterprise && checkout(plan.code, interval)}>{current ? "Plano atual" : enterprise ? "Falar com vendas" : "Selecionar plano"}</button></td>; })}</tr></tbody></table></div></div>}</section>;
}

function BillingHistory() { return <section className="billing-card billing-history"><div><h2>Histórico de cobrança</h2><p>Faturas, recibos e pagamentos aparecerão aqui quando disponíveis.</p></div><span>Em breve</span></section>; }

export default function BillingTab() {
  const [state, setState] = useState<CurrentBillingState | null>(null); const [plans, setPlans] = useState<BillingPlan[]>([]); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { setLoading(true); setError(null); try { const [current, catalog] = await Promise.all([getCurrentBilling(), listBillingPlans()]); setState(current); setPlans(catalog); } catch { setError("Não foi possível carregar as informações de plano. O restante do Wazza continua disponível."); } finally { setLoading(false); } }, []);
  useEffect(() => { void load(); }, [load]);
  if (loading) return <div className="flex min-h-48 items-center justify-center text-slate-500"><Loader2 className="mr-2 animate-spin" size={18} /> Carregando plano e cobrança…</div>;
  if (error) return <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900"><p>{error}</p><button onClick={() => void load()} className="mt-3 inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 font-semibold"><RefreshCw size={15} /> Tentar novamente</button></section>;
  if (!state?.billing_ui_enabled) return <section className="rounded-2xl border border-slate-200 bg-white p-5 text-slate-600">A visualização de plano e cobrança não está disponível neste ambiente.</section>;
  const checkout = async (code: string, interval: "monthly" | "annual") => { setBusy(true); try { const result = await createBillingCheckout(code, interval); window.location.assign(result.checkout_url); } catch { setError("Não foi possível iniciar o Checkout."); } finally { setBusy(false); } };
  const portal = async () => { setBusy(true); try { const result = await openBillingPortal(); window.location.assign(result.portal_url); } catch { setError("Não foi possível abrir o portal de cobrança."); } finally { setBusy(false); } };
  const pending = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search).get("checkout") === "success";
  return <div className="billing-page"><header className="billing-page__header"><div><h1>Plano e cobrança</h1><p>Gerencie a assinatura e os limites do seu workspace.</p></div></header>{!state.stripe_enabled && <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Os pagamentos online ainda não estão disponíveis. Você pode continuar utilizando seu período de teste normalmente.</p>}{pending && <p className="rounded-xl bg-blue-50 p-3 text-sm text-blue-900">Pagamento recebido. Estamos confirmando sua assinatura.</p>}{busy && <p className="text-sm text-slate-500">Redirecionando para a cobrança segura…</p>}<CurrentPlanCard state={state} portal={() => void portal()} changePlan={() => document.getElementById("plan-comparison-title")?.closest("section")?.scrollIntoView({ behavior: "smooth" })} /><UsageGrid state={state} /><section className="billing-card billing-resources"><div className="billing-section-heading"><div><h2>Recursos inclusos</h2><p>Recursos atualmente habilitados no seu plano.</p></div></div><EntitlementList entitlements={state.effective_entitlements} /></section><PlanComparison plans={plans} enabled={Boolean(state.stripe_enabled)} currentPlanCode={state.plan?.code} isTrial={state.trial} checkout={(code, interval) => void checkout(code, interval)} /><BillingHistory /><p className="billing-note"><CheckCircle2 size={14} /> Nenhum recurso é bloqueado nesta fase.</p></div>;
}
