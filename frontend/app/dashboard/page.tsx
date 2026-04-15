'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { IconChats, IconUsers } from '../../components/icons';
import { getConversations } from '../../lib/api';
import { Conversation } from '../../lib/types';

export default function DashboardPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);

  useEffect(() => {
    getConversations().then(setConversations).catch(() => localStorage.removeItem('tenant'));
  }, []);

  const humanInProgress = useMemo(
    () => conversations.filter((conversation) => conversation.status === 'human').length,
    [conversations]
  );

  const answeredToday = useMemo(() => {
    const now = new Date();

    return conversations.filter((conversation) => {
      const updatedAt = new Date(conversation.updated_at);

      return (
        !Number.isNaN(updatedAt.getTime()) &&
        updatedAt.getDate() === now.getDate() &&
        updatedAt.getMonth() === now.getMonth() &&
        updatedAt.getFullYear() === now.getFullYear()
      );
    }).length;
  }, [conversations]);

  const userName = 'Gabriel Lima';

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero premium">
        <div>
          <h1>{userName}</h1>
          <p>Sua central de atendimento</p>
        </div>
        <div className="dashboard-actions">
          <Link href="/crm" className="secondary-button">
            Clientes
          </Link>
          <Link href="/products" className="secondary-button">
            Produtos
          </Link>
          <Link href="/knowledge" className="secondary-button">
            Knowledge
          </Link>
          <Link href="/chat" className="primary-button">
            Abrir Inbox
          </Link>
        </div>
      </section>

      <section className="dashboard-grid">
        <article className="dashboard-card premium-card">
          <div className="dashboard-card-title">
            <IconChats width={20} />
            <h2>Conversas ativas</h2>
          </div>
          <p>{conversations.length}</p>
          <small>Contatos com histórico recente na inbox.</small>
        </article>

        <article className="dashboard-card premium-card">
          <div className="dashboard-card-title">
            <IconUsers width={20} />
            <h2>Em atendimento</h2>
          </div>
          <p>{humanInProgress}</p>
          <small>Conversas em modo humano neste momento.</small>
        </article>

        <article className="dashboard-card premium-card">
          <div className="dashboard-card-title">
            <IconChats width={20} />
            <h2>Respondidas hoje</h2>
          </div>
          <p>{answeredToday}</p>
          <small>Mensagens atualizadas no dia atual.</small>
        </article>
      </section>
    </main>
  );
}
