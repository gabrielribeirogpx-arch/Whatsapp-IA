'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

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

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero">
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
        <article className="dashboard-card">
          <h2>Tenant</h2>
          <p>{session?.slug || 'Não autenticado'}</p>
          <small>{session ? `slug: ${session.slug}` : 'Faça login em /login para carregar os dados.'}</small>
        </article>

        <article className="dashboard-card">
          <h2>Conversas ativas</h2>
          <p>{conversations.length}</p>
          <small>Total sincronizado com GET /conversations.</small>
        </article>

        <article className="dashboard-card">
          <h2>Atendimento humano</h2>
          <p>{humanInProgress}</p>
          <small>Conversas atualmente no modo humano.</small>
        </article>
      </section>
    </main>
  );
}
