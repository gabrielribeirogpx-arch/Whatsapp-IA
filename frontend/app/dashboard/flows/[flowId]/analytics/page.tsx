'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { getFlowAnalytics } from '@/lib/api';
import { FlowAnalytics } from '@/lib/types';

type Props = { params: { flowId: string } };

const EMPTY: FlowAnalytics = { entries: 0, messages_sent: 0, finalizations: 0 };

export default function FlowAnalyticsPage({ params }: Props) {
  const [loading, setLoading] = useState(true);
  const [analytics, setAnalytics] = useState<FlowAnalytics>(EMPTY);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      setLoading(true); setError(null);
      try { setAnalytics(await getFlowAnalytics(params.flowId)); }
      catch (err) { setError(err instanceof Error ? err.message : 'Erro ao carregar analytics.'); }
      finally { setLoading(false); }
    };
    load();
  }, [params.flowId]);

  const chartData = useMemo(() => [
    { name: 'Entradas', value: analytics.entries },
    { name: 'Mensagens', value: analytics.messages_sent },
    { name: 'Finalizações', value: analytics.finalizations },
  ], [analytics]);

  const stats = [
    { label: 'Entradas', value: analytics.entries, color: '#6366f1', bg: '#eef2ff' },
    { label: 'Mensagens enviadas', value: analytics.messages_sent, color: '#16a34a', bg: '#f0fdf4' },
    { label: 'Finalizações', value: analytics.finalizations, color: '#d97706', bg: '#fffbeb' },
  ];

  return (
    <div style={{ maxWidth: 1120, margin: '0 auto', padding: 'clamp(16px, 3vw, 32px)', fontFamily: 'Inter, -apple-system, sans-serif' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 28, flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 600, color: '#111', letterSpacing: '-0.02em' }}>Analytics do Flow</h1>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: '#aaa', fontFamily: 'monospace' }}>ID: {params.flowId}</p>
        </div>
        <Link href="/dashboard/flows" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: '#fff', border: '1px solid #e8e6e0', padding: '7px 14px', borderRadius: 8, fontSize: 13, color: '#555', textDecoration: 'none', fontWeight: 500 }}>
          ← Voltar
        </Link>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: '64px 0', color: '#aaa', fontSize: 13 }}>Carregando analytics...</div>
      ) : error ? (
        <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 12, padding: '16px 20px', color: '#dc2626', fontSize: 13 }}>{error}</div>
      ) : (
        <>
          {/* Stats */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, marginBottom: 24 }}>
            {stats.map((stat) => (
              <div key={stat.label} style={{ background: '#fff', border: '1px solid #e8e6e0', borderRadius: 14, padding: '20px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <div style={{ width: 32, height: 32, borderRadius: 8, background: stat.bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <div style={{ width: 10, height: 10, borderRadius: '50%', background: stat.color }} />
                  </div>
                  <span style={{ fontSize: 11, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{stat.label}</span>
                </div>
                <span style={{ fontSize: 36, fontWeight: 600, color: '#111', letterSpacing: '-0.03em' }}>{stat.value}</span>
              </div>
            ))}
          </div>

          {/* Chart */}
          <div style={{ background: '#fff', border: '1px solid #e8e6e0', borderRadius: 14, padding: '24px', boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
            <h3 style={{ margin: '0 0 20px', fontSize: 13, fontWeight: 600, color: '#888', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Visão geral</h3>
            <div style={{ width: '100%', height: 300 }}>
              <ResponsiveContainer>
                <BarChart data={chartData} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0ee" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: '#888' }} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: '#888' }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ borderRadius: 10, border: '1px solid #e8e6e0', fontSize: 13, boxShadow: '0 4px 12px rgba(0,0,0,0.08)' }} cursor={{ fill: '#f7f7f5' }} />
                  <Bar dataKey="value" fill="#16a34a" radius={[6, 6, 0, 0]} maxBarSize={80} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
