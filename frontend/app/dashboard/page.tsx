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
  'bg-white rounded-2xl border border-slate-100 shadow-[0_18px_45px_rgba(15,23,42,0.06)] p-5 md:p-6 min-h-[150px] transition-shadow duration-200 hover:shadow-[0_20px_50px_rgba(15,23,42,0.09)]';

function SkeletonLine({ width = '100%', height = 12 }: { width?: string; height?: number }) {
  return (
    <div
      className="rounded-full bg-gradient-to-r from-emerald-50 via-slate-200 to-emerald-50"
      style={{ width, height }}
    />
  );
}

function EmptyState({ message }: { message: string }) {
  return <p className="m-0 text-sm text-slate-500">{message}</p>;
}

function ErrorState({ message }: { message: string }) {
  return <p className="m-0 text-sm text-red-700">{message}</p>;
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [conversationsError, setConversationsError] = useState<string | null>(null);
  const [flowsError, setFlowsError] = useState<string | null>(null);

  useEffect(() => {
    async function loadDashboardData() {
      setIsLoading(true);

      try {
        const res = await apiFetch('/api/dashboard');
        const payload = await parseApiResponse<DashboardData>(res);
        setData(payload);
        setDashboardError(null);
      } catch {
        setData(null);
        setDashboardError('Não foi possível carregar os indicadores do dashboard agora.');
      }

      try {
        const payload = await getConversations();
        setConversations(Array.isArray(payload) ? payload : []);
        setConversationsError(null);
      } catch {
        setConversations([]);
        setConversationsError('Não foi possível carregar a atividade recente no momento.');
      }

      try {
        const payload = await listFlows();
        setFlows(Array.isArray(payload) ? payload : []);
        setFlowsError(null);
      } catch {
        setFlows([]);
        setFlowsError('Não foi possível carregar os fluxos neste instante.');
      }

      setIsLoading(false);
    }

    void loadDashboardData();
  }, []);

  const uniqueConversations = useMemo(() => {
    const seen = new Set<string>();

    return conversations.filter((conversation) => {
      const phone = conversation.phone ?? '';
      if (!phone || seen.has(phone)) return false;
      seen.add(phone);
      return true;
    });
  }, [conversations]);

  const derivedMessagesToday = useMemo(() => {
    const now = new Date();

    return uniqueConversations.filter((conversation) => {
      const updatedAt = new Date(conversation.updated_at);

      return (
        !Number.isNaN(updatedAt.getTime()) &&
        updatedAt.getDate() === now.getDate() &&
        updatedAt.getMonth() === now.getMonth() &&
        updatedAt.getFullYear() === now.getFullYear()
      );
    }).length;
  }, [uniqueConversations]);

  const viewModel = useMemo<DashboardViewModel>(() => {
    const fromDashboard = data?.metrics ?? {};

    const flowFallback = flows.length
      ? flows.slice(0, 3).map((flow) => ({ name: flow.name, value: 0 }))
      : FALLBACK_VIEW_MODEL.topFlows;

    const normalizedChannels = (data?.channels ?? [])
      .filter((channel) => channel.name && typeof channel.value === 'number')
      .map((channel) => ({ name: channel.name, value: channel.value }));

    return {
      activeConversations: fromDashboard.activeConversations ?? uniqueConversations.length ?? FALLBACK_VIEW_MODEL.activeConversations,
      activeLeads:
        fromDashboard.activeLeads ??
        uniqueConversations.filter((conversation) => conversation.mode === 'human').length ??
        FALLBACK_VIEW_MODEL.activeLeads,
      messagesToday: fromDashboard.messagesToday ?? derivedMessagesToday ?? FALLBACK_VIEW_MODEL.messagesToday,
      responseRate: fromDashboard.responseRate ?? FALLBACK_VIEW_MODEL.responseRate,
      conversions: fromDashboard.conversions ?? FALLBACK_VIEW_MODEL.conversions,
      topFlows:
        data?.top_flows?.length
          ? data.top_flows.map((flow) => ({ name: flow.name, value: flow.value ?? 0 }))
          : flowFallback,
      channels: normalizedChannels.length ? normalizedChannels : FALLBACK_VIEW_MODEL.channels,
    };
  }, [data, derivedMessagesToday, flows, uniqueConversations]);

  const messagesLast7Days = data?.charts?.messages_last_7_days;

  return (
    <div className="bg-[#F8FAFC] p-5 md:p-6 rounded-2xl">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="m-0 text-2xl font-bold text-slate-900">Dashboard</h1>
          <p className="m-0 mt-1 text-sm text-slate-500">Visão consolidada dos seus fluxos e atendimentos.</p>
        </div>
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {[
          ['💬', 'Conversas ativas', viewModel.activeConversations, '+0.0%'],
          ['🧠', 'Leads ativos', viewModel.activeLeads, '+0.0%'],
          ['📨', 'Mensagens hoje', viewModel.messagesToday, '+0.0%'],
          ['✅', 'Taxa de resposta', `${viewModel.responseRate}%`, '+0.0%'],
          ['🎯', 'Conversões', viewModel.conversions, '+0.0%'],
        ].map(([icon, label, value, change]) => (
          <div key={String(label)} className={cardClassName}>
            {isLoading ? (
              <div className="grid gap-3">
                <SkeletonLine width="30%" />
                <SkeletonLine width="55%" />
                <SkeletonLine width="40%" height={24} />
              </div>
            ) : (
              <>
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-lg">{icon}</span>
                  <span className="text-xs font-bold" style={{ color: String(change).startsWith('+') ? '#16A34A' : '#DC2626' }}>
                    {change}
                  </span>
                </div>
                <p className="m-0 mb-1 text-sm text-slate-500">{label}</p>
                <p className="m-0 text-2xl font-bold text-slate-900">{value}</p>
              </>
            )}
          </div>
        ))}
      </div>

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-3">
        <div className={`${cardClassName} xl:col-span-2`}>
          <p className="m-0 mb-3 font-bold text-slate-900">Mensagens — últimos 7 dias</p>
          {dashboardError ? (
            <ErrorState message={dashboardError} />
          ) : isLoading ? (
            <div className="grid gap-3">
              <SkeletonLine width="100%" height={180} />
            </div>
          ) : messagesLast7Days?.length ? (
            <DashboardChart data={messagesLast7Days} />
          ) : (
            <EmptyState message="Nenhuma atividade recente." />
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className={cardClassName}>
          <p className="m-0 mb-3 font-bold text-slate-900">Top fluxos</p>
          {flowsError ? (
            <ErrorState message={flowsError} />
          ) : isLoading ? (
            <div className="grid gap-3">
              <SkeletonLine width="90%" />
              <SkeletonLine width="80%" />
              <SkeletonLine width="70%" />
            </div>
          ) : viewModel.topFlows.length ? (
            <div className="grid gap-2">
              {viewModel.topFlows.map((flow, index) => (
                <p key={flow.name} className="m-0 text-slate-700">
                  {index + 1}. {flow.name} — {flow.value}%
                </p>
              ))}
            </div>
          ) : (
            <EmptyState message="Nenhum fluxo com performance recente." />
          )}
        </div>

        <div className={cardClassName}>
          <p className="m-0 mb-3 font-bold text-slate-900">Canais de entrada</p>
          {conversationsError ? (
            <ErrorState message={conversationsError} />
          ) : isLoading ? (
            <div className="grid gap-3">
              <SkeletonLine width="85%" />
              <SkeletonLine width="60%" />
            </div>
          ) : viewModel.channels.length ? (
            <ul className="m-0 grid gap-2 pl-5 text-slate-600">
              {viewModel.channels.map((channel) => (
                <li key={channel.name}>
                  {channel.name}: {channel.value}%
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState message="Nenhum canal com dados no período." />
          )}
        </div>
      </div>
    </div>
  );
}
