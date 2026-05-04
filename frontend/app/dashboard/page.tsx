'use client';

import { useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { Cell, Pie, PieChart } from 'recharts';

import DashboardChart from '../../components/DashboardChart';
import { apiFetch, getConversations, listFlows, parseApiResponse } from '../../lib/api';
import { Conversation, FlowItem } from '../../lib/types';

type DashboardData = {
  charts?: {
    messages_last_7_days?: {
      date: string;
      sent: number;
      received: number;
    }[];
  };
  metrics?: {
    activeConversations?: number;
    activeLeads?: number;
    messagesToday?: number;
    responseRate?: number;
    conversions?: number;
  };
  top_flows?: Array<{ name: string; value?: number }>;
  channels?: Array<{ name: string; value: number }>;
};

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

const cardClassName =
  'bg-white rounded-2xl border border-slate-100 shadow-[0_12px_30px_rgba(15,23,42,0.05)] p-5';

function SkeletonLine({ width = '100%', height = 12 }: { width?: string; height?: number }) {
  return <div className="rounded-full bg-gradient-to-r from-emerald-50 via-slate-200 to-emerald-50" style={{ width, height }} />;
}

const Sparkline = () => (
  <svg viewBox="0 0 84 28" className="h-full w-full" fill="none" aria-hidden>
    <path d="M1 25C8 17 12 15 20 18C28 21 34 24 41 20C48 16 53 17 59 14C66 11 72 8 83 2" stroke="#22C55E" strokeWidth="2.2" strokeLinecap="round" opacity="0.75"/>
  </svg>
);

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

const channelLegendColors: Record<string, string> = {
  whatsapp: '#16A34A',
  'site / chat': '#2563EB',
  instagram: '#8B5CF6',
  facebook: '#F59E0B',
  outros: '#94A3B8',
};

export default function DashboardPage() {
  const [period, setPeriod] = useState<Period>('7d');
  const [data, setData] = useState<DashboardData | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [flowsError, setFlowsError] = useState<string | null>(null);

  useEffect(() => { void (async () => {
    setIsLoading(true);
    try { const res = await apiFetch('/api/dashboard'); setData(await parseApiResponse<DashboardData>(res)); setDashboardError(null);} catch { setData(null); setDashboardError('Não foi possível carregar os indicadores do dashboard agora.'); }
    try { const payload = await getConversations(); setConversations(Array.isArray(payload) ? payload : []); setConversationsError(null);} catch { setConversations([]); setConversationsError('Não foi possível carregar a atividade recente no momento.'); }
    try { const payload = await listFlows(); setFlows(Array.isArray(payload) ? payload : []); setFlowsError(null);} catch { setFlows([]); setFlowsError('Não foi possível carregar os fluxos neste instante.'); }
    setIsLoading(false);
  })(); }, []);

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
    const fromDashboard = data?.metrics ?? {};
    const flowFallback = flows.length ? flows.slice(0, 5).map((flow) => ({ name: flow.name, value: 0 })) : FALLBACK_VIEW_MODEL.topFlows;
    const normalizedChannels = (data?.channels ?? []).filter((channel) => channel.name && typeof channel.value === 'number').map((channel) => ({ name: channel.name, value: channel.value }));
    const msgsToday = uniqueConversations.filter((c) => {
      const d = new Date(c.updated_at);
      const now = new Date();
      return !Number.isNaN(d.getTime()) && d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    }).length;
    return {
      activeConversations: fromDashboard.activeConversations ?? uniqueConversations.length ?? 0,
      activeLeads: fromDashboard.activeLeads ?? uniqueConversations.filter((conversation) => conversation.mode === 'human').length ?? 0,
      messagesToday: fromDashboard.messagesToday ?? msgsToday ?? 0,
      responseRate: fromDashboard.responseRate ?? 0,
      conversions: fromDashboard.conversions ?? 0,
      topFlows: data?.top_flows?.length ? data.top_flows.map((flow) => ({ name: flow.name, value: flow.value ?? 0 })) : flowFallback,
      channels: normalizedChannels.length ? normalizedChannels : FALLBACK_VIEW_MODEL.channels,
    };
  }, [conversations, data, flows, uniqueConversations]);

  const totalChannels = viewModel.channels.reduce((acc, c) => acc + c.value, 0);
  const liveItems = uniqueConversations.slice(0, 4);

  const normalizedChannelItems = useMemo(() => {
    const base = [
      { name: 'WhatsApp', value: 0 },
      { name: 'Site / Chat', value: 0 },
      { name: 'Instagram', value: 0 },
      { name: 'Facebook', value: 0 },
      { name: 'Outros', value: 0 },
    ];
    viewModel.channels.forEach((channel) => {
      const key = channel.name.trim().toLowerCase();
      const target = base.find((item) => item.name.toLowerCase() === key);
      if (target) target.value = channel.value;
      else base[4].value += channel.value;
    });
    const total = base.reduce((sum, item) => sum + item.value, 0);
    if (total === 0) base[0].value = 100;
    return base;
  }, [viewModel.channels]);

  return (
    <div className="bg-[#F8FAFC] max-w-[1320px] mx-auto px-6 lg:px-8 py-6 space-y-5 rounded-2xl">
      <div className="flex items-center justify-between gap-4 mb-4">
        <div>
          <h1 className="m-0 text-[26px] lg:text-[28px] leading-tight font-bold text-slate-900">Bom dia, Gabriel 👋</h1>
          <p className="m-0 mt-2 text-sm lg:text-base text-slate-500">Aqui está o resumo das suas conversas hoje.</p>
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
          <Link href="/dashboard/flows" className="h-11 px-5 rounded-xl bg-emerald-600 text-white shadow-[0_8px_20px_rgba(5,150,105,0.25)] font-semibold">+ Novo fluxo</Link>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">{kpiMeta.map((item) => {
        const value = viewModel[item.key];
        return <div key={item.key} className="bg-white rounded-2xl border border-slate-100 shadow-[0_12px_30px_rgba(15,23,42,0.05)] p-4 min-h-[112px] flex items-center justify-between">{isLoading ? <div className="grid gap-2 w-full"><SkeletonLine width="35%" /><SkeletonLine width="48%" /><SkeletonLine width="40%" height={20} /></div> :
          <>
            <div className="flex items-start gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 shrink-0">
                <img src={item.icon} alt={item.label} className="h-5 w-5 opacity-90"/>
              </div>
              <div className="flex flex-col">
                <span className="uppercase text-[11px] font-semibold text-slate-500">{item.label}</span>
                <span className="text-[24px] font-bold text-slate-900 leading-tight">{value}{item.suffix}</span>
                <span className="text-[11px] text-emerald-600">↑ 18% vs últimos 7 dias</span>
              </div>
            </div>
            <div className="w-16 h-8 self-end">
              <Sparkline/>
            </div>
          </>}</div>;
      })}</div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.75fr)_minmax(320px,0.9fr)] gap-4 items-stretch">
        <div className={`${cardClassName} min-h-[390px] p-5`}>{dashboardError ? <p className="m-0 p-3 text-sm text-red-700">{dashboardError}</p> : (
          // TODO: aplicar o filtro real por período quando a integração de dados do backend estiver disponível.
          <DashboardChart data={data?.charts?.messages_last_7_days ?? []} />
        )}</div>

        <div className={`${cardClassName} min-h-[390px] p-5`}>
          <div className="mb-4 flex items-center justify-between">
            <h3 className="m-0 text-lg font-semibold text-slate-900">Atividade ao vivo</h3>
            <span className="text-sm text-slate-500"><span className="mr-2 text-emerald-500">●</span>Atualizando agora</span>
          </div>
          {conversationsError ? <p className="text-sm text-red-700">{conversationsError}</p> : liveItems.length === 0 ? <div className="h-[290px] grid place-items-center rounded-xl border border-dashed border-emerald-200 bg-emerald-50/40 text-center"><div><p className="m-0 font-semibold text-slate-700">Sem atividade no momento</p><p className="m-0 mt-1 text-sm text-slate-500">Novas conversas aparecerão aqui em tempo real.</p></div></div> : <div className="space-y-4">{liveItems.map((c, idx) => {
            const name = c.name || c.phone || 'Contato';
            const initials = name.split(' ').map((w) => w[0]).slice(0,2).join('').toUpperCase();
            return <div key={c.id || idx} className="flex items-start justify-between border-b border-slate-100 pb-3 last:border-b-0"><div className="flex gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-full bg-emerald-50 text-sm font-semibold text-emerald-700">{initials}</div><div><p className="m-0 font-semibold text-slate-800">{name}</p><p className="m-0 text-sm text-slate-500">Flow: {getConversationFlowLabel(c)}</p><p className="m-0 text-sm text-slate-600 line-clamp-1">{c.last_message || 'Sem mensagem recente.'}</p></div></div><div className="text-right text-xs text-slate-500">agora<div className="ml-auto mt-2 h-2 w-2 rounded-full bg-emerald-500" /></div></div>;
          })}</div>}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
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
  );
}
