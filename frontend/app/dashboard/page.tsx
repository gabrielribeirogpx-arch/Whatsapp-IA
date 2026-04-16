'use client';

import Link from 'next/link';
import { useMemo } from 'react';

import { IconChats, IconUsers } from '../../components/icons';
import { Conversation } from '../../lib/types';

export default function DashboardPage() {
  const conversations: Conversation[] = [];

  const uniqueConversations = useMemo(() => {
    const seen = new Set<string>();

    return conversations.filter((conversation) => {
      const phone = conversation.phone ?? '';
      if (!phone || seen.has(phone)) return false;
      seen.add(phone);
      return true;
    });
  }, [conversations]);

  const humanInProgress = useMemo(
    () => uniqueConversations.filter((conversation) => conversation.status === 'human').length,
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

  const userName = 'Gabriel Lima';

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero premium">
        <div>
          <h1>{userName}</h1>
          <p>Sua central de conversas</p>
        </div>
        <div className="dashboard-actions">
          <Link href="/crm" className="secondary-button">
            Clientes
          </Link>
          <Link href="/pipeline" className="secondary-button">
            Pipeline
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

      <section className="dashboard-grid gap-4 mt-8">
        <article className="dashboard-card premium-card p-6">
          <div className="dashboard-card-title">
            <IconChats width={20} />
            <h2 className="text-xs text-gray-500 uppercase tracking-wide">Conversas</h2>
          </div>
          <p className="text-3xl font-semibold">{uniqueConversations.length}</p>
          <small>Contatos com histórico recente na inbox.</small>
        </article>

        <article className="dashboard-card premium-card p-6">
          <div className="dashboard-card-title">
            <IconUsers width={20} />
            <h2 className="text-xs text-gray-500 uppercase tracking-wide">Online agora</h2>
          </div>
          <p className="text-3xl font-semibold">{humanInProgress}</p>
          <small>Conversas em modo humano neste momento.</small>
        </article>

        <article className="dashboard-card premium-card p-6">
          <div className="dashboard-card-title">
            <IconChats width={20} />
            <h2 className="text-xs text-gray-500 uppercase tracking-wide">Resolvidas hoje</h2>
          </div>
          <p className="text-3xl font-semibold">{answeredToday}</p>
          <small>Mensagens atualizadas no dia atual.</small>
        </article>
      </section>
    </main>
  );
}
