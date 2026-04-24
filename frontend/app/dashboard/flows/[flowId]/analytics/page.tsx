'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

import { getFlowAnalytics } from '@/lib/api';
import { FlowAnalytics } from '@/lib/types';

type Props = {
  params: {
    flowId: string;
  };
};

const EMPTY_ANALYTICS: FlowAnalytics = {
  entries: 0,
  messages_sent: 0,
  finalizations: 0,
};

export default function FlowAnalyticsPage({ params }: Props) {
  const [loading, setLoading] = useState(true);
  const [analytics, setAnalytics] = useState<FlowAnalytics>(EMPTY_ANALYTICS);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadAnalytics = async () => {
      setLoading(true);
      setError(null);

      try {
        const result = await getFlowAnalytics(params.flowId);
        setAnalytics(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Erro ao carregar analytics do flow.');
      } finally {
        setLoading(false);
      }
    };

    loadAnalytics();
  }, [params.flowId]);

  const chartData = useMemo(
    () => [
      { name: 'Entradas', value: analytics.entries },
      { name: 'Mensagens', value: analytics.messages_sent },
      { name: 'Finalizações', value: analytics.finalizations },
    ],
    [analytics.entries, analytics.finalizations, analytics.messages_sent]
  );

  return (
    <div style={{ padding: 24, display: 'grid', gap: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ margin: 0 }}>Analytics do Flow</h1>
          <p style={{ margin: '6px 0 0', color: '#6b7280' }}>Flow ID: {params.flowId}</p>
        </div>
        <Link href="/dashboard/flows">Voltar para flows</Link>
      </div>

      {loading ? (
        <p>Carregando analytics...</p>
      ) : error ? (
        <p style={{ color: '#dc2626' }}>{error}</p>
      ) : (
        <>
          <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
            <article style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 14 }}>
              <small style={{ color: '#6b7280' }}>Total de entradas</small>
              <h2 style={{ margin: '8px 0 0' }}>{analytics.entries}</h2>
            </article>
            <article style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 14 }}>
              <small style={{ color: '#6b7280' }}>Total de mensagens</small>
              <h2 style={{ margin: '8px 0 0' }}>{analytics.messages_sent}</h2>
            </article>
            <article style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 14 }}>
              <small style={{ color: '#6b7280' }}>Total de finalizações</small>
              <h2 style={{ margin: '8px 0 0' }}>{analytics.finalizations}</h2>
            </article>
          </section>

          <section style={{ border: '1px solid #e5e7eb', borderRadius: 10, padding: 14 }}>
            <h3 style={{ marginTop: 0 }}>Gráfico</h3>
            <div style={{ width: '100%', height: 320 }}>
              <ResponsiveContainer>
                <BarChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="value" fill="#2563eb" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
