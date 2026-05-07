'use client';

import { useEffect, useId, useMemo, useState } from 'react';
import Link from 'next/link';
import { Cell, Pie, PieChart } from 'recharts';
import { useRouter } from 'next/navigation';
import { MessageSquare } from "lucide-react";

import DashboardChart from '../../components/DashboardChart';
import { createFlow, getConversations, listFlows } from '../../lib/api';
import { Conversation, FlowItem, FlowPayload } from '../../lib/types';
import { useDashboardAnalytics } from '../../hooks/useDashboardAnalytics';

type DashboardViewModel = {
  activeConversations: number;
  activeLeads: number;
  messagesToday: number;
  responseRate: number;
  conversions: number;
  topFlows: Array<{ name: string; value: number }>;
  channels: Array<{ name: string; value: number }>;
};

type Period = '24h' | '7d' | '30d' | '90d';

const FALLBACK_VIEW_MODEL: DashboardViewModel = {
  activeConversations: 0,
  activeLeads: 0,
  messagesToday: 0,
  responseRate: 0,
  conversions: 0,
  topFlows: [],
  channels: [{ name: 'WhatsApp', value: 100 }],
};


function getInitials(name?: string) {
  if (!name) return '—';

  const normalized = name.trim();
  if (!normalized) return '—';
  if (/^\+?\d+$/.test(normalized)) return 'U';

  const parts = normalized.split(' ').filter(Boolean);

  if (parts.length === 1) {
    return parts[0][0].toUpperCase();
  }

  const first = parts[0][0];
  const last = parts[parts.length - 1][0];

  return (first + last).toUpperCase();
}

function getGreeting() {
  const hour = new Date().getHours();

  if (hour >= 5 && hour < 12) return 'Bom dia';
  if (hour >= 12 && hour < 18) return 'Boa tarde';
  return 'Boa noite';
}

const cardClassName =
  'bg-white rounded-2xl border border-slate-100 shadow-[0_12px_30px_rgba(15,23,42,0.05)] p-5';

function SkeletonLine({ width = '100%', height = 12 }: { width?: string; height?: number }) {
  return <div className="rounded-full bg-gradient-to-r from-emerald-50 via-slate-200 to-emerald-50" style={{ width, height }} />;
}

