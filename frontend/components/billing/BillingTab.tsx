"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowRight, Check, CheckCircle2, CreditCard, Loader2, RefreshCw, ShieldCheck, Sparkles, Users, Workflow } from "lucide-react";
import { createBillingCheckout, getCurrentBilling, listBillingPlans, openBillingPortal } from "@/lib/api";
import type { BillingPlan, CurrentBillingState, EffectiveEntitlement, PlanFeature } from "@/lib/types";

const PLAN_COPY: Record<string, { description: string; benefits: string[] }> = {
  starter: { description: "O essencial para colocar sua operação no ar.", benefits: ["Automação de atendimento", "1 número de WhatsApp", "Fluxos prontos para usar"] },
  growth: { description: "Mais escala e inteligência para equipes em crescimento.", benefits: ["IA para conversas", "20 fluxos publicados", "Métricas de operação"] },
  business: { description: "Controle avançado para uma operação de alta performance.", benefits: ["Até 3 números de WhatsApp", "Automação em escala", "Retenção ampliada de dados"] },
  enterprise: { description: "Estrutura sob medida para organizações complexas.", benefits: ["Segurança e SSO", "Suporte prioritário", "Solução personalizada"] },
};

const FEATURE_ROWS = [
  ["users", "Usuários incluídos", Users],
  ["whatsapp_numbers", "Números de WhatsApp", CreditCard],
  ["published_flows", "Fluxos publicados", Workflow],
  ["observability_retention_days", "Histórico e observabilidade", ShieldCheck],
] as const;

function formatPrice(amount: number | null, interval: "monthly" | "annual") {
  if (amount === null) return "Sob consulta";
  return `R$ ${(amount / 100).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
}

function featureValue(feature?: PlanFeature) {
  if (!feature?.enabled) return "—";
  if (feature.limit_value === null) return "Ilimitado";
  return `${feature.limit_value} ${feature.limit_unit || ""}`.trim();
}

export function PlanBadge({ status }: { status?: string | null }) {
  const legacy = status === "legacy";
  const trial = status === "trialing";
  return <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${legacy ? "bg-blue-50 text-blue-700" : trial ? "bg-violet-50 text-violet-700" : "bg-emerald-50 text-emerald-700"}`}>{legacy ? "Acesso legado" : trial ? "Trial" : status || "Sem assinatura"}</span>;
}

export function SubscriptionStatusBadge({ status }: { status?: string | null }) { return <PlanBadge status={status} />; }
export function LimitDisplay({ entitlement }: { entitlement: EffectiveEntitlement }) { return <li className="flex justify-between gap-3 text-sm text-slate-600"><span>{entitlement.feature_key.replaceAll("_", " ")}</span><span className="font-medium text-slate-900">{entitlement.limit_value === null ? "Ilimitado" : `${entitlement.limit_value} ${entitlement.limit_unit || ""}`}</span></li>; }
export function EntitlementList({ entitlements }: { entitlements: EffectiveEntitlement[] }) { return <ul className="mt-4 grid gap-2 sm:grid-cols-2">{entitlements.filter(item => item.enabled).slice(0, 12).map(item => <LimitDisplay key={item.feature_key} entitlement={item} />)}</ul>; }

export function CurrentPlanCard({ state, portal }: { state: CurrentBillingState; portal: () => void }) {
  const legacy = state.subscription?.status === "legacy";
  const trial = state.trial;
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Plano atual</p><h2 className="mt-1 text-xl font-bold text-slate-950">{trial ? "Trial Growth" : state.plan?.name || "Sem assinatura"}</h2></div><SubscriptionStatusBadge status={state.subscription?.status} /></div>{trial && <p className="mt-4 rounded-xl border border-violet-200 bg-violet-50 p-3 text-sm text-violet-900">Trial de 14 dias · {state.days_remaining} dias restantes.</p>}<p className="mt-3 text-sm leading-6 text-slate-600">{legacy ? "Seu workspace mantém acesso integral até uma assinatura Stripe ser confirmada." : state.plan?.description || "Aguardando informações da assinatura."}</p>{state.subscription?.provider === "stripe" && <button onClick={portal} className="mt-5 rounded-xl border border-slate-300 px-4 py-2 text-sm font-semibold">Gerenciar cobrança</button>}</section>;
}

