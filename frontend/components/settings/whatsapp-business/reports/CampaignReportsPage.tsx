"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  BarChart3,
  CheckCircle2,
  ChevronDown,
  Download,
  Eye,
  Inbox,
  RefreshCw,
  Search,
  Send,
  SlidersHorizontal,
  X,
  XCircle,
} from "lucide-react";
import {
  campaignAnalyticsExportUrl,
  getAccountMe,
  getCampaignAnalyticsByCampaign,
  getCampaignAnalyticsByTemplate,
  getCampaignAnalyticsFailures,
  getCampaignAnalyticsHeatmap,
  getCampaignAnalyticsSummary,
  getCampaignAnalyticsTimeline,
  listTemplates,
  listWhatsAppCampaigns,
  listWhatsAppProviders,
  CampaignAnalyticsPage,
  CampaignAnalyticsSummary,
  FailureAnalyticsRow,
  HeatmapAnalytics,
  TemplateAnalyticsRow,
  TimelineAnalytics,
} from "@/lib/api";
import {
  WhatsAppCampaign,
  WhatsAppProvider,
  WhatsAppTemplate,
} from "@/lib/types";
import CampaignDetailsDrawer from "../campaigns/CampaignDetailsDrawer";
import CampaignStatusBadge from "../campaigns/CampaignStatusBadge";
import {
  formatCompact,
  formatDateTime,
  formatInteger,
  formatPercent,
} from "./formatters";
import type { CampaignReportPreviewScenario } from "./campaignAnalyticsPreviewData";

const iso = (d: Date) => d.toISOString();
const defaultStart = (days = 30) => {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d;
};
const rate = (a?: number | null, b?: number | null) =>
  b ? (Number(a || 0) / b) * 100 : null;
const previewFeatureEnabled =
  process.env.NEXT_PUBLIC_ENABLE_CAMPAIGN_ANALYTICS_PREVIEW === "true";
const authorizedPreviewRoles = new Set(["owner", "admin"]);
const previewScenarioLabels: Record<CampaignReportPreviewScenario, string> = {
  low: "Volume baixo",
  medium: "Volume médio",
  high: "Volume alto",
  failures: "Muitas falhas",
};
const previewScenarioValues = Object.keys(
  previewScenarioLabels,
) as CampaignReportPreviewScenario[];
const isPreviewScenario = (value: string): value is CampaignReportPreviewScenario =>
  previewScenarioValues.includes(value as CampaignReportPreviewScenario);
const colors = {
  sent: "#64748b",
  delivered: "#059669",
  read: "#4f46e5",
  failed: "#dc2626",
};
const metricOptions = [
  ["total_recipients", "Audiência"],
  ["total_sent", "Enviadas"],
  ["total_delivered", "Entregues"],
  ["total_read", "Lidas"],
  ["total_failed", "Falhas"],
  ["delivery_rate", "Taxa entrega"],
  ["read_rate", "Taxa leitura"],
] as const;

type Filters = {
  campaign_id: string;
  template_id: string;
  provider_id: string;
  status: string;
  template_category: string;
  template_language: string;
  search: string;
};
const emptyFilters: Filters = {
  campaign_id: "",
  template_id: "",
  provider_id: "",
  status: "",
  template_category: "",
  template_language: "",
  search: "",
};

