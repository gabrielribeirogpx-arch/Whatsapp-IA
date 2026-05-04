'use client';

import { useEffect, useMemo, useState } from 'react';

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
  'bg-white rounded-2xl border border-slate-100 shadow-[0_18px_45px_rgba(15,23,42,0.06)] p-5 min-h-[118px]';

function SkeletonLine({ width = '100%', height = 12 }: { width?: string; height?: number }) {
  return <div className="rounded-full bg-gradient-to-r from-emerald-50 via-slate-200 to-emerald-50" style={{ width, height }} />;
}

const Sparkline = () => (
  <svg viewBox="0 0 84 28" className="h-7 w-[84px]" fill="none" aria-hidden>
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

export default function DashboardPage() {
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

  return (<div className="bg-[#F8FAFC] p-5 md:p-6 rounded-2xl">
    <div className="mb-6"><h1 className="m-0 text-2xl font-bold text-slate-900">Dashboard</h1><p className="m-0 mt-1 text-sm text-slate-500">Visão consolidada dos seus fluxos e atendimentos.</p></div>

    <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">{kpiMeta.map((item) => {
      const value = viewModel[item.key];
      return <div key={item.key} className={cardClassName}>{isLoading ? <div className="grid gap-3"><SkeletonLine width="30%" /><SkeletonLine width="55%" /><SkeletonLine width="40%" height={24} /></div> :
        <div className="flex items-start justify-between gap-2"><div><div className="mb-3 flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-50"><img src={item.icon} alt={item.label} className="h-5 w-5 opacity-90"/></div><p className="m-0 text-xs font-semibold uppercase tracking-wide text-slate-500">{item.label}</p><p className="m-0 mt-1 text-3xl font-bold text-slate-900">{value}{item.suffix}</p></div><div className="self-end"><Sparkline/></div></div>}</div>;
    })}</div>

    <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
      <div className="bg-white rounded-2xl border border-slate-100 shadow-[0_18px_45px_rgba(15,23,42,0.06)] p-2 md:p-3">{dashboardError ? <p className="m-0 p-3 text-sm text-red-700">{dashboardError}</p> : <DashboardChart data={data?.charts?.messages_last_7_days ?? []} />}</div>
      <div className="bg-white rounded-2xl border border-slate-100 shadow-[0_18px_45px_rgba(15,23,42,0.06)] p-5">
        <div className="mb-4 flex items-center justify-between"><h3 className="m-0 text-xl font-semibold text-slate-900">Atividade ao vivo</h3><span className="text-sm text-slate-500"><span className="mr-1 text-emerald-500">●</span>Atualizando agora</span></div>
        {conversationsError ? <p className="text-sm text-red-700">{conversationsError}</p> : liveItems.length === 0 ? <p className="text-sm text-slate-500">Nenhuma atividade recente</p> : <div className="space-y-4">{liveItems.map((c, idx) => {
          const name = c.name || c.phone || 'Contato';
          const initials = name.split(' ').map((w) => w[0]).slice(0,2).join('').toUpperCase();
          return <div key={c.id || idx} className="flex items-start justify-between border-b border-slate-100 pb-3 last:border-b-0"><div className="flex gap-3"><div className="flex h-11 w-11 items-center justify-center rounded-full bg-emerald-50 text-sm font-semibold text-emerald-700">{initials}</div><div><p className="m-0 font-semibold text-slate-800">{name}</p><p className="m-0 text-sm text-slate-500">Flow: {c.flow_name || 'Sem fluxo'}</p><p className="m-0 text-sm text-slate-600 line-clamp-1">{c.last_message || 'Sem mensagem recente.'}</p></div></div><div className="text-right text-xs text-slate-500">agora<div className="ml-auto mt-2 h-2 w-2 rounded-full bg-emerald-500" /></div></div>;
        })}</div>}
      </div>
    </div>

    <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
      <div className={cardClassName}><div className="mb-4 flex items-center justify-between"><p className="m-0 font-bold text-slate-900">Top fluxos</p><button className="rounded-lg border border-slate-200 px-2 py-1 text-xs text-slate-600">Por conversas</button></div>
      {flowsError ? <p className="text-sm text-red-700">{flowsError}</p> : <div className="space-y-3">{(viewModel.topFlows.slice(0,5)).map((flow, i) => { const pct = Math.round(flow.value || 0); return <div key={flow.name} className="grid grid-cols-[16px_1fr_auto] items-center gap-2"><span className="h-4 w-4 rounded bg-emerald-100" /><span className="text-sm text-slate-700">{flow.name}</span><span className="text-sm font-semibold text-slate-700">{flow.value}</span><div className="col-span-3 h-2 rounded-full bg-slate-100"><div className="h-2 rounded-full bg-emerald-500" style={{ width: `${Math.min(100, pct)}%` }} /></div></div>; })}</div>}</div>

      <div className={cardClassName}><p className="m-0 mb-4 font-bold text-slate-900">Canais de entrada</p><div className="flex items-center gap-4"><div className="relative grid h-36 w-36 place-items-center rounded-full" style={{ background: 'conic-gradient(#16A34A 0deg 360deg)' }}><div className="grid h-24 w-24 place-items-center rounded-full bg-white text-center"><p className="m-0 text-xs text-slate-500">Total</p><p className="m-0 text-2xl font-bold">{totalChannels}</p></div></div><div className="space-y-2 text-sm">{viewModel.channels.map((ch) => <div key={ch.name} className="flex items-center justify-between gap-3"><span className="inline-flex items-center gap-2"><img src="/icons/dashboard/whatsapp.svg" className="h-4 w-4" alt="canal" />{ch.name}</span><span className="font-semibold">{ch.value}%</span></div>)}</div></div></div>

      <div className={cardClassName}><p className="m-0 mb-4 font-bold text-slate-900">Desempenho geral</p><div className="space-y-4 text-sm text-slate-700">{['Tempo médio de resposta','Conversas resolvidas','Satisfação (CSAT)','Abandono de conversas'].map((n) => <div key={n} className="flex items-center justify-between"><span>{n}</span><span className="font-semibold">—</span><span className="text-slate-400">—</span><Sparkline/></div>)}</div></div>
    </div>

    <div className="mt-6 flex items-center justify-between gap-4 rounded-2xl border border-slate-100 bg-gradient-to-r from-white to-emerald-50 p-5 shadow-[0_18px_45px_rgba(15,23,42,0.06)]"><div className="flex items-center gap-4"><img src="/icons/dashboard/fluxos.svg" alt="Fluxos" className="h-16 w-16"/><div><p className="m-0 text-sm font-semibold text-emerald-600">Dica para você 🚀</p><p className="m-0 text-xl font-semibold text-slate-900">Construa fluxos mais inteligentes com o builder visual</p><p className="m-0 text-sm text-slate-600">Use o builder para criar jornadas dinâmicas e personalizadas.</p></div></div><button className="rounded-xl bg-emerald-600 px-5 py-3 font-semibold text-white">Abrir builder</button></div>
  </div>);
}