const Sparkline = ({ values = [], className = 'h-full w-full overflow-hidden' }: { values?: number[]; className?: string }) => {
  const gradientId = useId();
  const glowId = useId();
  const safeValues = values.length ? values : [0,0,0,0,0,0,0];
  const maxValue = Math.max(...safeValues, 1);
  const step = safeValues.length > 1 ? 62 / (safeValues.length - 1) : 62;
  const linePath = safeValues.map((value, index) => { const x = 1 + (index * step); const y = 22 - ((value / maxValue) * 18); return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`; }).join(' ');

  return (
    <svg width="64" height="24" viewBox="0 0 64 24" className={className} fill="none" aria-hidden>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#22c55e" stopOpacity="0.35" />
          <stop offset="60%" stopColor="#22c55e" stopOpacity="0.15" />
          <stop offset="100%" stopColor="#22c55e" stopOpacity="0" />
        </linearGradient>
        <filter id={glowId} x="-50%" y="-50%" width="200%" height="200%">
          <feDropShadow dx="0" dy="0" stdDeviation="1.5" floodColor="#22c55e" floodOpacity="0.4" />
        </filter>
      </defs>
      <path d={`${linePath} L 63,24 L 1,24 Z`} fill={`url(#${gradientId})`} />
      <path d={linePath} stroke="#22c55e" fill="none" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" filter={`url(#${glowId})`} />
    </svg>
  );
};



type DashboardTimeseries = {
  labels?: string[];
  conversations?: number[];
  leads?: number[];
  messages_received?: number[];
  messages_sent?: number[];
  conversions?: number[];
};

function toSafeNumber(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function toSafeArray(values?: number[]): number[] {
  if (!Array.isArray(values)) return [];
  return values.map((value) => toSafeNumber(value));
}

function getKpiSeries(key: (typeof kpiMeta)[number]['key'], timeseries?: DashboardTimeseries): number[] {
  const safeTimeseries = timeseries ?? {};

  switch (key) {
    case 'activeConversations':
      return toSafeArray(safeTimeseries.conversations);
    case 'activeLeads':
      return toSafeArray(safeTimeseries.leads);
    case 'messagesToday':
      return toSafeArray(safeTimeseries.messages_received);
    case 'responseRate': {
      const sent = toSafeArray(safeTimeseries.messages_sent);
      const received = toSafeArray(safeTimeseries.messages_received);
      const maxLength = Math.max(sent.length, received.length);
      return Array.from({ length: maxLength }, (_, index) => {
        const sentValue = sent[index] ?? 0;
        const receivedValue = received[index] ?? 0;
        if (receivedValue <= 0) return 0;
        return (sentValue / receivedValue) * 100;
      });
    }
    case 'conversions':
      return toSafeArray(safeTimeseries.conversions);
    default:
      return [0, 0, 0, 0, 0, 0, 0];
  }
}

function getDeltaPercent(series: number[]): number {
  const safeSeries = toSafeArray(series);
  if (!safeSeries.length) return 0;

  const midpoint = Math.floor(safeSeries.length / 2);
  if (midpoint <= 0) return 0;

  const firstHalf = safeSeries.slice(0, midpoint);
  const secondHalf = safeSeries.slice(midpoint);

  const firstSum = firstHalf.reduce((sum, value) => sum + value, 0);
  const secondSum = secondHalf.reduce((sum, value) => sum + value, 0);

  if (firstSum <= 0) {
    if (secondSum <= 0) return 0;
    return 100;
  }

  const delta = ((secondSum - firstSum) / firstSum) * 100;
  return Number.isFinite(delta) ? Math.round(delta) : 0;
}
const kpiMeta = [
  { key: 'activeConversations', label: 'Conversas ativas', icon: '/icons/dashboard/conversas.svg', suffix: '' },
  { key: 'activeLeads', label: 'Leads ativos', icon: '/icons/dashboard/leads.svg', suffix: '' },
  { key: 'messagesToday', label: 'Mensagens hoje', icon: '/icons/dashboard/mensagens.svg', suffix: '' },
  { key: 'responseRate', label: 'Taxa de resposta', icon: '/icons/dashboard/resposta.svg', suffix: '%' },
  { key: 'conversions', label: 'Conversões', icon: '/icons/dashboard/conversoes.svg', suffix: '' },
] as const;

const getConversationFlowLabel = (conversation: Conversation) => {
  const raw = conversation as Conversation & {
    flow_name?: string;
    flowName?: string;
    flow?: { name?: string };
    source?: string;
  };

  return raw.flow_name || raw.flowName || raw.flow?.name || raw.source || 'Flow';
};


const periodLabelMap: Record<Period, string> = {
  '24h': 'últimas 24 horas',
  '7d': 'últimos 7 dias',
  '30d': 'últimos 30 dias',
  '90d': 'últimos 90 dias',
};

const channelLegendColors: Record<string, string> = {
  whatsapp: '#16A34A',
  'site / chat': '#2563EB',
  instagram: '#8B5CF6',
  facebook: '#F59E0B',
  outros: '#94A3B8',
};

export default function DashboardPage() {
  const [period, setPeriod] = useState<Period>('7d');
  const [greeting, setGreeting] = useState('Olá');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const router = useRouter();
  const { data, kpis, timeseries, isLoading, error: dashboardError } = useDashboardAnalytics(period);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [flowsError, setFlowsError] = useState<string | null>(null);
  const [creatingFlow, setCreatingFlow] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    void (async () => {
      try { const payload = await getConversations(); setConversations(Array.isArray(payload) ? payload : []); setConversationsError(null);} catch { setConversations([]); setConversationsError('Não foi possível carregar a atividade recente no momento.'); }
      try { const payload = await listFlows(); setFlows(Array.isArray(payload) ? payload : []); setFlowsError(null);} catch { setFlows([]); setFlowsError('Não foi possível carregar os fluxos neste instante.'); }
    })();
  }, []);

  useEffect(() => {
    setGreeting(getGreeting());
  }, []);

  useEffect(() => {
    setMounted(true);
  }, []);

  async function handleCreateFlow() {
    try {
      setCreatingFlow(true);
      const initialNodeId = typeof crypto !== 'undefined' && crypto.randomUUID
        ? crypto.randomUUID()
        : `${Date.now()}`;

      const created = await createFlow({
        name: 'Novo fluxo',
        trigger_type: 'default',
        trigger_value: '',
        nodes: [
          {
            id: initialNodeId,
            type: 'message',
            position: { x: 180, y: 160 },
            data: {
              label: 'Mensagem',
              text: 'Olá! 👋',
              is_start: true,
              is_end: false,
            },
          },
        ],
        edges: [],
      } as FlowPayload & { nodes: unknown[]; edges: unknown[] });

      if (!created?.id) {
        throw new Error('Flow criado sem id');
      }

      router.push(`/dashboard/flow-builder?flow_id=${created.id}`);
    } catch (error) {
      console.error('Erro ao criar fluxo', error);
      alert('Não foi possível criar o fluxo agora.');
    } finally {
      setCreatingFlow(false);
    }
  }
  const uniqueConversations = useMemo(() => {
    const seen = new Set<string>();
    return conversations.filter((conversation) => {
      const phone = conversation.phone ?? '';
      if (!phone || seen.has(phone)) return false;
      seen.add(phone);
      return true;
    });
  }, [conversations]);

  const viewModel = useMemo<DashboardViewModel>(() => {
    const flowFallback = flows.length ? flows.slice(0, 5).map((flow) => ({ name: flow.name, value: 0 })) : FALLBACK_VIEW_MODEL.topFlows;
    const msgsToday = uniqueConversations.filter((c) => {
      const d = new Date(c.updated_at);
      const now = new Date();
      return !Number.isNaN(d.getTime()) && d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    }).length;
    return {
      activeConversations: Number(kpis?.conversations) || uniqueConversations.length || 0,
      activeLeads: Number(kpis?.leads) || uniqueConversations.filter((conversation) => conversation.mode === 'human').length || 0,
      messagesToday: Number(kpis?.messages_received) || msgsToday || 0,
      responseRate: Number(kpis?.response_rate) || 0,
      conversions: Number(kpis?.conversions) || 0,
      topFlows: flowFallback,
      channels: FALLBACK_VIEW_MODEL.channels,
    };
  }, [conversations, flows, kpis, uniqueConversations]);

  const totalChannels = (viewModel.channels || []).reduce((acc, c) => acc + c.value, 0);
  const liveItems = uniqueConversations.slice(0, 4);
  const analyticsSeries = {
    labels: timeseries?.labels ?? [],
    conversations: timeseries?.conversations ?? [],
    leads: timeseries?.leads ?? [],
    messagesReceived: timeseries?.messages_received ?? [],
    messagesSent: timeseries?.messages_sent ?? [],
    conversions: timeseries?.conversions ?? [],
  };

  const safeSeries = {
    labels: timeseries?.labels ?? [],
    messages_sent: timeseries?.messages_sent ?? [],
    messages_received: timeseries?.messages_received ?? [],
  };

  const chartData = safeSeries.labels.map((label, i) => ({
    name: label,
    sent: safeSeries.messages_sent[i] || 0,
    received: safeSeries.messages_received[i] || 0,
  }));

  const xAxisTickInterval =
    period === '24h' ? 0 :
    period === '7d' ? 0 :
    period === '30d' ? 3 :
    9;

  const normalizedChannelItems = useMemo(() => {
    const base = [
      { name: 'WhatsApp', value: 0 },
      { name: 'Site / Chat', value: 0 },
      { name: 'Instagram', value: 0 },
      { name: 'Facebook', value: 0 },
      { name: 'Outros', value: 0 },
    ];
    (viewModel.channels || []).forEach((channel) => {
      const key = channel.name.trim().toLowerCase();
      const target = base.find((item) => item.name.toLowerCase() === key);
      if (target) target.value = channel.value;
      else base[4].value += channel.value;
    });
    const total = base.reduce((sum, item) => sum + item.value, 0);
    if (total === 0) base[0].value = 100;
    return base;
  }, [viewModel.channels]);
  const safeKpis = Array.isArray(kpiMeta) ? kpiMeta : [];

  if (!mounted || !data) {
    return (
      <div className="p-6 text-sm text-gray-500">
        Carregando dashboard...
      </div>
    );
  }

  return (
    <section className="w-full min-w-0 px-5 py-6 lg:px-6">
      <div className="w-full min-w-0 space-y-5">
      <div className="mb-4 flex items-center justify-between gap-4 md:mb-6">
        <div>
          <h1 className="text-xl md:text-2xl font-semibold leading-tight text-gray-900">
            {greeting}, Gabriel <span className="text-lg">👋</span>
          </h1>
          <p className="mt-1 text-sm text-gray-500">Aqui está o resumo das suas conversas hoje.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-slate-500">Período</span>
          <select
            value={period}
            onChange={(e) => setPeriod(e.target.value as Period)}
            className="h-11 rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-slate-700 outline-none transition focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100"
            aria-label="Selecionar período"
          >
            <option value="24h">Últimas 24h</option>
            <option value="7d">Últimos 7 dias</option>
            <option value="30d">Últimos 30 dias</option>
            <option value="90d">Últimos 90 dias</option>
          </select>
          <button className="h-11 w-11 rounded-xl border border-slate-200 bg-white text-slate-500">📅</button>
          <button
            type="button"
            onClick={handleCreateFlow}
            disabled={creatingFlow}
            className="inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-emerald-600 px-5 text-sm font-semibold leading-none text-white shadow-[0_12px_24px_rgba(16,185,129,0.22)] transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:opacity-70"
          >
            <span className="text-base leading-none">+</span>
            <span className="leading-none">{creatingFlow ? 'Criando...' : 'Novo fluxo'}</span>
          </button>
        </div>
      </div>

      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
  {safeKpis.map((item) => {
    if (!item) return null;
    const rawValue = viewModel?.[item.key as keyof typeof viewModel];
    const value = typeof rawValue === 'number' || typeof rawValue === 'string' ? rawValue : 0;
    const series = getKpiSeries(item.key, timeseries);
    const sparklineSeries = series.length ? series : [0, 0, 0, 0, 0, 0, 0];
    const delta = getDeltaPercent(sparklineSeries);
    const trendText = period === '7d' ? 'vs últimos 7 dias' : 'vs período anterior';
    const trendPrefix = delta >= 0 ? '↑' : '↓';

    return (
      <div
        key={item.key}
        className="relative overflow-hidden rounded-2xl border border-slate-100 bg-white p-5 min-h-[110px] shadow-[0_10px_30px_rgba(15,23,42,0.06)] transition hover:shadow-[0_18px_40px_rgba(15,23,42,0.10)]"
      >
        <div className="absolute inset-0 opacity-[0.03] bg-[radial-gradient(circle_at_top_left,#22c55e,transparent)] pointer-events-none" />

        <div className="relative z-10 flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50">
            {item.key === 'messagesToday' ? (
              <MessageSquare className="h-5 w-5 text-emerald-600" />
            ) : item.icon ? (
              <img src={item.icon} alt={item.label} className="h-5 w-5" />
            ) : (
              <div className="h-5 w-5 rounded bg-slate-300" />
            )}
          </div>

          <div className="min-w-0 flex-1">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{item.label}</span>

            <span className="mt-1 block text-2xl font-bold text-slate-900">
              {value}
              {item.suffix ?? ''}
            </span>
          </div>
        </div>

        <div className="relative z-10 mt-3 flex w-full items-center justify-between gap-3">
          <span className="inline-flex items-center gap-1 text-xs leading-none text-emerald-600">
            {trendPrefix} {Math.abs(delta)}%
            <span className="font-normal text-slate-500">
              {trendText}
            </span>
          </span>

          <div className="flex h-7 w-20 shrink-0 items-center justify-end">
            <Sparkline values={sparklineSeries} className="h-7 w-20" />
          </div>
        </div>
      </div>
    );
  })}
</div>
      <div className="grid w-full grid-cols-1 gap-4 items-stretch xl:grid-cols-[minmax(0,2fr)_minmax(320px,0.9fr)]">
        <div className={`${cardClassName} min-h-[390px] p-5`}>{dashboardError ? <p className="m-0 p-3 text-sm text-red-700">{dashboardError}</p> : (
          chartData.length ? <DashboardChart title={`Mensagens — ${periodLabelMap[period]}`} data={chartData.map((item) => ({ date: item.name, received: item.received, sent: item.sent }))} xAxisTickInterval={xAxisTickInterval} /> : null
        )}</div>

        <div className="min-h-[390px] rounded-2xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.04)]">
          <div className="flex items-center justify-between">
            <h3 className="m-0 text-sm font-semibold text-slate-900">Atividade ao vivo</h3>
            <span className="text-xs text-slate-500 flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />Atualizando agora</span>
          </div>
          {conversationsError ? <p className="mt-4 text-sm text-red-700">{conversationsError}</p> : liveItems.length === 0 ? <div className="mt-4 h-[290px] grid place-items-center rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 text-center"><div><p className="m-0 font-semibold text-slate-700">Sem atividade no momento</p><p className="m-0 mt-1 text-sm text-slate-500">Novas conversas aparecerão aqui em tempo real.</p></div></div> : <div className="mt-4 divide-y divide-slate-100">{(liveItems || []).map((c, idx) => {
            const name = c.name || c.phone || 'Contato';
            const contactName = (c as Conversation & { contact_name?: string | null }).contact_name;
            const initials = getInitials(c.name || contactName || c.phone);
            return <div key={c.id || idx} className="flex items-start gap-3 py-3"><div className="h-9 w-9 rounded-full bg-emerald-50 text-emerald-700 text-xs font-semibold flex items-center justify-center shrink-0">{initials}</div><div className="min-w-0 flex-1"><p className="m-0 text-sm font-semibold text-slate-800 leading-tight">{name}</p><p className="m-0 text-xs text-slate-500 mt-0.5">Flow: {getConversationFlowLabel(c)}</p><p className="m-0 text-xs text-slate-500 mt-1 line-clamp-1">{c.last_message || 'Sem mensagem recente.'}</p></div><div className="flex shrink-0 items-center gap-2"><span className="text-xs text-slate-400">agora</span><span className="h-2 w-2 rounded-full bg-emerald-500" /></div></div>;
          })}</div>}
          <div className="mt-4 border-t border-slate-100 pt-4 text-center">
            <Link href="/chat" className="text-sm font-medium text-emerald-600 hover:text-emerald-700">
              Ver todas as conversas →
            </Link>
          </div>
        </div>
      </div>

      <div className="grid w-full grid-cols-1 gap-4 xl:grid-cols-3">
        <div className={`${cardClassName} min-h-[280px] p-5`}><div className="mb-4 flex items-center justify-between"><p className="m-0 text-lg font-semibold text-slate-900">Top fluxos</p><button className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs text-slate-600">Por conversas</button></div>
        {flowsError ? <p className="text-sm text-red-700">{flowsError}</p> : <div className="space-y-3">{(viewModel.topFlows.slice(0,5)).map((flow) => {
          const pct = Math.max(0, Math.min(100, Math.round(flow.value || 0)));
          return <div key={flow.name} className="grid grid-cols-[20px_1fr_auto_auto] items-center gap-3"><span className="h-5 w-5 rounded bg-emerald-100" /><span className="text-sm font-medium text-slate-700">{flow.name}</span><span className="text-sm font-semibold text-slate-800">{flow.value}</span><span className="text-sm text-slate-500">{pct}%</span><div className="col-span-4 h-2 rounded-full bg-slate-100"><div className="h-2 rounded-full bg-emerald-500" style={{ width: `${pct}%` }} /></div></div>; })}</div>}
        <div className="mt-4 pt-3 border-t border-slate-100 text-center text-emerald-600 font-semibold">Ver todos os fluxos →</div></div>

        <div className={`${cardClassName} min-h-[280px] p-5`}><p className="m-0 mb-4 text-lg font-semibold text-slate-900">Canais de entrada</p><div className="flex items-center justify-between gap-4"><div className="relative flex min-h-[190px] items-center justify-center overflow-visible"><PieChart width={190} height={190}><Pie data={normalizedChannelItems} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={52} outerRadius={74} paddingAngle={2} stroke="none">{normalizedChannelItems.map((item) => <Cell key={item.name} fill={channelLegendColors[item.name.toLowerCase()] ?? '#94A3B8'} />)}</Pie></PieChart><div className="pointer-events-none absolute grid h-24 w-24 place-items-center rounded-full bg-white text-center"><p className="m-0 text-xs text-slate-500">Total</p><p className="m-0 text-2xl font-bold">{totalChannels}</p></div></div><div className="space-y-2 text-sm flex-1">{normalizedChannelItems.map((ch) => <div key={ch.name} className="flex items-center justify-between gap-3"><span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: channelLegendColors[ch.name.toLowerCase()] ?? '#94A3B8' }} />{ch.name}</span><span className="font-semibold text-slate-700">{ch.value}%</span></div>)}</div></div>
        <div className="mt-4 pt-3 border-t border-slate-100 text-center text-emerald-600 font-semibold">Ver todos os canais →</div></div>

        <div className={`${cardClassName} min-h-[280px] p-5`}><p className="m-0 mb-4 text-lg font-semibold text-slate-900">Desempenho geral</p><div className="space-y-4 text-sm text-slate-700">{['Tempo médio de resposta','Conversas resolvidas','Satisfação (CSAT)','Abandono de conversas'].map((n) => <div key={n} className="grid grid-cols-[1fr_auto_auto_64px] items-center gap-3"><span>{n}</span><span className="font-semibold">—</span><span className="text-emerald-600">↑ 0%</span><span className="h-7 w-16"><Sparkline/></span></div>)}</div>
        <div className="mt-4 pt-3 border-t border-slate-100 text-center text-emerald-600 font-semibold">Ver relatório completo →</div></div>
      </div>

      <div className="flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-gradient-to-r from-white via-emerald-50/60 to-white p-5 min-h-[110px] shadow-[0_12px_30px_rgba(15,23,42,0.05)]"><div className="flex items-center gap-4"><div className="h-16 w-16 rounded-2xl bg-emerald-100/70 grid place-items-center"><img src="/icons/dashboard/fluxos.svg" alt="Fluxos" className="h-10 w-10"/></div><div><p className="m-0 text-sm font-semibold text-emerald-600">Dica para você 🚀</p><p className="m-0 text-xl font-bold text-slate-900">Construa fluxos mais inteligentes com o builder visual</p><p className="m-0 text-lg text-slate-600">Use o builder para criar jornadas dinâmicas e personalizadas.</p></div></div><button className="rounded-xl bg-emerald-600 px-5 py-3 font-semibold text-white shadow-[0_8px_20px_rgba(5,150,105,0.25)]">Abrir builder ↗</button></div>
      </div>
    </section>
  );
}
