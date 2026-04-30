'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';

import Header from '@/components/Dashboard/Header';
import KPICard from '@/components/Dashboard/KPICard';
import StatusBadge from '@/components/Dashboard/StatusBadge';
import { apiFetch, listFlows } from '@/lib/api';
import { FlowItem } from '@/lib/types';

type FlowAnalyticsResponse = {
  entries?: number;
  messages_sent?: number;
  finalizations?: number;
  total_executions?: number;
  total_steps?: number;
  total_waits?: number;
  total_errors?: number;
};

type FlowSession = {
  id?: string;
  conversation_id: string;
  status: string;
  current_node_id?: string | null;
  updated_at?: string | null;
};

async function fetchAnalytics(flowId: string): Promise<FlowAnalyticsResponse> {
  const res = await apiFetch(`/api/flows/${flowId}/analytics`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function fetchSessions(flowId: string): Promise<FlowSession[]> {
  const res = await apiFetch(`/api/flows/${flowId}/sessions`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function getRelativeTime(iso?: string | null) {
  if (!iso) return '-';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const diff = Date.now() - date.getTime();
  const mins = Math.max(1, Math.floor(diff / 60000));
  if (mins < 60) return `Há ${mins} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `Há ${hours} h`;
  const days = Math.floor(hours / 24);
  return `Há ${days} d`;
}

function toBadgeStatus(status: string): 'success' | 'warning' | 'danger' {
  const normalized = status.toLowerCase();
  if (normalized.includes('error') || normalized.includes('fail')) return 'danger';
  if (normalized.includes('wait') || normalized.includes('pending')) return 'warning';
  return 'success';
}

export default function FlowAnalyticsPage() {
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<string>('');
  const [analytics, setAnalytics] = useState<FlowAnalyticsResponse | null>(null);
  const [sessions, setSessions] = useState<FlowSession[]>([]);
  const [loading, setLoading] = useState(true);
  const chartRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const loadFlows = async () => {
      setLoading(true);
      try {
        const data = await listFlows();
        setFlows(data);
        if (data.length > 0) {
          setSelectedFlow(data[0].id);
        }
      } finally {
        setLoading(false);
      }
    };

    loadFlows();
  }, []);

  useEffect(() => {
    const loadFlowData = async () => {
      if (!selectedFlow) return;

      setLoading(true);
      try {
        const [analyticsData, sessionsData] = await Promise.all([
          fetchAnalytics(selectedFlow),
          fetchSessions(selectedFlow)
        ]);

        setAnalytics(analyticsData);
        setSessions(sessionsData);
      } finally {
        setLoading(false);
      }
    };

    loadFlowData();
  }, [selectedFlow]);

  useEffect(() => {
    if (!chartRef.current) return;

    let chartInstance: { destroy: () => void } | null = null;

    const loadChart = async () => {
      const { Chart, registerables } = await import('chart.js');
      Chart.register(...registerables);

      const ctx = chartRef.current?.getContext('2d');
      if (!ctx) return;

      chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
          labels: ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'],
          datasets: [
            {
              label: 'Execuções',
              data: [250, 320, 290, 410, 480, 350, 300],
              borderColor: '#075E54',
              backgroundColor: 'rgba(7, 94, 84, 0.08)',
              tension: 0.4,
              fill: true,
              pointRadius: 4,
              pointBackgroundColor: '#075E54',
              pointBorderColor: '#fff',
              pointBorderWidth: 2,
              pointHoverRadius: 6,
              borderWidth: 2
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { display: false }
          },
          scales: {
            y: {
              beginAtZero: true,
              grid: { color: 'rgba(115, 114, 108, 0.2)' },
              ticks: { color: '#3d3d3a', font: { size: 12 } }
            },
            x: {
              grid: { display: false },
              ticks: { color: '#3d3d3a', font: { size: 12 } }
            }
          }
        }
      });
    };

    void loadChart();

    return () => {
      chartInstance?.destroy();
    };
  }, []);

  return (
    <div style={{ backgroundColor: '#f8fafc', minHeight: '100vh' }}>
      <Header
        title="Automações"
        subtitle="Status de fluxos em tempo real"
        actions={(
          <select
            value={selectedFlow}
            onChange={(e) => setSelectedFlow(e.target.value)}
            style={{ minWidth: 280, padding: '10px 12px', borderRadius: 10, border: '1px solid #cbd5e1', background: '#fff' }}
          >
            {flows.map((flow) => (
              <option key={flow.id} value={flow.id}>
                {flow.name}
              </option>
            ))}
          </select>
        )}
      />
      {loading ? (
        <p style={{ padding: '2rem' }}>Carregando...</p>
      ) : (
        <div style={{ display: 'grid', gap: 16, padding: '2rem' }}>
          <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
            <KPICard label="Execuções" value="2.4k" trend="↑ 24% em 7 dias" />
            <KPICard label="Taxa sucesso" value="98.3%" unit="Saudável" />
            <KPICard label="Tempo médio" value="1.2s" unit="Por execução" />
            <KPICard label="Erros" value="42" trend="↓ 15 (últimas 24h)" />
          </section>

          <div style={{ padding: '2rem', borderBottom: '0.5px solid var(--color-border-tertiary)', background: '#fff', borderRadius: 12 }}>
            <h2 style={{ fontSize: '14px', fontWeight: 500, margin: '0 0 1.5rem', color: 'var(--color-text-primary)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
              Execuções últimos 7 dias
            </h2>
            <div style={{ position: 'relative', width: '100%', height: '280px' }}>
              <canvas id="executionsChart" ref={chartRef} />
            </div>
          </div>

          <section style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 12, padding: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h2 style={{ margin: 0 }}>Instâncias de fluxo</h2>
              <Link href="/dashboard/flows">Ver todas →</Link>
            </div>
            <p style={{ margin: '0 0 12px', fontSize: 12 }}>● Sucesso | ● Aguardando | ● Erro</p>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr>
                    <th align="left">conversation_id</th>
                    <th align="left">status</th>
                    <th align="left">current_node_id</th>
                    <th align="left">updated_at</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map((session) => (
                    <tr key={session.id ?? session.conversation_id}>
                      <td style={{ padding: '10px 0', borderTop: '1px solid #e2e8f0', fontFamily: 'monospace', fontSize: 12 }}>{session.conversation_id}</td>
                      <td style={{ borderTop: '1px solid #e2e8f0' }}><StatusBadge status={toBadgeStatus(session.status)} label={session.status} /></td>
                      <td style={{ borderTop: '1px solid #e2e8f0', fontFamily: 'monospace', fontSize: 12 }}>{session.current_node_id ?? '-'}</td>
                      <td style={{ borderTop: '1px solid #e2e8f0' }}>{getRelativeTime(session.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
