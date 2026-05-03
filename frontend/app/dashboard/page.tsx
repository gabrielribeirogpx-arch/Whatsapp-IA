'use client';

import { useEffect, useMemo, useState } from 'react';

import DashboardChart from '../../components/DashboardChart';
import { apiFetch, parseApiResponse } from '../../lib/api';
import { Conversation } from '../../lib/types';

type DashboardData = {
  charts?: {
    messages_last_7_days?: {
      date: string;
      sent: number;
      received: number;
    }[];
  };
};

export default function DashboardPage() {
  const conversations = useMemo<Conversation[]>(() => [], []);
  const conversationsMemo = useMemo(() => conversations, [conversations]);
  const [data, setData] = useState<DashboardData | null>(null);

  useEffect(() => {
    async function loadDashboardData() {
      try {
        const res = await apiFetch('/api/dashboard');
        const payload = await parseApiResponse<DashboardData>(res);
        setData(payload);
      } catch {
        setData(null);
      }
    }

    void loadDashboardData();
  }, []);

  const uniqueConversations = useMemo(() => {
    const seen = new Set<string>();

    return conversationsMemo.filter((conversation) => {
      const phone = conversation.phone ?? '';
      if (!phone || seen.has(phone)) return false;
      seen.add(phone);
      return true;
    });
  }, [conversationsMemo]);

  const humanInProgress = useMemo(
    () => uniqueConversations.filter((conversation) => conversation.mode === 'human').length,
    [uniqueConversations]
  );

  const answeredToday = useMemo(() => {
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

  const messagesLast7Days = data?.charts?.messages_last_7_days;

  return (
    <>
      <div style={{ marginBottom: 28 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700, color: '#111827', margin: '0 0 2px' }}>
          Bom dia, Gabriel 👋
        </h1>
        <p style={{ fontSize: 13, color: '#6B7280', margin: 0 }}>
          Aqui está o resumo das suas conversas hoje.
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 28 }}>
        <div className="dash-metric-card">
          <p className="dash-metric-label">Conversas ativas</p>
          <p className="dash-metric-value">{uniqueConversations.length}</p>
          <p className="dash-metric-desc">Contatos com histórico recente na inbox.</p>
        </div>
        <div className="dash-metric-card">
          <p className="dash-metric-label">Leads ativos</p>
          <p className="dash-metric-value">{humanInProgress}</p>
          <p className="dash-metric-desc">Conversas em modo humano neste momento.</p>
        </div>
        <div className="dash-metric-card">
          <p className="dash-metric-label">Mensagens hoje</p>
          <p className="dash-metric-value">{answeredToday}</p>
          <p className="dash-metric-desc">Mensagens atualizadas no dia atual.</p>
        </div>
      </div>

      {messagesLast7Days && (
        <div className="dash-chart-card">
          <p className="dash-chart-title">Mensagens — últimos 7 dias</p>
          <DashboardChart data={messagesLast7Days} />
        </div>
      )}
    </>
  );
}
