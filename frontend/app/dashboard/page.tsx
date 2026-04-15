'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { IconChats, IconChip, IconUsers } from '../../components/icons';
import { getConversations, getTenantSessionFromStorage } from '../../lib/api';
import { Conversation, TenantSession } from '../../lib/types';

export default function DashboardPage() {
  const [session, setSession] = useState<TenantSession | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);

  useEffect(() => {
    const tenant = getTenantSessionFromStorage();
    if (!tenant) return;

    setSession(tenant);
    getConversations().then(setConversations).catch(() => localStorage.removeItem('tenant'));
  }, []);

  const humanInProgress = useMemo(
    () => conversations.filter((conversation) => conversation.status === 'human').length,
    [conversations]
  );

  const conversationsByDay = useMemo(() => {
    const map = new Map<string, number>();

    conversations.forEach((conversation) => {
      const day = new Date(conversation.updated_at).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
      map.set(day, (map.get(day) || 0) + 1);
    });

    return Array.from(map.entries()).map(([day, total]) => ({ day, total }));
  }, [conversations]);

  const maxConversations = Math.max(...conversationsByDay.map((item) => item.total), 1);

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero premium">
        <div>
          <h1>Painel WhatsApp IA</h1>
          <p>Monitore atendimento e acesse rapidamente a operação de mensagens em tempo real.</p>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Link href="/crm" className="secondary-button">
            Abrir CRM
          </Link>
          <Link href="/chat" className="primary-button">
            Abrir chat
          </Link>
        </div>
      </section>

      <section className="dashboard-grid">
        <article className="dashboard-card premium-card">
          <div className="dashboard-card-title">
            <IconChip width={20} />
            <h2>Tenant</h2>
          </div>
          <p>{session?.slug || 'Não autenticado'}</p>
          <small>{session ? `slug: ${session.slug}` : 'Faça login em /login para carregar os dados.'}</small>
        </article>

        <article className="dashboard-card premium-card">
          <div className="dashboard-card-title">
            <IconChats width={20} />
            <h2>Conversas ativas</h2>
          </div>
          <p>{conversations.length}</p>
          <small>Total sincronizado com GET /conversations.</small>
        </article>

        <article className="dashboard-card premium-card">
          <div className="dashboard-card-title">
            <IconUsers width={20} />
            <h2>Atendimento humano</h2>
          </div>
          <p>{humanInProgress}</p>
          <small>Conversas atualmente no modo humano.</small>
        </article>
      </section>

      <section className="dashboard-chart-card">
        <h2>Conversas por dia</h2>
        <div className="dashboard-chart-wrap simple-chart">
          {conversationsByDay.length ? (
            conversationsByDay.map((point) => (
              <div key={point.day} className="simple-chart-row">
                <span>{point.day}</span>
                <div className="simple-chart-bar-track">
                  <div className="simple-chart-bar" style={{ width: `${(point.total / maxConversations) * 100}%` }} />
                </div>
                <strong>{point.total}</strong>
              </div>
            ))
          ) : (
            <p className="empty-state">Sem dados de conversa para exibir no gráfico.</p>
          )}
        </div>
      </section>
    </main>
  );
}