export function PlanComparison({ plans, enabled, currentPlanCode, isTrial, checkout }: { plans: BillingPlan[]; enabled: boolean; currentPlanCode?: string; isTrial: boolean; checkout: (code: string, interval: "monthly" | "annual") => void }) {
  const [interval, setInterval] = useState<"monthly" | "annual">("monthly");
  const currentCode = isTrial ? "growth" : currentPlanCode;
  const publicPlans = plans.filter(plan => plan.code !== "growth_trial" && plan.code !== "legacy");
  const planByCode = useMemo(() => new Map(publicPlans.map(plan => [plan.code, plan])), [publicPlans]);
  return <section className="plan-comparison" aria-labelledby="plan-comparison-title">
    <div className="plan-comparison__header">
      <div><p className="plan-comparison__eyebrow">Planos Wazza</p><h2 id="plan-comparison-title">Comparar planos</h2><p>Escolha a estrutura ideal para o ritmo da sua operação.</p></div>
      <div className="plan-comparison__interval" aria-label="Periodicidade"><button type="button" onClick={() => setInterval("monthly")} className={interval === "monthly" ? "is-active" : ""}>Mensal</button><button type="button" onClick={() => setInterval("annual")} className={interval === "annual" ? "is-active" : ""}>Anual <span>melhor valor</span></button></div>
    </div>
    <div className="plan-comparison__rail">
      <div className="plan-comparison__grid">
        {publicPlans.map(plan => {
          const copy = PLAN_COPY[plan.code] || { description: plan.description || "Plano flexível para sua operação.", benefits: ["Recursos essenciais", "Evolução contínua", "Suporte Wazza"] };
          const amount = interval === "monthly" ? plan.monthly_price_cents : plan.annual_price_cents;
          const recommended = plan.code === "growth";
          const current = plan.code === currentCode;
          const Icon = recommended ? Sparkles : plan.code === "enterprise" ? ShieldCheck : plan.code === "business" ? Workflow : Users;
          return <article key={plan.code} className={`plan-card ${recommended ? "plan-card--recommended" : ""} ${current ? "plan-card--current" : ""}`}>
            <div className="plan-card__topline">{recommended && <span className="plan-card__badge plan-card__badge--popular"><Sparkles size={13} /> Mais popular</span>}{current && <span className="plan-card__badge plan-card__badge--current">{isTrial ? "Trial" : "Atual"}</span>}{!recommended && !current && plan.code === "enterprise" && <span className="plan-card__badge">Enterprise</span>}{!recommended && !current && plan.code !== "enterprise" && <span className="plan-card__badge">Plano</span>}</div>
            <div className="plan-card__icon"><Icon size={20} /></div><h3>{plan.name}</h3><p className="plan-card__description">{copy.description}</p>
            <div className="plan-card__price"><strong>{formatPrice(amount, interval)}</strong>{amount !== null && <span>por {interval === "monthly" ? "mês" : "ano"}</span>}</div>
            <div className="plan-card__divider" /><p className="plan-card__includes">Tudo que você precisa:</p><ul>{copy.benefits.map(benefit => <li key={benefit}><Check size={16} />{benefit}</li>)}</ul>
            <button type="button" disabled={!enabled || amount === null || current} onClick={() => checkout(plan.code, interval)} className="plan-card__cta">{current ? "Plano atual" : amount === null ? "Fale com a gente" : "Escolher plano"}{!current && amount !== null && <ArrowRight size={16} />}</button>
          </article>;
        })}
      </div>
    </div>
    <div className="plan-table-wrap"><div className="plan-table-heading"><div><p className="plan-comparison__eyebrow">Visão detalhada</p><h3>Compare recursos lado a lado</h3></div><span>Incluso em cada plano</span></div><div className="plan-table-scroll"><table className="plan-table"><thead><tr><th>Recursos</th>{publicPlans.map(plan => <th key={plan.code} className={plan.code === "growth" ? "is-recommended" : ""}>{plan.name}</th>)}</tr></thead><tbody>{FEATURE_ROWS.map(([key, label, Icon]) => <tr key={key}><th><span className="plan-table__feature-icon"><Icon size={15} /></span>{label}</th>{publicPlans.map(plan => <td key={plan.code} className={plan.code === "growth" ? "is-recommended" : ""}>{featureValue(planByCode.get(plan.code)?.features.find(feature => feature.feature_key === key))}</td>)}</tr>)}</tbody></table></div></div>
  </section>;
}

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
  return <div className="space-y-4"><header className="flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-2 text-emerald-700"><CreditCard size={20} /></span><div><h1 className="text-2xl font-bold text-slate-950">Plano e cobrança</h1><p className="text-sm text-slate-600">{state.stripe_enabled ? "Escolha um plano ou gerencie sua assinatura." : "Cobrança online temporariamente indisponível."}</p></div></header>{!state.stripe_enabled && <p className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Os pagamentos online ainda não estão disponíveis. Você pode continuar utilizando seu período de teste normalmente.</p>}{pending && <p className="rounded-xl bg-blue-50 p-3 text-sm text-blue-900">Pagamento recebido. Estamos confirmando sua assinatura.</p>}{busy && <p className="text-sm text-slate-500">Redirecionando para a cobrança segura…</p>}<CurrentPlanCard state={state} portal={() => void portal()} /><section className="rounded-2xl border border-slate-200 bg-white p-5"><h2 className="text-lg font-bold text-slate-950">Recursos e limites</h2><EntitlementList entitlements={state.effective_entitlements} /></section><PlanComparison plans={plans} enabled={Boolean(state.stripe_enabled)} currentPlanCode={state.plan?.code} isTrial={state.trial} checkout={(code, interval) => void checkout(code, interval)} /><p className="flex items-center gap-2 text-xs text-slate-500"><CheckCircle2 size={14} className="text-emerald-600" /> Nenhum recurso é bloqueado nesta fase.</p></div>;
}
