'use client';

import { useEffect, useId, useMemo, useState } from 'react';
import { Cell, Pie, PieChart } from 'recharts';
import { useRouter } from 'next/navigation';
import { AlertTriangle, CalendarDays, CheckCircle2, Clock3, Gauge, MessageSquare, RadioTower, Send, Star, TrendingUp, UsersRound, Zap } from "lucide-react";
import type { LucideIcon } from 'lucide-react';

import DashboardChart from '../../components/DashboardChart';
import AnimatedNumber from '../../components/motion/AnimatedNumber';
import DashboardInsightPanel from '@/components/dashboard/DashboardInsightPanel';
import DateRangePicker, { DateRange } from '@/components/dashboard/DateRangePicker';
import CreateFlowModal from '@/components/flows/CreateFlowModal';
import { getConversations, listFlows } from '../../lib/api';
import { Conversation, FlowItem } from '../../lib/types';
import { useDashboardAnalytics } from '../../hooks/useDashboardAnalytics';
import { DashboardSkeleton } from '@/components/ui/loading';

type DashboardViewModel = {
  activeConversations: number;
  activeLeads: number;
  messagesToday: number;
  responseRate: number;
  conversions: number;
  topFlows: Array<{ name: string; value: number }>;
  channels: Array<{ name: string; value: number }>;
  performance: { avgResponseTimeSeconds: number | null; resolvedConversations: number; csat: number | null; abandonmentRate: number; };
};

type Period = '24h' | '7d' | '30d' | '90d';
type DetailPanelKey = 'flows' | 'channels' | 'report' | 'conversations' | null;

const FALLBACK_VIEW_MODEL: DashboardViewModel = {
  activeConversations: 0,
  activeLeads: 0,
  messagesToday: 0,
  responseRate: 0,
  conversions: 0,
  topFlows: [],
  channels: [],
  performance: { avgResponseTimeSeconds: null, resolvedConversations: 0, csat: null, abandonmentRate: 0 },
};


