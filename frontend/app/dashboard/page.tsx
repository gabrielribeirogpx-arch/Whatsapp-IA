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

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [flows, setFlows] = useState<FlowItem[]>([]);

  useEffect(() => {
    async function loadDashboardData() {
      try {
        const res = await apiFetch('/api/dashboard');
        const payload = await parseApiResponse<DashboardData>(res);
        setData(payload);
      } catch {
        setData(null);
      }

      try {
        const payload = await getConversations();
        setConversations(Array.isArray(payload) ? payload : []);
      } catch {
        setConversations([]);
      }

      try {
        const payload = await listFlows();
        setFlows(Array.isArray(payload) ? payload : []);
      } catch {
        setFlows([]);
      }
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
  const cardBaseStyle = {
    border: '1px solid #E5E7EB',
    borderRadius: 16,
    background: '#FFFFFF',
    padding: 18,
    boxShadow: '0 1px 2px rgba(16,24,40,0.04)',
  };

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, color: '#111827', margin: '0 0 4px' }}>Dashboard</h1>
          <p style={{ fontSize: 14, color: '#6B7280', margin: 0 }}>Visão consolidada dos seus fluxos e atendimentos.</p>
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
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
              <span style={{ fontSize: 18 }}>{icon}</span>
              <span style={{ fontSize: 12, color: String(change).startsWith('+') ? '#16A34A' : '#DC2626', fontWeight: 700 }}>
                {change}
              </span>
            </div>
            <p style={{ margin: '0 0 4px', fontSize: 13, color: '#6B7280' }}>{label}</p>
            <p style={{ margin: '0 0 8px', fontSize: 24, fontWeight: 700, color: '#111827' }}>{value}</p>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, marginBottom: 20 }}>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Mensagens — últimos 7 dias</p>
          {messagesLast7Days ? <DashboardChart data={messagesLast7Days} /> : <p style={{ margin: 0, color: '#6B7280' }}>Sem dados para o período.</p>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 16, marginBottom: 20 }}>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Top fluxos</p>
          {viewModel.topFlows.length ? (
            viewModel.topFlows.map((flow, index) => (
              <p key={flow.name} style={{ margin: '0 0 8px', color: '#374151' }}>
                {index + 1}. {flow.name} — {flow.value}%
              </p>
            ))
          ) : (
            <p style={{ margin: 0, color: '#6B7280' }}>Sem fluxos para exibir.</p>
          )}
        </div>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Canais de entrada</p>
          <ul style={{ margin: 0, paddingLeft: 18, color: '#4B5563', display: 'grid', gap: 8 }}>
            {viewModel.channels.map((channel) => (
              <li key={channel.name}>
                {channel.name}: {channel.value}%
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
