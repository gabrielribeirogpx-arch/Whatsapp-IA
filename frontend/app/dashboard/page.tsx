'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import DashboardChart from '../../components/DashboardChart';
import { apiFetch } from '../../lib/api';
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
        if (!res.ok) return;

        const payload = (await res.json()) as DashboardData;
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
    <div style={{ display: 'flex', minHeight: '100vh', background: '#F7F8F7', fontFamily: 'Inter, -apple-system, sans-serif' }}>
      {/* Sidebar */}
      <nav className="dash-sidebar">
        <div className="dash-sidebar-logo">
          <img src="/Logo.svg" alt="Ícone" className="logo-icon" />
          <img src="/Logo2.svg" alt="Logo" className="logo-full" />
        </div>

        <span className="dash-nav-section">Principal</span>

        <Link href="/dashboard" className="dash-nav-item active">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          <span className="dash-nav-label">Dashboard</span>
        </Link>

        <Link href="/chat" className="dash-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          <span className="dash-nav-label">Inbox</span>
        </Link>

        <Link href="/crm" className="dash-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          <span className="dash-nav-label">Clientes</span>
        </Link>

        <Link href="/pipeline" className="dash-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
          <span className="dash-nav-label">Pipeline</span>
        </Link>

        <div className="dash-nav-divider" />
        <span className="dash-nav-section">Ferramentas</span>

        <Link href="/products" className="dash-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/></svg>
          <span className="dash-nav-label">Produtos</span>
        </Link>

        <Link href="/knowledge" className="dash-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>
          <span className="dash-nav-label">Knowledge</span>
        </Link>

        <Link href="/dashboard/flow-builder" className="dash-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
          <span className="dash-nav-label">Flow Builder</span>
        </Link>

        <Link href="/dashboard/settings" className="dash-nav-item">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51h.01a1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          <span className="dash-nav-label">Configurações</span>
        </Link>

        <div style={{ marginTop: 'auto' }}>
          <div className="dash-nav-divider" />
          <div className="dash-nav-item">
            <div className="dash-avatar">GL</div>
            <div className="dash-nav-label">
              <div style={{ fontSize: 12, fontWeight: 600, color: '#111827' }}>Gabriel Lima</div>
              <div style={{ fontSize: 11, color: '#9CA3AF' }}>Admin</div>
            </div>
          </div>
        </div>
      </nav>

      {/* Conteúdo principal */}
      <main style={{ flex: 1, overflowY: 'auto', padding: '32px 36px' }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontSize: 22, fontWeight: 700, color: '#111827', margin: '0 0 2px' }}>
            Bom dia, Gabriel 👋
          </h1>
          <p style={{ fontSize: 13, color: '#6B7280', margin: 0 }}>
            Aqui está o resumo das suas conversas hoje.
          </p>
        </div>

        {/* Cards de métricas */}
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

        {/* Gráfico */}
        {messagesLast7Days && (
          <div className="dash-chart-card">
            <p className="dash-chart-title">Mensagens — últimos 7 dias</p>
            <DashboardChart data={messagesLast7Days} />
          </div>
        )}
      </main>
    </div>
  );
}
