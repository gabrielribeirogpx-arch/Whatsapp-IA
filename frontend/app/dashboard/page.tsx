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
        <div style={{ display: 'flex', gap: 10 }}>
          <button style={{ border: '1px solid #D1D5DB', background: '#fff', color: '#374151', borderRadius: 10, padding: '10px 14px', fontWeight: 600, cursor: 'pointer' }}>Últimos 7 dias</button>
          <button style={{ border: 'none', background: '#111827', color: '#fff', borderRadius: 10, padding: '10px 14px', fontWeight: 700, cursor: 'pointer' }}>+ Novo fluxo</button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 14, marginBottom: 20 }}>
        {[
          ['💬', 'Conversas ativas', uniqueConversations.length, '+8.4%'],
          ['🧠', 'Leads ativos', humanInProgress, '+5.1%'],
          ['📨', 'Mensagens hoje', answeredToday, '+11.2%'],
          ['✅', 'Resolução', '92%', '+2.3%'],
          ['⏱️', 'Tempo médio', '1m42s', '-0.8%'],
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
            <div style={{ height: 28, borderRadius: 8, background: 'linear-gradient(180deg, rgba(59,130,246,0.18), rgba(59,130,246,0.02))', position: 'relative', overflow: 'hidden' }}>
              <div style={{ position: 'absolute', width: '130%', height: 2, background: '#3B82F6', top: '58%', left: '-12%', transform: 'rotate(-4deg)' }} />
            </div>
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16, marginBottom: 20 }}>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Mensagens — últimos 7 dias</p>
          {messagesLast7Days ? <DashboardChart data={messagesLast7Days} /> : <p style={{ margin: 0, color: '#6B7280' }}>Sem dados para o período.</p>}
        </div>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Atividade ao vivo</p>
          <ul style={{ margin: 0, paddingLeft: 18, color: '#4B5563', display: 'grid', gap: 8 }}>
            <li>Novo lead entrou pelo Instagram há 2 min.</li>
            <li>Fluxo “Qualificação B2B” finalizou 3 contatos.</li>
            <li>2 conversas aguardando retorno humano.</li>
          </ul>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr 1fr', gap: 16, marginBottom: 20 }}>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Top fluxos</p>
          <p style={{ margin: '0 0 8px', color: '#374151' }}>1. Recuperação de carrinho — 41%</p>
          <p style={{ margin: '0 0 8px', color: '#374151' }}>2. Qualificação inbound — 28%</p>
          <p style={{ margin: 0, color: '#374151' }}>3. Reativação de leads — 17%</p>
        </div>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Canais de entrada</p>
          <div style={{ width: 130, height: 130, borderRadius: '50%', margin: '0 auto', background: 'conic-gradient(#3B82F6 0 45%, #10B981 45% 75%, #F59E0B 75% 100%)', position: 'relative' }}>
            <div style={{ position: 'absolute', inset: 26, background: '#fff', borderRadius: '50%' }} />
          </div>
        </div>
        <div style={cardBaseStyle}>
          <p style={{ margin: '0 0 12px', color: '#111827', fontWeight: 700 }}>Desempenho geral</p>
          <p style={{ margin: '0 0 8px', color: '#374151' }}>Meta mensal: 78% concluída</p>
          <p style={{ margin: '0 0 8px', color: '#374151' }}>Taxa de resposta: 95%</p>
          <p style={{ margin: 0, color: '#374151' }}>Satisfação estimada: 4.7/5</p>
        </div>
      </div>

      <div style={{ ...cardBaseStyle, background: 'linear-gradient(90deg, #111827 0%, #1F2937 100%)', color: '#fff', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <p style={{ margin: '0 0 4px', fontWeight: 700 }}>Pronto para escalar seus resultados?</p>
          <p style={{ margin: 0, color: '#D1D5DB' }}>Crie ou ajuste automações no construtor visual em poucos cliques.</p>
        </div>
        <button style={{ border: 'none', borderRadius: 10, background: '#fff', color: '#111827', fontWeight: 700, padding: '10px 14px', cursor: 'pointer' }}>Abrir builder</button>
      </div>
    </>
  );
}