function formatRelativeTime(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const diffInMinutes = Math.max(1, Math.floor((Date.now() - date.getTime()) / 60000));
  if (diffInMinutes < 60) return `há ${diffInMinutes} min`;
  const diffInHours = Math.floor(diffInMinutes / 60);
  if (diffInHours < 24) return `há ${diffInHours}h`;
  return date.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

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


const MEDIA_PREVIEW_LABELS: Array<{ pattern: RegExp; label: string }> = [
  { pattern: /(video|vídeo|mp4|mov|webm)/i, label: '📹 Vídeo enviado' },
  { pattern: /(image|imagem|foto|jpeg|jpg|png|gif|webp)/i, label: '🖼️ Imagem enviada' },
  { pattern: /(document|documento|pdf|docx?|xlsx?|arquivo|file)/i, label: '📄 Documento enviado' },
  { pattern: /(audio|áudio|voice|voz|ogg|mp3|wav|m4a)/i, label: '🎧 Áudio enviado' },
  { pattern: /(media|mídia|attachment|anexo)/i, label: '📎 Mídia enviada' },
];

function truncateText(value: string, maxLength = 55) {
  if (value.length <= maxLength) return value;
  return `${value.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function formatLastMessagePreview(message?: string | null) {
  const rawMessage = (message || '').trim();
  if (!rawMessage) return 'Sem mensagem recente.';

  const mediaLabel = MEDIA_PREVIEW_LABELS.find(({ pattern }) => pattern.test(rawMessage));
  if (mediaLabel) return mediaLabel.label;

  const withoutLongUrls = rawMessage
    .replace(/https?:\/\/\S+/gi, '[link]')
    .replace(/www\.\S+/gi, '[link]')
    .replace(/\s+/g, ' ')
    .trim();

  return truncateText(withoutLongUrls || 'Mensagem recebida.');
}

function getConversationStatusLabel(conversation: Conversation) {
  const rawStatus = (conversation.status || '').toLowerCase();

  if (rawStatus.includes('resolved') || rawStatus.includes('resolvido')) return 'Resolvido';
  if (rawStatus.includes('waiting') || rawStatus.includes('pending') || rawStatus.includes('aguard')) return 'Aguardando';

  if (conversation.mode === 'human') return 'Humano';
  if (conversation.mode === 'bot') return 'Bot';
  if (conversation.mode === 'ai') return 'IA';

  return 'Aguardando';
}

function getConversationHref(conversation: Conversation) {
  if (conversation.contact_id) return `/chat?contact_id=${encodeURIComponent(conversation.contact_id)}`;
  if (conversation.phone) return `/chat?phone=${encodeURIComponent(conversation.phone)}`;
  return '/chat';
}

function getGreeting() {
  const hour = new Date().getHours();

  if (hour >= 5 && hour < 12) return 'Bom dia';
  if (hour >= 12 && hour < 18) return 'Boa tarde';
  return 'Boa noite';
}

const cardClassName =
  'rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]';

function SkeletonLine({ width = '100%', height = 12 }: { width?: string; height?: number }) {
  return <div className="rounded-full bg-gradient-to-r from-emerald-50 via-slate-200 to-emerald-50" style={{ width, height }} />;
}

const Sparkline = ({ values = [], className = 'h-full w-full overflow-hidden' }: { values?: number[]; className?: string }) => {
  const gradientId = useId();
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
      </defs>
      <path d={`${linePath} L 63,24 L 1,24 Z`} fill={`url(#${gradientId})`} opacity="0.55" />
      <path d={linePath} stroke="#16a34a" fill="none" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
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

const kpiMeta: Array<{
  key: keyof Pick<DashboardViewModel, 'activeConversations' | 'activeLeads' | 'messagesToday' | 'responseRate' | 'conversions'>;
  label: string;
  icon: LucideIcon;
  suffix: string;
}> = [
  { key: 'activeConversations', label: 'Conversas ativas', icon: MessageSquare, suffix: '' },
  { key: 'activeLeads', label: 'Leads ativos', icon: UsersRound, suffix: '' },
  { key: 'messagesToday', label: 'Mensagens', icon: Send, suffix: '' },
  { key: 'responseRate', label: 'Taxa de resposta', icon: Gauge, suffix: '%' },
  { key: 'conversions', label: 'Conversões', icon: CheckCircle2, suffix: '' },
];

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
  const [customRange, setCustomRange] = useState<DateRange | null>(null);
  const [isCalendarOpen, setIsCalendarOpen] = useState(false);
  const [greeting, setGreeting] = useState('Olá');
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const router = useRouter();
  const { data, summary, kpis, timeseries, isLoading, error: dashboardError, refetch: refetchDashboardAnalytics } = useDashboardAnalytics(customRange ?? { preset: period });
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [flowsError, setFlowsError] = useState<string | null>(null);
  const [isCreateFlowOpen, setIsCreateFlowOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [showWelcomeToast, setShowWelcomeToast] = useState(false);
  const [activePanel, setActivePanel] = useState<DetailPanelKey>(null);
  const [isActivityLive, setIsActivityLive] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const welcome = params.get('welcome');
    if (welcome !== '1') return;

    setShowWelcomeToast(true);
    router.replace('/dashboard');

    const timeoutId = window.setTimeout(() => setShowWelcomeToast(false), 3200);
    return () => window.clearTimeout(timeoutId);
  }, [router]);

  useEffect(() => {
    void (async () => {
      try { const payload = await getConversations(5); setConversations(Array.isArray(payload) ? payload : []); setConversationsError(null);} catch { setConversations([]); setConversationsError('Não foi possível carregar as conversas recentes.'); }
      try { const payload = await listFlows(); setFlows(Array.isArray(payload) ? payload : []); setFlowsError(null);} catch { setFlows([]); setFlowsError('Não foi possível carregar os fluxos neste instante.'); }
    })();
  }, []);


  useEffect(() => {
    if (typeof window === 'undefined') return;

    const tenantId = localStorage.getItem('tenant_id');
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!tenantId || !apiUrl) return;

    const baseUrl = apiUrl.endsWith('/') ? apiUrl.slice(0, -1) : apiUrl;
    const eventSource = new EventSource(`${baseUrl}/api/dashboard/stream?tenant_id=${encodeURIComponent(tenantId)}`);

    eventSource.onopen = () => setIsActivityLive(true);
    eventSource.onmessage = (event) => {
      let payload: {
        event?: string;
        refresh?: string[];
        activity?: unknown;
      } | null = null;

      try {
        payload = JSON.parse(event.data);
      } catch {
        payload = null;
      }

      const refreshTargets = payload?.refresh ?? [];
      if (refreshTargets.includes('analytics')) {
        void refetchDashboardAnalytics();
      }
      if (refreshTargets.includes('conversations')) {
        getConversations(5).then((items) => setConversations(Array.isArray(items) ? items : [])).catch(() => undefined);
      }
    };

    eventSource.onerror = () => {
      setIsActivityLive(false);
    };

    return () => {
      eventSource.close();
      setIsActivityLive(false);
    };
  }, [refetchDashboardAnalytics]);

  useEffect(() => {
    setGreeting(getGreeting());
  }, []);

  useEffect(() => {
    setMounted(true);
  }, []);

  function handleFlowCreated(flowId: string, flowName?: string | null) {
    console.info('[FLOW CREATED CALLBACK]', { flow_id: flowId, flow_name: flowName });
    console.info('[FLOW CREATE REDIRECT]', { url: `/dashboard/flow-builder?flow_id=${flowId}` });
    router.push(`/dashboard/flow-builder?flow_id=${flowId}`);
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
    const activeFlows = flows.filter((flow) => flow.is_active);
    const flowFallback = activeFlows.length ? activeFlows.slice(0, 5).map((flow) => ({ name: flow.name, value: 0 })) : FALLBACK_VIEW_MODEL.topFlows;
    return {
      activeConversations: Number(kpis?.conversations ?? uniqueConversations.length),
      activeLeads: Number(kpis?.leads ?? uniqueConversations.filter((conversation) => conversation.mode === 'human').length),
      messagesToday: Number((kpis as any)?.messages_today ?? (Number(kpis?.messages_received ?? 0) + Number(kpis?.messages_sent ?? 0))),
      responseRate: Number(kpis?.response_rate ?? 0),
      conversions: Number(kpis?.conversions ?? 0),
      topFlows: (summary?.top_flows ?? flowFallback).map((f) => ({ name: f.name, value: Number((f as any).conversations ?? (f as any).value ?? 0) })),
      channels: (summary?.channels ?? []).map((c) => ({ name: c.channel, value: Number(c.percentage) ?? 0 })),
      performance: {
        avgResponseTimeSeconds: summary?.performance?.avg_response_time_seconds ?? null,
        resolvedConversations: Number(summary?.performance?.resolved_conversations ?? 0),
        csat: summary?.performance?.csat ?? null,
        abandonmentRate: Number(summary?.performance?.abandonment_rate ?? 0),
      },
    };
  }, [flows, kpis, uniqueConversations, summary]);

  const totalChannels = (viewModel.channels || []).reduce((acc, c) => acc + c.value, 0);
  const recentConversations = uniqueConversations.slice(0, 5);
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
    sent: safeSeries.messages_sent[i] ?? 0,
    received: safeSeries.messages_received[i] ?? 0,
  }));

  const xAxisTickInterval =
    customRange ? Math.max(0, Math.ceil(chartData.length / 8) - 1) :
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
    return total === 0 ? [] : base;
  }, [viewModel.channels]);
  const safeKpis = Array.isArray(kpiMeta) ? kpiMeta : [];
  const isPanelLoading = (!flows.length && !conversations.length) && (isLoading || !mounted);
  const performanceKpis = [
    { label: 'Resp. méd.', value: viewModel.performance.avgResponseTimeSeconds !== null ? `${viewModel.performance.avgResponseTimeSeconds}s` : 'Sem dados', icon: Clock3, className: 'border-indigo-100/70 bg-indigo-50/50 text-indigo-500 ring-indigo-100/60' },
    { label: 'Resolvidas', value: viewModel.performance.resolvedConversations, icon: CheckCircle2, className: 'border-emerald-100/70 bg-emerald-50/50 text-emerald-500 ring-emerald-100/60' },
    { label: 'CSAT', value: viewModel.performance.csat ?? '—', icon: Star, className: 'border-amber-100/70 bg-amber-50/50 text-amber-500 ring-amber-100/60' },
    { label: 'Abandono', value: `${viewModel.performance.abandonmentRate}%`, icon: AlertTriangle, className: 'border-orange-100/70 bg-orange-50/50 text-orange-500 ring-orange-100/60' },
  ];

  const panelConfig = {
    flows: {
      title: 'Todos os fluxos',
      description: 'Visão completa de status, publicação e ações rápidas.',
    },
    channels: {
      title: 'Todos os canais',
      description: 'Monitoramento dos canais conectados e saúde da operação.',
    },
    report: {
      title: 'Relatório completo',
      description: 'Métricas detalhadas com insights e tendências do período.',
    },
    conversations: {
      title: 'Todas as conversas',
      description: 'Acompanhe últimas interações, filtros e distribuição de atendimento.',
    },
  } as const;

  if (!mounted || !data) {
    return (
      <div className="p-6 text-sm text-gray-500">
        <DashboardSkeleton />
      </div>
    );
  }

  return (
    <section className="motion-page w-full min-w-0 px-4 py-5 sm:px-5 lg:px-6 lg:py-6">
      {showWelcomeToast ? (
        <div className="fixed right-6 top-6 z-[120] rounded-xl border border-emerald-200 bg-white/95 px-4 py-3 text-sm font-medium text-emerald-700 shadow-[0_12px_30px_rgba(16,185,129,0.18)] backdrop-blur">
          ✅ Conta criada com sucesso. Seu workspace está pronto!
        </div>
      ) : null}
      <div className="mx-auto w-full min-w-0 max-w-[1600px] space-y-5">
      <div className="flex flex-col gap-4 border-b border-slate-200/70 pb-5 sm:flex-row sm:items-end sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold leading-tight tracking-[-0.02em] text-slate-950 md:text-2xl">
            {greeting}, Gabriel <span className="text-lg">👋</span>
          </h1>
          <p className="mt-1 text-[13px] leading-5 text-slate-500">Aqui está o resumo das suas conversas hoje.</p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:flex-nowrap">
          <span className="sr-only">Período</span>
          <select
            value={customRange ? 'custom' : period}
            onChange={(e) => { setCustomRange(null); setPeriod(e.target.value as Period); }}
            className="h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-[13px] font-medium text-slate-700 outline-none transition hover:border-slate-300 focus-visible:border-emerald-500 focus-visible:ring-2 focus-visible:ring-emerald-100 sm:flex-none"
            aria-label="Selecionar período"
          >
            <option value="24h">Últimas 24h</option>
            <option value="7d">Últimos 7 dias</option>
            <option value="30d">Últimos 30 dias</option>
            <option value="90d">Últimos 90 dias</option>
            {customRange ? <option value="custom">{new Date(`${customRange.startDate}T12:00:00`).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })} – {new Date(`${customRange.endDate}T12:00:00`).toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' })}</option> : null}
          </select>
          <div className="relative">
            <button type="button" aria-label="Selecionar período personalizado" aria-haspopup="dialog" aria-expanded={isCalendarOpen} onClick={() => setIsCalendarOpen((open) => !open)} className="inline-flex h-10 w-10 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-500 transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200"><CalendarDays size={17} strokeWidth={1.8} /></button>
            {isCalendarOpen ? <DateRangePicker initialRange={customRange} onCancel={() => setIsCalendarOpen(false)} onApply={(range) => { setCustomRange(range); setIsCalendarOpen(false); }} /> : null}
          </div>
          <button
            type="button"
            onClick={() => setIsCreateFlowOpen(true)}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 text-[13px] font-semibold leading-none text-white shadow-[0_1px_2px_rgba(5,150,105,0.18)] transition hover:bg-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-300 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-70"
          >
            <span className="text-base leading-none">+</span>
            <span className="leading-none">Novo fluxo</span>
          </button>
        </div>
      </div>

      <div className="grid w-full grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
  {safeKpis.map((item) => {
    if (!item) return null;
    const rawValue = viewModel?.[item.key as keyof typeof viewModel];
    const value = typeof rawValue === 'number' || typeof rawValue === 'string' ? rawValue : 0;
    const numericValue = Number(value) ?? 0;
    const series = getKpiSeries(item.key, timeseries);
    const sparklineSeries = series.length ? series : [0, 0, 0, 0, 0, 0, 0];
    const delta = item.key === 'messagesToday' ? (kpis as any)?.messages_delta as number | null | undefined : undefined;
    const hasRealDelta = delta !== undefined;
    const trendText = hasRealDelta ? 'vs. período anterior' : '';
    const trendPrefix = typeof delta === 'number' && delta >= 0 ? '↑' : '↓';
    const Icon = item.icon;

    return (
      <div
        key={item.key}
        className="motion-card motion-enter relative flex min-h-[142px] flex-col overflow-hidden rounded-xl border border-slate-200/80 bg-white p-4 shadow-[0_1px_2px_rgba(15,23,42,0.03)]"
        style={{ animationDelay: `${safeKpis.indexOf(item) * 35}ms` }}
      >
        <div className="relative z-10 flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <span className="text-xs font-medium text-slate-500">{item.label}</span>
            <span className="mt-2 block text-[28px] font-semibold leading-none tracking-[-0.035em] text-slate-950">
              <AnimatedNumber value={numericValue} />
              {item.suffix ?? ''}
            </span>
          </div>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-500">
            <Icon aria-hidden="true" className="h-4 w-4" strokeWidth={1.8} />
          </div>
        </div>

        <div className="relative z-10 mt-auto flex w-full items-end justify-between gap-2 pt-4">
          <span className="inline-flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5 text-[11px] leading-4">
            {hasRealDelta ? <span className={typeof delta === 'number' && delta >= 0 ? 'font-semibold text-emerald-600' : typeof delta === 'number' ? 'font-semibold text-rose-600' : 'font-semibold text-slate-400'}>{typeof delta === 'number' ? `${trendPrefix} ${Math.abs(delta)}%` : '—'}</span> : null}
            <span className="font-normal text-slate-400">
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
      <div className="grid w-full grid-cols-1 items-stretch gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,0.9fr)]">
        <div className={`${cardClassName} min-h-[390px] p-5`}>{dashboardError ? <p className="m-0 p-3 text-sm text-red-700">{dashboardError}</p> : (
          chartData.length ? <DashboardChart title={`Mensagens — ${customRange ? `${new Date(`${customRange.startDate}T12:00:00`).toLocaleDateString('pt-BR')} a ${new Date(`${customRange.endDate}T12:00:00`).toLocaleDateString('pt-BR')}` : periodLabelMap[period]}`} data={chartData.map((item) => ({ date: item.name, received: item.received, sent: item.sent }))} xAxisTickInterval={xAxisTickInterval} /> : null
        )}</div>

        <div className="min-h-[390px] rounded-xl border border-slate-200/80 bg-white p-5 shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
          <div className="flex items-center justify-between">
            <h3 className="m-0 text-sm font-semibold text-slate-900">Conversas recentes</h3>
            <span className="flex items-center gap-2 text-xs text-slate-500"><span className={`h-1.5 w-1.5 rounded-full ${isActivityLive ? 'bg-emerald-500' : 'bg-slate-300'}`} />{isActivityLive ? 'Ao vivo' : 'Atualizado agora'}</span>
          </div>
          {conversationsError ? <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-700">{conversationsError}</p> : null}
          {recentConversations.length === 0 ? <div className="mt-4 grid h-[290px] place-items-center rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-6 text-center"><div><p className="m-0 font-semibold text-slate-700">Sem conversas recentes</p><p className="m-0 mt-1 text-sm text-slate-500">Quando novas mensagens chegarem, elas aparecerão aqui.</p></div></div> : <div className="mt-3 divide-y divide-slate-100">{recentConversations.map((conversation) => {
            const displayName = conversation.name?.trim() || conversation.phone?.trim() || 'Conversa';
            const attendantName = conversation.assigned_user_name?.trim() || 'Sem atendente';
            const statusLabel = getConversationStatusLabel(conversation);
            const unreadCount = Number(conversation.unread_count || 0);
            const unreadLabel = unreadCount > 0 ? `${unreadCount} nova${unreadCount > 1 ? 's' : ''}` : null;
            const badges = [`Atendente: ${attendantName}`, statusLabel, unreadLabel].filter(Boolean);
            return <button type="button" key={conversation.id} onClick={() => router.push(getConversationHref(conversation))} className="group flex w-full items-start gap-3 rounded-lg px-2 py-3 text-left transition-colors duration-150 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-200"><div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600 ring-1 ring-inset ring-slate-200">{getInitials(displayName)}</div><div className="min-w-0 flex-1"><div className="flex items-start justify-between gap-3"><p className="m-0 truncate text-[13px] font-semibold leading-tight text-slate-900">{displayName}</p><span className="shrink-0 text-[11px] font-medium text-slate-400">{formatRelativeTime(conversation.updated_at)}</span></div><p className="m-0 mt-1 truncate text-xs leading-relaxed text-slate-500">{formatLastMessagePreview(conversation.last_message)}</p><div className="mt-1.5 flex flex-wrap gap-1">{badges.map((badge) => <span key={badge} className="inline-flex max-w-full items-center rounded-md border border-slate-200/80 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium leading-3.5 text-slate-500">{badge}</span>)}</div></div></button>;
          })}</div>}
          <div className="mt-4 border-t border-slate-100 pt-4 text-center">
            <button type="button" onClick={() => router.push('/chat')} className="text-sm font-medium text-emerald-600 hover:text-emerald-700">
              Ver inbox →
            </button>
          </div>
        </div>
      </div>

      <div className="grid w-full grid-cols-1 items-stretch gap-4 xl:grid-cols-3">
        <div className={`${cardClassName} flex min-h-[224px] flex-col p-4 sm:p-5`}>
          <div className="mb-4 flex min-h-8 items-center justify-between gap-3">
            <p className="m-0 text-sm font-semibold text-slate-900">Top fluxos</p>
            <button type="button" className="rounded-md border border-slate-200/80 bg-white px-2.5 py-1.5 text-[11px] font-medium text-slate-500 transition-colors hover:border-slate-300 hover:bg-slate-50 hover:text-slate-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200">Por conversas</button>
          </div>
          {flowsError ? <p className="text-sm text-red-700">{flowsError}</p> : viewModel.topFlows.length === 0 ? <div className="grid min-h-[116px] flex-1 place-items-center rounded-lg border border-slate-100 bg-slate-50/60 px-5 py-4 text-center"><div><span className="mx-auto inline-flex h-8 w-8 items-center justify-center rounded-lg bg-white text-slate-400 ring-1 ring-inset ring-slate-200"><Zap size={15} strokeWidth={1.8} /></span><p className="m-0 mt-2.5 text-sm font-semibold text-slate-800">Nenhum fluxo ativo ainda</p><p className="m-0 mt-1 max-w-[280px] text-xs leading-5 text-slate-500">Crie seu primeiro fluxo automatizado para começar a coletar métricas.</p></div></div> : <div className="space-y-3">{(viewModel.topFlows.slice(0,5)).map((flow) => {
            const pct = Math.max(0, Math.min(100, Math.round(flow.value || 0)));
            return <div key={flow.name} className="grid grid-cols-[20px_1fr_auto_auto] items-center gap-3"><span className="h-5 w-5 rounded bg-emerald-100" /><span className="text-sm font-medium text-slate-700">{flow.name}</span><span className="text-sm font-semibold text-slate-800">{flow.value}</span><span className="text-sm text-slate-500">{pct}%</span><div className="col-span-4 h-2 rounded-full bg-slate-100"><div className="h-2 rounded-full bg-emerald-500" style={{ width: `${pct}%` }} /></div></div>;
          })}</div>}
          <button type="button" onClick={() => setActivePanel('flows')} className="mt-3 inline-flex min-h-8 items-end justify-center border-t border-slate-100 pt-2.5 text-xs font-medium text-slate-500 transition-colors hover:text-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200">Ver todos os fluxos <span aria-hidden="true" className="ml-1">→</span></button>
        </div>

        <div className={`${cardClassName} flex min-h-[224px] flex-col p-4 sm:p-5`}>
          <div className="mb-4 flex min-h-8 items-center"><p className="m-0 text-sm font-semibold text-slate-900">Canais de entrada</p></div>
          {normalizedChannelItems.length === 0 ? <div className="grid min-h-[116px] flex-1 place-items-center rounded-lg border border-slate-100 bg-slate-50/60 px-5 py-4 text-center"><div><span className="mx-auto inline-flex h-8 w-8 items-center justify-center rounded-lg bg-white text-slate-400 ring-1 ring-inset ring-slate-200"><RadioTower size={15} strokeWidth={1.8} /></span><p className="m-0 mt-2.5 text-sm font-semibold text-slate-800">Nenhum canal conectado</p><p className="m-0 mt-1 text-xs leading-5 text-slate-500">Conecte WhatsApp, Instagram ou Webchat.</p></div></div> : <div className="flex items-center justify-between gap-4"><div className="relative flex min-h-[190px] items-center justify-center overflow-visible"><PieChart width={190} height={190}><Pie data={normalizedChannelItems} dataKey="value" nameKey="name" cx="50%" cy="50%" innerRadius={52} outerRadius={74} paddingAngle={2} stroke="none">{normalizedChannelItems.map((item) => <Cell key={item.name} fill={channelLegendColors[item.name.toLowerCase()] ?? '#94A3B8'} />)}</Pie></PieChart><div className="pointer-events-none absolute grid h-24 w-24 place-items-center rounded-full bg-white text-center"><p className="m-0 text-xs text-slate-500">Total</p><p className="m-0 text-2xl font-bold">{totalChannels}</p></div></div><div className="space-y-2 text-sm flex-1">{normalizedChannelItems.map((ch) => <div key={ch.name} className="flex items-center justify-between gap-3"><span className="inline-flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: channelLegendColors[ch.name.toLowerCase()] ?? '#94A3B8' }} />{ch.name}</span><span className="font-semibold text-slate-700">{ch.value}%</span></div>)}</div></div>}
          <button type="button" onClick={() => setActivePanel('channels')} className="mt-3 inline-flex min-h-8 items-end justify-center border-t border-slate-100 pt-2.5 text-xs font-medium text-slate-500 transition-colors hover:text-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200">Ver todos os canais <span aria-hidden="true" className="ml-1">→</span></button>
        </div>

        <div className={`${cardClassName} flex min-h-[224px] flex-col p-4 sm:p-5`}>
          <div className="mb-4 flex min-h-8 items-center"><p className="m-0 text-sm font-semibold text-slate-900">Desempenho geral</p></div>
          {viewModel.performance.avgResponseTimeSeconds === null && viewModel.performance.resolvedConversations === 0 && viewModel.performance.csat === null ? <div className="flex-1 rounded-lg bg-slate-50/60 px-3 py-3"><div className="mb-2.5 flex items-center gap-2"><span className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-white text-slate-400 ring-1 ring-inset ring-slate-200"><TrendingUp size={14} strokeWidth={1.8} /></span><p className="m-0 text-xs font-medium leading-4 text-slate-600">Dados aparecerão aqui conforme as conversas acontecerem.</p></div><div className="grid grid-cols-2">{[1,2,3,4].map((item) => <div key={item} className={`px-3 py-2.5 ${item % 2 === 1 ? 'border-r border-slate-200/80' : ''} ${item <= 2 ? 'border-b border-slate-200/80' : ''}`}><SkeletonLine width="52%" height={13} /><div className="mt-2"><SkeletonLine width="42%" height={8} /></div></div>)}</div></div> : <div className="grid flex-1 grid-cols-2 rounded-lg bg-slate-50/40">{performanceKpis.map((item, index) => { const Icon = item.icon; return <div key={item.label} className={`flex min-h-[82px] items-center gap-3.5 px-3.5 py-3 ${index % 2 === 0 ? 'border-r border-slate-200/50' : ''} ${index < 2 ? 'border-b border-slate-200/50' : ''}`}><span className={`inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border ring-1 ring-inset ${item.className}`}><Icon size={13} strokeWidth={1.7} /></span><div className="min-w-0"><p className={`m-0 text-lg font-medium leading-none tracking-[-0.015em] ${item.label === 'CSAT' && item.value === '—' ? 'text-slate-400' : 'text-slate-900'}`}>{item.value}</p><p className="m-0 mt-1.5 text-[10px] font-normal leading-tight tracking-[0.01em] text-slate-500">{item.label}</p></div></div>; })}</div>}
          <div className="mt-auto pt-3"><button type="button" onClick={() => setActivePanel('report')} className="inline-flex min-h-8 w-full items-end justify-center border-t border-slate-100 pt-2.5 text-xs font-medium text-slate-500 transition-colors hover:text-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200">Ver relatório completo <span aria-hidden="true" className="ml-1">→</span></button></div>
        </div>
      </div>

      <div className="flex min-h-[92px] flex-col gap-4 rounded-xl border border-slate-200/80 bg-slate-50/50 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.03)] sm:flex-row sm:items-center sm:justify-between sm:p-5"><div className="flex min-w-0 items-start gap-3"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-white ring-1 ring-inset ring-slate-200"><img src="/icons/dashboard/fluxos.svg" alt="" aria-hidden="true" className="h-6 w-6"/></div><div className="min-w-0"><p className="m-0 text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-500">Dica para você</p><p className="m-0 mt-1 text-base font-semibold leading-snug text-slate-900">Construa fluxos mais inteligentes com o builder visual</p><p className="m-0 mt-1 text-sm leading-relaxed text-slate-500">Use o builder para criar jornadas dinâmicas e personalizadas.</p></div></div><button type="button" className="inline-flex h-9 shrink-0 items-center justify-center self-start rounded-lg border border-slate-200 bg-white px-3.5 text-xs font-semibold text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,0.04)] transition-colors hover:border-emerald-200 hover:bg-emerald-50/50 hover:text-emerald-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200 sm:self-center">Abrir builder <span aria-hidden="true" className="ml-1">↗</span></button></div>
      </div>
    
      <CreateFlowModal
        open={isCreateFlowOpen}
        onClose={() => setIsCreateFlowOpen(false)}
        onCreated={handleFlowCreated}
        title="Criar novo fluxo"
      />
      <DashboardInsightPanel
        open={activePanel !== null}
        loading={isPanelLoading}
        onClose={() => setActivePanel(null)}
        title={activePanel ? panelConfig[activePanel].title : ''}
        description={activePanel ? panelConfig[activePanel].description : ''}
      >
        {activePanel === 'flows' ? (
          flows.length ? (
            <div className="space-y-3">
              {flows.map((flow) => {
                const isPublished = flow.is_active;
                return <div key={flow.id} className="rounded-2xl border border-emerald-100 bg-white/90 p-4 shadow-sm"><div className="flex items-start justify-between gap-3"><div><p className="m-0 text-sm font-semibold text-slate-900">{flow.name}</p><p className="mt-1 text-xs text-slate-500">Status: {isPublished ? 'Ativo' : 'Inativo'}</p></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${isPublished ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>{isPublished ? 'Ativo' : 'Inativo'}</span></div><div className="mt-3 flex gap-2"><button className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-medium text-slate-700">Editar</button><button className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-medium text-emerald-700">Abrir analytics</button></div></div>;
              })}
            </div>
          ) : <div className="grid min-h-[260px] place-items-center rounded-2xl border border-dashed border-emerald-200 bg-white/70 p-6 text-center"><p className="text-sm font-medium text-slate-600">Sem fluxos por enquanto. Crie um novo fluxo para visualizar detalhes aqui.</p></div>
        ) : null}
        {activePanel === 'channels' ? (
          <div className="space-y-3">
            {['WhatsApp', 'Instagram', 'Webchat'].map((channel) => <div key={channel} className="flex items-center justify-between rounded-2xl border border-emerald-100 bg-white/90 p-4"><div><p className="m-0 text-sm font-semibold text-slate-900">{channel}</p><p className="mt-1 text-xs text-slate-500">Canal conectado ao dashboard</p></div><span className="rounded-full bg-emerald-100 px-2 py-1 text-[11px] font-semibold text-emerald-700">Ativo</span></div>)}
          </div>
        ) : null}
        {activePanel === 'report' ? (
          <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">{[{ label: 'Conversões', value: viewModel.conversions }, { label: 'Taxa de resposta', value: `${viewModel.responseRate}%` }, { label: 'CSAT', value: viewModel.performance.csat ?? 'Sem dados' }, { label: 'Abandono', value: `${viewModel.performance.abandonmentRate}%` }].map((item) => <div key={item.label} className="rounded-2xl border border-emerald-100 bg-white p-4"><p className="m-0 text-xs uppercase tracking-wide text-slate-500">{item.label}</p><p className="mt-2 text-xl font-bold text-slate-900">{item.value}</p></div>)}</div>
            <div className="rounded-2xl border border-emerald-100 bg-white p-4"><p className="m-0 text-sm font-semibold text-slate-900">Tendências</p><p className="mt-1 text-sm text-slate-500">As conversões seguiram estáveis no período e a taxa de resposta apresentou melhor consistência nas últimas interações.</p></div>
          </div>
        ) : null}
        {activePanel === 'conversations' ? (
          uniqueConversations.length ? (
            <div className="space-y-3">
              {uniqueConversations.slice(0, 10).map((conversation) => <div key={conversation.id} className="rounded-2xl border border-emerald-100 bg-white/90 p-4"><div className="flex items-start justify-between gap-3"><div><p className="m-0 text-sm font-semibold text-slate-900">{conversation.name || conversation.phone}</p><p className="mt-1 text-xs text-slate-500">{getConversationFlowLabel(conversation)}</p></div><span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${conversation.mode === 'human' ? 'bg-sky-100 text-sky-700' : 'bg-purple-100 text-purple-700'}`}>{conversation.mode === 'human' ? 'Humano' : 'IA'}</span></div><p className="mt-3 text-sm text-slate-600">{conversation.last_message || 'Sem mensagem recente.'}</p></div>)}
            </div>
          ) : <div className="grid min-h-[260px] place-items-center rounded-2xl border border-dashed border-emerald-200 bg-white/70 p-6 text-center"><p className="text-sm font-medium text-slate-600">Nenhuma conversa recente para exibir. Novas conversas aparecerão aqui automaticamente.</p></div>
        ) : null}
      </DashboardInsightPanel>
</section>
  );
}
