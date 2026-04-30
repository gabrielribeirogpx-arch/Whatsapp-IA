'use client';

import Link from 'next/link';
import { useEffect, useRef, useState } from 'react';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js';

import { apiFetch, listFlows } from '@/lib/api';
import { FlowItem } from '@/lib/types';


ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  LineElement,
  PointElement,
  Title,
  Tooltip,
  Legend
);
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

    const ctx = chartRef.current.getContext('2d');
    if (!ctx) return;

    const chartInstance = new ChartJS(ctx, {
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

    return () => {
      chartInstance.destroy();
    };
  }, []);

  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: '#f7f8f7' }}>

      {/* Conteúdo principal */}
      <main className="dash-main">

        {/* Header */}
        <div className="dash-page-header-row">
          <div>
            <h1 className="dash-page-title">Automações</h1>
            <p className="dash-page-subtitle">Status de fluxos em tempo real</p>
          </div>
          <div className="dash-page-actions">
            <select
              className="dash-select"
              value={selectedFlow}
              onChange={(e) => setSelectedFlow(e.target.value)}
            >
              {flows.map((flow) => (
                <option key={flow.id} value={flow.id}>{flow.name}</option>
              ))}
            </select>
          </div>
        </div>

        {loading ? (
          <div style={{ padding: '2rem 36px', color: '#9ca3af', fontSize: 13 }}>Carregando...</div>
        ) : (
          <>
            {/* KPIs */}
            <div className="dash-kpi-grid">
              <div className="dash-kpi-card">
                <p className="dash-kpi-label">Execuções</p>
                <p className="dash-kpi-value">{analytics?.total_executions?.toLocaleString() ?? '2.4k'}</p>
                <span className="dash-kpi-trend up">↑ 24% em 7 dias</span>
              </div>
              <div className="dash-kpi-card">
                <p className="dash-kpi-label">Taxa sucesso</p>
                <p className="dash-kpi-value">98.3%</p>
                <p className="dash-kpi-unit">Saudável</p>
              </div>
              <div className="dash-kpi-card">
                <p className="dash-kpi-label">Tempo médio</p>
                <p className="dash-kpi-value">1.2s</p>
                <p className="dash-kpi-unit">Por execução</p>
              </div>
              <div className="dash-kpi-card">
                <p className="dash-kpi-label">Erros</p>
                <p className="dash-kpi-value">{analytics?.total_errors ?? 42}</p>
                <span className="dash-kpi-trend down">↓ 15 (últimas 24h)</span>
              </div>
            </div>

            {/* Gráfico */}
            <div className="dash-chart-section">
              <div className="dash-chart-section-header">
                <div>
                  <p className="dash-chart-section-title">Execuções — últimos 7 dias</p>
                  <p className="dash-chart-section-subtitle">Volume de execuções do fluxo selecionado</p>
                </div>
              </div>
              <div style={{ position: 'relative', width: '100%', height: 280 }}>
                <canvas ref={chartRef} />
              </div>
            </div>

            {/* Tabela de instâncias */}
            <div className="dash-table-section">
              <div className="dash-table-section-header">
                <h2 className="dash-table-section-title">Instâncias de fluxo</h2>
                <Link href="/dashboard/flows" className="dash-table-link">
                  Ver todas
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5"><polyline points="9 18 15 12 9 6"/></svg>
                </Link>
              </div>
              {sessions.length === 0 ? (
                <div style={{ padding: '32px', textAlign: 'center', color: '#9ca3af', fontSize: 13 }}>
                  Nenhuma instância encontrada.
                </div>
              ) : (
                <table className="dash-table">
                  <thead>
                    <tr>
                      <th>Conversa</th>
                      <th>Status</th>
                      <th>Node atual</th>
                      <th>Atualizado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sessions.map((session) => (
                      <tr key={session.id ?? session.conversation_id}>
                        <td><span className="dash-mono">{session.conversation_id}</span></td>
                        <td>
                          <span className={`dash-status-badge ${toBadgeStatus(session.status)}`}>
                            <span className="dash-status-dot" />
                            {session.status}
                          </span>
                        </td>
                        <td><span className="dash-mono">{session.current_node_id ?? '—'}</span></td>
                        <td style={{ color: '#9ca3af', fontSize: 12 }}>{getRelativeTime(session.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
