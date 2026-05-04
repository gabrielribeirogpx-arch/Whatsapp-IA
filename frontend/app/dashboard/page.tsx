'use client';

import { CSSProperties, useEffect, useMemo, useState } from 'react';

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

const cardBaseStyle: CSSProperties = {
  border: '1px solid #E2E8F0',
  borderRadius: 16,
  background: '#FFFFFF',
  padding: 18,
  boxShadow: '0 8px 24px rgba(15, 23, 42, 0.04)',
};

const premiumLabelStyle: CSSProperties = { margin: '0 0 12px', color: '#0F172A', fontWeight: 700 };
const subtleTextStyle: CSSProperties = { margin: 0, color: '#64748B', fontSize: 14 };

function SkeletonLine({ width = '100%', height = 12 }: { width?: string; height?: number }) {
  return (
    <div
      style={{
        width,
        height,
        borderRadius: 999,
        background: 'linear-gradient(90deg, #ECFDF5 0%, #E2E8F0 50%, #ECFDF5 100%)',
      }}
    />
  );
}

function EmptyState({ message }: { message: string }) {
  return <p style={subtleTextStyle}>{message}</p>;
}

function ErrorState({ message }: { message: string }) {
  return <p style={{ ...subtleTextStyle, color: '#B91C1C' }}>{message}</p>;
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
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: '#0F172A', margin: '0 0 4px' }}>Dashboard</h1>
          <p style={{ fontSize: 14, color: '#64748B', margin: 0 }}>Visão consolidada dos seus fluxos e atendimentos.</p>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 14, marginBottom: 20 }}>
        {[
          ['💬', 'Conversas ativas', viewModel.activeConversations, '+0.0%'],
          ['🧠', 'Leads ativos', viewModel.activeLeads, '+0.0%'],
          ['📨', 'Mensagens hoje', viewModel.messagesToday, '+0.0%'],
          ['✅', 'Taxa de resposta', `${viewModel.responseRate}%`, '+0.0%'],
          ['🎯', 'Conversões', viewModel.conversions, '+0.0%'],
        ].map(([icon, label, value, change]) => (
          <div key={String(label)} style={cardBaseStyle}>
            {isLoading ? (
              <div style={{ display: 'grid', gap: 10 }}>
                <SkeletonLine width="30%" />
                <SkeletonLine width="55%" />
                <SkeletonLine width="40%" height={24} />
              </div>
            ) : (
              <>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: 18 }}>{icon}</span>
                  <span style={{ fontSize: 12, color: String(change).startsWith('+') ? '#16A34A' : '#DC2626', fontWeight: 700 }}>
                    {change}
                  </span>
                </div>
                <p style={{ margin: '0 0 4px', fontSize: 13, color: '#64748B' }}>{label}</p>
                <p style={{ margin: '0 0 8px', fontSize: 24, fontWeight: 700, color: '#0F172A' }}>{value}</p>
              </>
            )}
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, marginBottom: 20 }}>
        <div style={cardBaseStyle}>
          <p style={premiumLabelStyle}>Mensagens — últimos 7 dias</p>
          {dashboardError ? (
            <ErrorState message={dashboardError} />
          ) : isLoading ? (
            <div style={{ display: 'grid', gap: 10 }}>
              <SkeletonLine width="100%" height={160} />
            </div>
          ) : messagesLast7Days?.length ? (
            <DashboardChart data={messagesLast7Days} />
          ) : (
            <EmptyState message="Nenhuma atividade recente." />
          )}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 16, marginBottom: 20 }}>
        <div style={cardBaseStyle}>
          <p style={premiumLabelStyle}>Top fluxos</p>
          {flowsError ? (
            <ErrorState message={flowsError} />
          ) : isLoading ? (
            <div style={{ display: 'grid', gap: 10 }}>
              <SkeletonLine width="90%" />
              <SkeletonLine width="80%" />
              <SkeletonLine width="70%" />
            </div>
          ) : viewModel.topFlows.length ? (
            viewModel.topFlows.map((flow, index) => (
              <p key={flow.name} style={{ margin: '0 0 8px', color: '#334155' }}>
                {index + 1}. {flow.name} — {flow.value}%
              </p>
            ))
          ) : (
            <EmptyState message="Nenhum fluxo com performance recente." />
          )}
        </div>

        <div style={cardBaseStyle}>
          <p style={premiumLabelStyle}>Canais de entrada</p>
          {conversationsError ? (
            <ErrorState message={conversationsError} />
          ) : isLoading ? (
            <div style={{ display: 'grid', gap: 10 }}>
              <SkeletonLine width="85%" />
              <SkeletonLine width="60%" />
            </div>
          ) : viewModel.channels.length ? (
            <ul style={{ margin: 0, paddingLeft: 18, color: '#475569', display: 'grid', gap: 8 }}>
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
    </>
  );
}
