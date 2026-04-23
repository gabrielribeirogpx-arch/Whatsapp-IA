'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import DashboardChart from '../../components/DashboardChart';
import { IconChats, IconUsers } from '../../components/icons';
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

  const userName = 'Gabriel Lima';
  const messagesLast7Days = data?.charts?.messages_last_7_days;

  return (
    <div style={{ display: 'flex', height: '100vh', background: '#F7F8F7', fontFamily: 'Inter, -apple-system, sans-serif' }}>
      {/* Sidebar com ícones */}
      <nav
        style={{
          width: 56,
          background: '#FFFFFF',
          borderRight: '1px solid #E8EAE6',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          padding: '12px 0',
          gap: 4,
          flexShrink: 0,
        }}
      >
        {/* Logo */}
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 8,
            background: '#16A34A',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 16,
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="white">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z" />
            <path d="M12 0C5.373 0 0 5.373 0 12c0 2.123.555 4.116 1.527 5.845L.057 23.405a.5.5 0 00.61.61l5.56-1.47A11.943 11.943 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 22c-1.907 0-3.7-.484-5.265-1.337l-.378-.21-3.924 1.037 1.037-3.924-.21-.378A9.953 9.953 0 012 12C2 6.477 6.477 2 12 2s10 4.477 10 10-4.477 10-10 10z" />
          </svg>
        </div>

        {/* Nav items */}
        {[
          {
            href: '/dashboard',
            label: 'Dashboard',
            active: true,
            svg: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
              </svg>
            ),
          },
          {
            href: '/chat',
            label: 'Inbox',
            svg: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            ),
          },
          {
            href: '/crm',
            label: 'Clientes',
            svg: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
            ),
          },
          {
            href: '/pipeline',
            label: 'Pipeline',
            svg: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="20" x2="18" y2="10" />
                <line x1="12" y1="20" x2="12" y2="4" />
                <line x1="6" y1="20" x2="6" y2="14" />
              </svg>
            ),
          },
          {
            href: '/products',
            label: 'Produtos',
            svg: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
              </svg>
            ),
          },
          {
            href: '/knowledge',
            label: 'Knowledge',
            svg: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
                <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
              </svg>
            ),
          },
          {
            href: '/dashboard/flow-builder',
            label: 'Flow Builder',
            svg: (
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
              </svg>
            ),
          },
        ].map((item) => (
          <Link
            key={item.href}
            href={item.href}
            title={item.label}
            style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              textDecoration: 'none',
              background: item.active ? '#F0FDF4' : 'transparent',
              color: item.active ? '#16A34A' : '#9CA3AF',
              transition: 'background 0.15s, color 0.15s',
              border: item.active ? '1px solid #BBF7D0' : '1px solid transparent',
            }}
          >
            {item.svg}
          </Link>
        ))}

        {/* Avatar no bottom */}
        <div style={{ marginTop: 'auto', marginBottom: 4 }}>
          <div
            style={{
              width: 32,
              height: 32,
              borderRadius: '50%',
              background: '#16A34A',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 12,
              fontWeight: 700,
              color: '#fff',
            }}
          >
            GL
          </div>
        </div>
      </nav>

      {/* Conteúdo principal */}
      <main style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
        {/* Header */}
        <div style={{ marginBottom: 28 }}>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#111827', margin: 0 }}>{userName}</h1>
          <p style={{ fontSize: 13, color: '#6B7280', margin: '2px 0 0' }}>Sua central de conversas</p>
        </div>

        {/* Cards de métricas */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 16, marginBottom: 28 }}>
          {[
            {
              label: 'Conversas ativas',
              value: uniqueConversations.length,
              desc: 'Contatos com histórico recente na inbox.',
            },
            { label: 'Leads ativos', value: humanInProgress, desc: 'Conversas em modo humano neste momento.' },
            { label: 'Mensagens hoje', value: answeredToday, desc: 'Mensagens atualizadas no dia atual.' },
          ].map((card) => (
            <div
              key={card.label}
              style={{
                background: '#FFFFFF',
                border: '1px solid #E8EAE6',
                borderRadius: 12,
                padding: '20px 24px',
                boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
              }}
            >
              <p
                style={{
                  fontSize: 11,
                  fontWeight: 600,
                  color: '#9CA3AF',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  margin: '0 0 8px',
                }}
              >
                {card.label}
              </p>
              <p style={{ fontSize: 32, fontWeight: 700, color: '#111827', margin: '0 0 4px', lineHeight: 1 }}>
                {card.value}
              </p>
              <p style={{ fontSize: 12, color: '#9CA3AF', margin: 0 }}>{card.desc}</p>
            </div>
          ))}
        </div>

        {/* Gráfico */}
        {messagesLast7Days && (
          <div
            style={{
              background: '#FFFFFF',
              border: '1px solid #E8EAE6',
              borderRadius: 12,
              padding: '20px 24px',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}
          >
            <p style={{ fontSize: 13, fontWeight: 600, color: '#374151', margin: '0 0 16px' }}>
              Mensagens (últimos 7 dias)
            </p>
            <DashboardChart data={messagesLast7Days} />
          </div>
        )}
      </main>
    </div>
  );
}