function ReportsEmptyState({
  title = "Nenhum dado no período",
  text = "Os resultados aparecerão após a execução das campanhas.",
}: {
  title?: string;
  text?: string;
}) {
  return (
    <div className="flex min-h-[180px] flex-col items-center justify-center rounded-2xl bg-slate-50/80 px-5 py-8 text-center">
      <Inbox size={22} className="text-slate-400" />
      <p className="mt-3 text-sm font-semibold text-slate-700">{title}</p>
      <p className="mt-1 max-w-sm text-sm text-slate-500">{text}</p>
    </div>
  );
}
function Shell({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-[18px] bg-white shadow-[0_18px_50px_-45px_rgba(15,23,42,.5)] ring-1 ring-[#E7EAF0] ${className}`}
    >
      {children}
    </section>
  );
}
function SelectShell({
  label,
  value,
  onChange,
  children,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`relative ${className}`}>
      <span className="sr-only">{label}</span>
      <select
        aria-label={label}
        className="h-10 w-full appearance-none rounded-xl border border-slate-200 bg-white py-2 pl-3 pr-9 text-sm font-medium text-slate-700 shadow-sm outline-none transition focus:border-emerald-300 focus:ring-4 focus:ring-emerald-100"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {children}
      </select>
      <ChevronDown
        size={15}
        className="pointer-events-none absolute right-3 top-3 text-slate-400"
      />
    </label>
  );
}
function ReportsHeader({
  onReload,
  exportHref,
  previewActive = false,
}: {
  onReload: () => void;
  exportHref: string;
  previewActive?: boolean;
}) {
  return (
    <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
      <div>
        <h1 className="text-[30px] font-semibold tracking-[-.03em] text-slate-950">
          Relatórios
        </h1>
        <p className="mt-1 text-sm text-slate-600">
          Desempenho das campanhas de WhatsApp.
        </p>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onReload}
          className="inline-flex h-10 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50"
        >
          <RefreshCw size={15} />
          Atualizar
        </button>
        {previewActive ? (
          <button
            type="button"
            disabled
            title="Indisponível no modo demonstração."
            className="inline-flex h-10 cursor-not-allowed items-center gap-2 rounded-xl bg-slate-300 px-4 text-sm font-semibold text-white shadow-sm"
          >
            <Download size={15} />
            Exportar CSV
          </button>
        ) : (
          <a
            className="inline-flex h-10 items-center gap-2 rounded-xl bg-slate-950 px-4 text-sm font-semibold text-white shadow-sm hover:bg-slate-800"
            href={exportHref}
          >
            <Download size={15} />
            Exportar CSV
          </a>
        )}
      </div>
    </div>
  );
}
function ReportsFilterBar({
  period,
  quick,
  start,
  end,
  setStart,
  setEnd,
  filters,
  setFilters,
  providers,
  allCampaigns,
  allTemplates,
}: any) {
  const presets = [
    ["today", "Hoje"],
    ["7", "7 dias"],
    ["30", "30 dias"],
    ["90", "90 dias"],
    ["custom", "Personalizado"],
  ];
  return (
    <Shell className="p-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex h-10 rounded-xl bg-slate-100 p-1">
          {presets.map(([v, l]) => (
            <button
              key={v}
              onClick={() => quick(v)}
              className={`rounded-lg px-3 text-xs font-semibold transition ${period === v ? "bg-white text-emerald-700 shadow-sm" : "text-slate-600 hover:text-slate-900"}`}
            >
              {l}
            </button>
          ))}
        </div>
        <input
          aria-label="Período inicial"
          type="datetime-local"
          className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm outline-none focus:border-emerald-300 focus:ring-4 focus:ring-emerald-100"
          value={start.slice(0, 16)}
          onChange={(e) => setStart(new Date(e.target.value).toISOString())}
        />
        <span className="text-slate-400">→</span>
        <input
          aria-label="Período final"
          type="datetime-local"
          className="h-10 rounded-xl border border-slate-200 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm outline-none focus:border-emerald-300 focus:ring-4 focus:ring-emerald-100"
          value={end.slice(0, 16)}
          onChange={(e) => setEnd(new Date(e.target.value).toISOString())}
        />
        <SelectShell
          label="Remetente"
          value={filters.provider_id}
          onChange={(provider_id) => setFilters({ ...filters, provider_id })}
        >
          <option value="">Remetente</option>
          {providers.map((p: WhatsAppProvider) => (
            <option key={p.id} value={p.id}>
              {p.display_name || p.phone_number_id || p.id}
            </option>
          ))}
        </SelectShell>
        <SelectShell
          label="Status"
          value={filters.status}
          onChange={(status) => setFilters({ ...filters, status })}
        >
          <option value="">Status</option>
          {[
            "draft",
            "scheduled",
            "running",
            "paused",
            "completed",
            "cancelled",
            "failed",
          ].map((s) => (
            <option key={s}>{s}</option>
          ))}
        </SelectShell>
        <SelectShell
          label="Campanha"
          value={filters.campaign_id}
          onChange={(campaign_id) => setFilters({ ...filters, campaign_id })}
          className="min-w-[190px] flex-1"
        >
          <option value="">Campanha</option>
          {allCampaigns.map((c: WhatsAppCampaign) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </SelectShell>
        <SelectShell
          label="Template"
          value={filters.template_id}
          onChange={(template_id) => setFilters({ ...filters, template_id })}
          className="min-w-[160px]"
        >
          <option value="">Template</option>
          {allTemplates.map((t: WhatsAppTemplate) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </SelectShell>
        <button
          className="ml-auto h-10 rounded-xl px-3 text-sm font-semibold text-slate-500 hover:bg-slate-100 hover:text-slate-900"
          onClick={() => setFilters(emptyFilters)}
        >
          Limpar
        </button>
      </div>
    </Shell>
  );
}
function ExecutiveMetrics({
  summary,
}: {
  summary: CampaignAnalyticsSummary | null;
}) {
  const items = [
    ["Enviadas", summary?.total_sent, "Eventos processados", Send, colors.sent],
    [
      "Entregues",
      summary?.total_delivered,
      `${formatPercent(summary?.delivery_rate)} das enviadas`,
      CheckCircle2,
      colors.delivered,
    ],
    [
      "Lidas",
      summary?.total_read,
      `${formatPercent(summary?.read_rate)} das entregues`,
      Eye,
      colors.read,
    ],
    [
      "Falhas",
      summary?.total_failed,
      `${formatPercent(summary?.failure_rate)} dos destinatários`,
      XCircle,
      colors.failed,
    ],
  ] as const;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {items.map(([label, value, hint, Icon, color]) => (
        <Shell key={label} className="p-5">
          <div className="flex items-start justify-between">
            <p className="text-[11px] font-semibold uppercase tracking-[.12em] text-slate-500">
              {label}
            </p>
            <Icon size={18} style={{ color }} />
          </div>
          <p
            title={formatInteger(value)}
            className="mt-4 text-4xl font-semibold tracking-[-.04em] tabular-nums"
            style={{ color }}
          >
            {formatCompact(value)}
          </p>
          <p className="mt-2 text-sm text-slate-600">{hint}</p>
          <div className="mt-4 flex h-8 items-end gap-1">
            {[35, 52, 44, 64, 58, 76, 68].map((h, i) => (
              <span key={i} className="flex-1 rounded-full bg-slate-100">
                <span
                  className="block rounded-full"
                  style={{
                    height: `${h}%`,
                    backgroundColor: color,
                    opacity: 0.22,
                  }}
                />
              </span>
            ))}
          </div>
        </Shell>
      ))}
    </div>
  );
}
function SecondaryMetricsStrip({
  summary,
}: {
  summary: CampaignAnalyticsSummary | null;
}) {
  const items = [
    ["Campanhas", summary?.campaigns_created],
    ["Concluídas", summary?.campaigns_completed],
    ["Destinatários", summary?.total_recipients],
    ["Entrega", formatPercent(summary?.delivery_rate)],
    ["Leitura", formatPercent(summary?.read_rate)],
    ["Falha", formatPercent(summary?.failure_rate)],
  ];
  return (
    <Shell className="grid grid-cols-2 divide-x divide-y divide-slate-100 overflow-hidden sm:grid-cols-3 xl:grid-cols-6 xl:divide-y-0">
      {items.map(([l, v]) => (
        <div key={l} className="px-5 py-4">
          <p className="text-xs font-medium text-slate-500">{l}</p>
          <p className="mt-1 text-lg font-semibold tabular-nums text-slate-900">
            {typeof v === "number" ? formatCompact(v) : (v ?? "—")}
          </p>
        </div>
      ))}
    </Shell>
  );
}
function CampaignTrendChart({ data }: { data: any[] }) {
  const has = data.some((d) => d.sent || d.delivered || d.read || d.failed);
  return (
    <Shell className="p-5">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Evolução temporal</h2>
          <p className="text-sm text-slate-500">
            Entregas, leituras e falhas ao longo do período.
          </p>
        </div>
        <div className="flex gap-3 text-xs font-medium">
          {Object.entries(colors).map(([k, c]) => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <i
                className="h-2 w-2 rounded-full"
                style={{ backgroundColor: c }}
              />
              {
                (
                  {
                    sent: "Enviadas",
                    delivered: "Entregues",
                    read: "Lidas",
                    failed: "Falhas",
                  } as any
                )[k]
              }
            </span>
          ))}
        </div>
      </div>
      {has ? (
        <ResponsiveContainer width="100%" height={330}>
          <LineChart
            data={data}
            margin={{ top: 18, right: 20, bottom: 0, left: 0 }}
          >
            <CartesianGrid vertical={false} stroke="#edf0f4" />
            <XAxis
              dataKey="bucket"
              minTickGap={34}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v) =>
                new Date(v).toLocaleDateString("pt-BR", {
                  day: "2-digit",
                  month: "2-digit",
                })
              }
            />
            <YAxis
              tickFormatter={formatCompact}
              width={52}
              tickLine={false}
              axisLine={false}
            />
            <Tooltip
              contentStyle={{
                borderRadius: 14,
                border: "1px solid #E7EAF0",
                boxShadow: "0 18px 40px -28px rgba(15,23,42,.5)",
              }}
              labelFormatter={(v) => formatDateTime(String(v))}
              formatter={(v: any, n) => [formatInteger(Number(v)), n]}
            />
            {Object.entries(colors).map(([k, c]) => (
              <Line
                key={k}
                dot={false}
                activeDot={{ r: 4 }}
                strokeWidth={2.5}
                type="monotone"
                dataKey={k}
                name={
                  (
                    {
                      sent: "Enviadas",
                      delivered: "Entregues",
                      read: "Lidas",
                      failed: "Falhas",
                    } as any
                  )[k]
                }
                stroke={c}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <ReportsEmptyState
          title="Nenhum evento no período"
          text="As entregas, leituras e falhas aparecerão aqui após a execução das campanhas."
        />
      )}
    </Shell>
  );
}
function CampaignFunnel({
  summary,
}: {
  summary: CampaignAnalyticsSummary | null;
}) {
  const f = [
    ["Destinatários", summary?.total_recipients],
    ["Enviadas", summary?.total_sent],
    ["Entregues", summary?.total_delivered],
    ["Lidas", summary?.total_read],
  ] as const;
  return (
    <Shell className="p-5">
      <h2 className="text-lg font-semibold">Funil de desempenho</h2>
      <div className="mt-5 space-y-5">
        {f.map(([label, val], i) => {
          const prev = i ? f[i - 1][1] : val;
          const pct = i ? rate(val, prev) : 100;
          const loss = i
            ? Math.max(Number(prev || 0) - Number(val || 0), 0)
            : 0;
          return (
            <div key={label}>
              <div className="flex items-end justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-slate-800">
                    {label}
                  </p>
                  <p className="text-xs text-slate-500">
                    {i ? `Perda: ${formatInteger(loss)}` : "Base do funil"}
                  </p>
                </div>
                <div className="text-right">
                  <p className="font-semibold tabular-nums">
                    {formatInteger(val)}
                  </p>
                  <p className="text-xs text-slate-500">
                    {i ? (pct == null ? "—" : formatPercent(pct)) : "100%"}
                  </p>
                </div>
              </div>
              <div className="mt-2 h-2.5 rounded-full bg-slate-100">
                <div
                  className="h-2.5 rounded-full bg-emerald-600"
                  style={{
                    width: `${Math.max(2, Math.min(rate(val, summary?.total_recipients) || 0, 100))}%`,
                  }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </Shell>
  );
}
function CampaignTable({
  campaigns,
  filters,
  setFilters,
  compare,
  setCompare,
  setSelected,
}: any) {
  return (
    <Shell className="overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-5">
        <div>
          <h2 className="text-lg font-semibold">Campanhas</h2>
          <p className="text-sm text-slate-500">
            Selecione de 2 a 5 campanhas para comparar.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="h-10 rounded-xl border border-slate-200 px-3 text-sm font-semibold text-slate-700">
            <SlidersHorizontal size={15} className="mr-2 inline" />
            Ordenar
          </button>
          <label className="relative">
            <Search
              size={15}
              className="absolute left-3 top-3 text-slate-400"
            />
            <input
              className="h-10 rounded-xl border border-slate-200 pl-9 pr-3 text-sm outline-none focus:border-emerald-300 focus:ring-4 focus:ring-emerald-100"
              placeholder="Buscar"
              value={filters.search}
              onChange={(e) =>
                setFilters({ ...filters, search: e.target.value })
              }
            />
          </label>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[980px] text-[13px]">
          <thead className="bg-slate-50 text-left text-xs font-semibold text-slate-500">
            <tr>
              {[
                "",
                "Campanha",
                "Status",
                "Audiência",
                "Entregues",
                "Lidas",
                "Falhas",
                "Taxa de leitura",
                "Início",
                "Ações",
              ].map((h, i) => (
                <th
                  className={`px-4 py-3 ${i > 2 && i < 8 ? "text-right" : ""}`}
                  key={i}
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {campaigns?.items.map((c: WhatsAppCampaign & any) => (
              <tr key={c.id} className="hover:bg-slate-50/70">
                <td className="px-4 py-4">
                  <input
                    aria-label={`Comparar ${c.name}`}
                    type="checkbox"
                    checked={compare.includes(c.id)}
                    disabled={!compare.includes(c.id) && compare.length >= 5}
                    onChange={(e) =>
                      setCompare(
                        e.target.checked
                          ? [...compare, c.id]
                          : compare.filter((id: string) => id !== c.id),
                      )
                    }
                  />
                </td>
                <td className="max-w-[290px] px-4 py-4">
                  <button
                    title={c.name}
                    className="block truncate text-left font-semibold text-slate-900 hover:text-emerald-700"
                    onClick={() => setSelected(c)}
                  >
                    {c.name}
                  </button>
                  <p className="truncate text-xs text-slate-500">
                    {c.template_name ||
                      c.template_id ||
                      "Template não informado"}
                  </p>
                </td>
                <td className="px-4 py-4">
                  <CampaignStatusBadge status={c.status} />
                </td>
                {[
                  c.total_recipients,
                  c.total_delivered,
                  c.total_read,
                  c.total_failed,
                ].map((v, i) => (
                  <td key={i} className="px-4 py-4 text-right tabular-nums">
                    {formatInteger(v)}
                  </td>
                ))}
                <td className="px-4 py-4 text-right">
                  <span className="font-semibold">
                    {formatPercent(c.read_rate)}
                  </span>
                  <div className="mt-1 h-1.5 rounded-full bg-slate-100">
                    <div
                      className="h-1.5 rounded-full bg-indigo-500"
                      style={{ width: `${Math.min(c.read_rate || 0, 100)}%` }}
                    />
                  </div>
                </td>
                <td className="px-4 py-4 text-slate-600">
                  {formatDateTime(c.started_at)}
                </td>
                <td className="px-4 py-4">
                  <button
                    onClick={() => setSelected(c)}
                    className="font-semibold text-emerald-700"
                  >
                    Detalhes
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!campaigns?.items.length && (
        <div className="p-5">
          <ReportsEmptyState />
        </div>
      )}
    </Shell>
  );
}
function TemplateRanking({ templates }: { templates: TemplateAnalyticsRow[] }) {
  const maxRead = Math.max(...templates.map((t) => t.read_rate || 0), 1);
  return (
    <Shell className="p-5">
      <h2 className="text-lg font-semibold">Templates com melhor desempenho</h2>
      {templates.length ? (
        <div className="mt-4 space-y-3">
          {templates.map((t, i) => (
            <div
              key={t.template_id}
              className="flex items-center gap-3 rounded-2xl bg-slate-50 p-3"
            >
              <span className="grid h-8 w-8 place-items-center rounded-full bg-white text-sm font-bold text-slate-500">
                {i + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate font-semibold">{t.template_name}</p>
                <p className="text-sm text-slate-500">
                  {formatPercent(t.read_rate)} leitura · {t.campaigns} campanhas
                </p>
                <div className="mt-2 h-1.5 rounded-full bg-white">
                  <div
                    className="h-1.5 rounded-full bg-indigo-500"
                    style={{
                      width: `${Math.max(2, ((t.read_rate || 0) / maxRead) * 100)}%`,
                    }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <ReportsEmptyState />
      )}
    </Shell>
  );
}
function FailureSummary({ failures }: { failures: FailureAnalyticsRow[] }) {
  const maxFailure = Math.max(...failures.map((f) => f.count), 1);
  return (
    <Shell className="p-5">
      <h2 className="text-lg font-semibold">Principais falhas</h2>
      {failures.length ? (
        <div className="mt-4 space-y-3">
          {failures
            .sort((a, b) => b.count - a.count)
            .map((f) => (
              <div key={f.category} className="rounded-2xl bg-slate-50 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold">{f.category}</p>
                    <p className="text-sm text-slate-500">
                      {formatInteger(f.count)} ocorrências ·{" "}
                      {formatPercent(f.percent)}
                    </p>
                  </div>
                  <span className="h-2 w-24 rounded-full bg-white">
                    <span
                      className="block h-2 rounded-full bg-rose-500"
                      style={{ width: `${(f.count / maxFailure) * 100}%` }}
                    />
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-600">
                  {f.recommendation}
                </p>
              </div>
            ))}
        </div>
      ) : (
        <ReportsEmptyState />
      )}
    </Shell>
  );
}
function CampaignHeatmap({ heatmap }: { heatmap: HeatmapAnalytics | null }) {
  const maxHeat = Math.max(...(heatmap?.items || []).map((h) => h.count), 1);
  return (
    <Shell className="p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Atividade por dia e horário</h2>
          <p className="text-sm text-slate-500">
            Distribuição de envios, entregas e leituras no timezone do tenant.
          </p>
        </div>
        <SelectShell
          label="Métrica do heatmap"
          value="read"
          onChange={() => {}}
        >
          <option value="read">Leituras</option>
        </SelectShell>
      </div>
      {heatmap?.sufficient_data ? (
        <div className="mt-5 overflow-x-auto">
          <div className="grid min-w-[760px] grid-cols-[72px_repeat(24,1fr)] gap-1 text-[10px]">
            <span />
            {Array.from({ length: 24 }, (_, h) => (
              <span key={h} className="text-center text-slate-400">
                {h}
              </span>
            ))}
            {["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"].map((d, wd) => (
              <div key={d} className="contents">
                <span className="py-1 text-slate-500">{d}</span>
                {Array.from({ length: 24 }, (_, h) => {
                  const cell = heatmap.items.find(
                    (x) => x.weekday === wd && x.hour === h,
                  );
                  const opacity = Math.max(0.08, (cell?.count || 0) / maxHeat);
                  return (
                    <span
                      key={`${wd}-${h}`}
                      title={`${d}, ${h}h: ${formatInteger(cell?.count || 0)}`}
                      className="h-6 rounded"
                      style={{ backgroundColor: `rgba(16,185,129,${opacity})` }}
                    />
                  );
                })}
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">
            Legenda: quanto mais intenso, maior a atividade.
          </p>
        </div>
      ) : (
        <ReportsEmptyState />
      )}
    </Shell>
  );
}
function CampaignComparisonDrawer({
  open,
  onClose,
  compared,
  metric,
  setMetric,
}: any) {
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-slate-950/20"
      onClick={onClose}
    >
      <aside
        className="h-full w-full max-w-xl bg-white p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold">Comparar campanhas</h2>
            <p className="text-sm text-slate-500">
              Selecione de 2 a 5 campanhas na tabela.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-2 hover:bg-slate-100"
          >
            <X size={18} />
          </button>
        </div>
        <div className="mt-5">
          <SelectShell label="Métrica" value={metric} onChange={setMetric}>
            {metricOptions.map(([v, l]) => (
              <option key={v} value={v}>
                {l}
              </option>
            ))}
          </SelectShell>
        </div>
        {compared.length >= 2 ? (
          <>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart
                data={compared}
                margin={{ top: 20, right: 10, left: 0, bottom: 0 }}
              >
                <CartesianGrid vertical={false} stroke="#edf0f4" />
                <XAxis dataKey="name" hide />
                <YAxis tickFormatter={formatCompact} />
                <Tooltip
                  formatter={(v: any) =>
                    metric.includes("rate")
                      ? formatPercent(Number(v))
                      : formatInteger(Number(v))
                  }
                />
                <Bar dataKey={metric} fill="#059669" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            <div className="mt-4 divide-y divide-slate-100">
              {compared.map((c: any) => (
                <div
                  key={c.id}
                  className="flex justify-between gap-3 py-3 text-sm"
                >
                  <span className="truncate font-medium">{c.name}</span>
                  <span className="font-semibold tabular-nums">
                    {metric.includes("rate")
                      ? formatPercent(c[metric])
                      : formatInteger(c[metric])}
                  </span>
                </div>
              ))}
            </div>
          </>
        ) : (
          <div className="mt-6">
            <ReportsEmptyState
              title="Seleção insuficiente"
              text="Escolha pelo menos duas campanhas para visualizar a comparação."
            />
          </div>
        )}
      </aside>
    </div>
  );
}

export default function CampaignReportsPage() {
  const [period, setPeriod] = useState("30");
  const [start, setStart] = useState(iso(defaultStart()));
  const [end, setEnd] = useState(iso(new Date()));
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [summary, setSummary] = useState<CampaignAnalyticsSummary | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignAnalyticsPage | null>(
    null,
  );
  const [templates, setTemplates] = useState<TemplateAnalyticsRow[]>([]);
  const [timeline, setTimeline] = useState<TimelineAnalytics | null>(null);
  const [failures, setFailures] = useState<FailureAnalyticsRow[]>([]);
  const [heatmap, setHeatmap] = useState<HeatmapAnalytics | null>(null);
  const [allCampaigns, setAllCampaigns] = useState<WhatsAppCampaign[]>([]);
  const [allTemplates, setAllTemplates] = useState<WhatsAppTemplate[]>([]);
  const [providers, setProviders] = useState<WhatsAppProvider[]>([]);
  const [selected, setSelected] = useState<WhatsAppCampaign | null>(null);
  const [compare, setCompare] = useState<string[]>([]);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [metric, setMetric] = useState("total_delivered");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [preview, setPreview] = useState<CampaignReportPreviewScenario | "">(
    "",
  );
  const [previewPickerOpen, setPreviewPickerOpen] = useState(false);
  const [previewAuthorized, setPreviewAuthorized] = useState(false);
  const params = useMemo(
    () => ({ start, end, ...filters }),
    [start, end, filters],
  );
  const previewAllowed = previewFeatureEnabled && previewAuthorized;
  const previewActive = previewAllowed && !!preview;
  const applyPreview = useCallback(
    async (scenario: CampaignReportPreviewScenario) => {
      if (!previewAllowed) return;
      const { buildCampaignReportPreview } = await import("./campaignAnalyticsPreviewData");
      const data = buildCampaignReportPreview(scenario);
      setSummary(data.summary);
      setCampaigns(data.campaigns);
      setTemplates(data.templates);
      setTimeline(data.timeline);
      setFailures(data.failures);
      setHeatmap(data.heatmap);
      setAllCampaigns(data.allCampaigns);
      setAllTemplates(data.allTemplates);
      setProviders(data.providers);
      setCompare([]);
      setSelected(null);
      setUpdated(new Date());
      setError("");
      setLoading(false);
    },
    [previewAllowed],
  );
  const reload = useCallback(async () => {
    if (previewAllowed && preview) {
      await applyPreview(preview);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const [s, c, t, l, f, h] = await Promise.all([
        getCampaignAnalyticsSummary(params),
        getCampaignAnalyticsByCampaign({ ...params, page_size: 20 }),
        getCampaignAnalyticsByTemplate(params),
        getCampaignAnalyticsTimeline(params),
        getCampaignAnalyticsFailures(params),
        getCampaignAnalyticsHeatmap({ ...params, metric: "read" }),
      ]);
      setSummary(s);
      setCampaigns(c);
      setTemplates(t);
      setTimeline(l);
      setFailures(f);
      setHeatmap(h);
      setUpdated(new Date());
    } catch (e: any) {
      setError(e?.message || "Falha ao carregar relatórios");
    } finally {
      setLoading(false);
    }
  }, [params, preview, applyPreview, previewAllowed]);
  useEffect(() => {
    if (previewActive) return;
    void Promise.all([
      listWhatsAppCampaigns(),
      listTemplates(),
      listWhatsAppProviders(),
    ]).then(([c, t, p]) => {
      setAllCampaigns(c);
      setAllTemplates(t);
      setProviders(p);
    });
  }, [previewActive]);
  useEffect(() => {
    if (!previewFeatureEnabled) return;
    void getAccountMe()
      .then((account) => {
        const role = String(account.profile?.role || "").toLowerCase();
        setPreviewAuthorized(authorizedPreviewRoles.has(role));
      })
      .catch(() => setPreviewAuthorized(false));
  }, []);
  useEffect(() => {
    if (!previewAllowed) {
      setPreview("");
      return;
    }
    const raw = new URLSearchParams(window.location.search).get("preview") || "";
    if (isPreviewScenario(raw)) setPreview(raw);
  }, [previewAllowed]);
  useEffect(() => {
    void reload();
  }, [reload]);
  function quick(v: string) {
    setPeriod(v);
    if (v === "custom") return;
    const now = new Date();
    const s = new Date(now);
    if (v === "today") s.setHours(0, 0, 0, 0);
    else s.setDate(s.getDate() - Number(v));
    setStart(iso(s));
    setEnd(iso(now));
  }
  const filteredCampaigns = useMemo(() => {
    if (!previewActive || !campaigns) return campaigns;
    const startMs = new Date(start).getTime();
    const endMs = new Date(end).getTime();
    const items = campaigns.items.filter((c: any) => {
      const started = c.started_at ? new Date(c.started_at).getTime() : 0;
      return (
        (!filters.campaign_id || c.id === filters.campaign_id) &&
        (!filters.template_id || c.template_id === filters.template_id) &&
        (!filters.provider_id || c.provider_id === filters.provider_id) &&
        (!filters.status || c.status === filters.status) &&
        (!filters.search || c.name.toLowerCase().includes(filters.search.toLowerCase())) &&
        (!started || (started >= startMs && started <= endMs))
      );
    });
    return { ...campaigns, items, total: items.length };
  }, [campaigns, end, filters, previewActive, start]);
  const displayAnalyticsData = {
    summary,
    campaigns: filteredCampaigns,
    templates,
    timeline,
    failures,
    heatmap,
  };
  const compared = (displayAnalyticsData.campaigns?.items || []).filter((c) =>
    compare.includes(c.id),
  );
  return (
    <div className="min-h-screen bg-[#F7F8FA] px-4 py-6 text-slate-950 sm:px-6 lg:px-8">
      <div className="mx-auto max-w-[1440px] space-y-7">
        <div className="space-y-4">
          <ReportsHeader
            onReload={() => void reload()}
            exportHref={campaignAnalyticsExportUrl({
              ...params,
              type: "campaigns",
            })}
            previewActive={previewActive}
          />
          <ReportsFilterBar
            period={period}
            quick={quick}
            start={start}
            end={end}
            setStart={setStart}
            setEnd={setEnd}
            filters={filters}
            setFilters={setFilters}
            providers={providers}
            allCampaigns={allCampaigns}
            allTemplates={allTemplates}
          />
          {previewActive && (
            <div className="sticky top-2 z-30 flex flex-wrap items-center gap-2 rounded-2xl border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950 shadow-sm">
              <span className="font-bold">Modo demonstração — estes dados não são reais.</span>
              <button type="button" onClick={() => setPreviewPickerOpen(true)} className="font-semibold underline">Trocar cenário</button>
              <button
                type="button"
                onClick={() => {
                  setPreview("");
                  setPreviewPickerOpen(false);
                  window.history.replaceState(null, "", window.location.pathname);
                }}
                className="font-semibold underline"
              >
                Sair da demonstração
              </button>
            </div>
          )}
          {previewAllowed && (
            <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              <button
                type="button"
                onClick={() => setPreviewPickerOpen(!previewPickerOpen)}
                className="rounded-xl bg-amber-500 px-3 py-2 font-semibold text-white shadow-sm hover:bg-amber-600"
              >
                Visualizar demonstração
              </button>
              {preview && (
                <span className="font-semibold">
                  Ativo:{" "}
                  {preview ? previewScenarioLabels[preview] : ""}
                </span>
              )}
              {previewPickerOpen && (
                <div className="flex flex-wrap items-center gap-2">
                  {previewScenarioValues.map((s) => (
                    <button
                      key={s}
                      onClick={() => {
                        setPreview(s);
                        window.history.replaceState(null, "", `?preview=${s}`);
                      }}
                      className={`rounded-full px-2.5 py-1 font-semibold ${preview === s ? "bg-amber-200" : "bg-white"}`}
                    >
                      {previewScenarioLabels[s]}
                    </button>
                  ))}
                  <button
                    onClick={() => {
                      setPreview("");
                      setPreviewPickerOpen(false);
                      window.history.replaceState(null, "", window.location.pathname);
                    }}
                    className="underline"
                  >
                    voltar aos dados reais
                  </button>
                </div>
              )}
              <span className="text-amber-700">
                Disponível somente com NEXT_PUBLIC_ENABLE_CAMPAIGN_ANALYTICS_PREVIEW=true e perfil administrativo.
              </span>
            </div>
          )}
        </div>
        {error && (
          <div className="rounded-2xl border border-rose-200 bg-rose-50 p-4 text-rose-700">
            {error}{" "}
            <button onClick={() => void reload()} className="underline">
              Tentar novamente
            </button>
          </div>
        )}
        <div className="space-y-3">
          <ExecutiveMetrics summary={displayAnalyticsData.summary} />
          <SecondaryMetricsStrip summary={displayAnalyticsData.summary} />
        </div>
        <section className="grid gap-5 xl:grid-cols-[minmax(0,1.85fr)_minmax(320px,1fr)]">
          <CampaignTrendChart data={displayAnalyticsData.timeline?.items || []} />
          <CampaignFunnel summary={displayAnalyticsData.summary} />
        </section>
        <div className="space-y-5">
          <div className="flex justify-end">
            <button
              onClick={() => setComparisonOpen(true)}
              className="inline-flex h-10 items-center gap-2 rounded-xl bg-emerald-600 px-4 text-sm font-semibold text-white shadow-sm hover:bg-emerald-700"
            >
              <BarChart3 size={15} />
              Comparar campanhas
            </button>
          </div>
          <CampaignTable
            campaigns={displayAnalyticsData.campaigns}
            filters={filters}
            setFilters={setFilters}
            compare={compare}
            setCompare={setCompare}
            setSelected={previewActive ? () => undefined : setSelected}
          />
          <section className="grid gap-5 xl:grid-cols-2">
            <TemplateRanking templates={displayAnalyticsData.templates} />
            <FailureSummary failures={displayAnalyticsData.failures} />
          </section>
          <CampaignHeatmap heatmap={displayAnalyticsData.heatmap} />
        </div>
        <p className="text-xs text-slate-500">
          {updated
            ? `Última atualização: ${updated.toLocaleString("pt-BR")}`
            : "Atualizado há poucos segundos"}
        </p>
        {selected && (
          <CampaignDetailsDrawer
            campaign={selected}
            template={allTemplates.find((t) => t.id === selected.template_id)}
            onClose={() => setSelected(null)}
            actions={null}
          />
        )}
        <CampaignComparisonDrawer
          open={comparisonOpen}
          onClose={() => setComparisonOpen(false)}
          compared={compared}
          metric={metric}
          setMetric={setMetric}
        />
      </div>
    </div>
  );
}
