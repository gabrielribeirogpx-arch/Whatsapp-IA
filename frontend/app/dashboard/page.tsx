'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { getConversations, tenantLogin } from '../../lib/api';
import { Conversation, TenantAuth, TenantSession } from '../../lib/types';

const STORAGE_KEY = 'tenant_auth';

export default function DashboardPage() {
  const [auth, setAuth] = useState<TenantAuth | null>(null);
  const [session, setSession] = useState<TenantSession | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (!saved) return;

    try {
      const parsed = JSON.parse(saved) as TenantAuth;
      setAuth(parsed);

      tenantLogin(parsed)
        .then((tenantSession) => {
          setSession(tenantSession);
          return getConversations();
        })
        .then(setConversations)
        .catch(() => localStorage.removeItem(STORAGE_KEY));
    } catch {
      localStorage.removeItem(STORAGE_KEY);
    }
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
        <Link href="/chat" className="primary-button">
          Abrir chat
        </Link>
      </section>

      <section className="dashboard-grid">
        <article className="dashboard-card">
          <h2>Tenant</h2>
          <p>{session?.name || 'Não autenticado'}</p>
          <small>{auth ? `slug: ${auth.slug}` : 'Faça login em /chat para carregar os dados.'}</small>
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
