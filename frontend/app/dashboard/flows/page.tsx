'use client';

import { useEffect, useMemo, useState } from 'react';

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

type FlowEvent = {
  id: string;
  title: string;
  timestamp: string;
  description: string;
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

function cardStyle() {
  return {
    background: '#fff',
    border: '1px solid #e5e7eb',
    borderRadius: 12,
    padding: 16,
    boxShadow: '0 4px 12px rgba(15, 23, 42, 0.05)'
  } as const;
}

export default function FlowAnalyticsPage() {
  const [flows, setFlows] = useState<FlowItem[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<string>('');
  const [analytics, setAnalytics] = useState<FlowAnalyticsResponse | null>(null);
  const [sessions, setSessions] = useState<FlowSession[]>([]);
  const [loading, setLoading] = useState(true);

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

  const events = useMemo<FlowEvent[]>(() => {
    if (sessions.length === 0) {
      return [
        {
          id: 'mock-1',
          title: 'Nenhum evento recente',
          timestamp: new Date().toISOString(),
          description: 'Assim que o flow for executado, os eventos aparecerão aqui.'
        }
      ];
    }

    return sessions.slice(0, 5).map((session, index) => ({
      id: session.id ?? `${session.conversation_id}-${index}`,
      title: `Sessão ${session.status}`,
      timestamp: session.updated_at ?? new Date().toISOString(),
      description: `Conversa ${session.conversation_id} no nó ${session.current_node_id ?? 'N/A'}`
    }));
  }, [sessions]);

  const summary = {
    totalExecutions: analytics?.total_executions ?? analytics?.entries ?? 0,
    totalSteps: analytics?.total_steps ?? analytics?.messages_sent ?? 0,
    totalWaits: analytics?.total_waits ?? 0,
    totalErrors: analytics?.total_errors ?? analytics?.finalizations ?? 0
  };

  return (
    <div style={{ padding: 24, display: 'grid', gap: 20, backgroundColor: '#f8fafc', minHeight: '100vh' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <h1 style={{ margin: 0 }}>Flow Analytics</h1>
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
      </div>

      {loading ? (
        <p>Carregando...</p>
      ) : (
        <>
          <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12 }}>
            <div style={cardStyle()}><strong>Total Execuções</strong><p style={{ fontSize: 24, margin: '8px 0 0' }}>{summary.totalExecutions}</p></div>
            <div style={cardStyle()}><strong>Total Steps</strong><p style={{ fontSize: 24, margin: '8px 0 0' }}>{summary.totalSteps}</p></div>
            <div style={cardStyle()}><strong>Total Waits</strong><p style={{ fontSize: 24, margin: '8px 0 0' }}>{summary.totalWaits}</p></div>
            <div style={cardStyle()}><strong>Total Errors</strong><p style={{ fontSize: 24, margin: '8px 0 0' }}>{summary.totalErrors}</p></div>
          </section>

          <section style={cardStyle()}>
            <h2 style={{ marginTop: 0 }}>Sessões</h2>
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
                      <td style={{ padding: '10px 0', borderTop: '1px solid #e2e8f0' }}>{session.conversation_id}</td>
                      <td style={{ borderTop: '1px solid #e2e8f0' }}>{session.status}</td>
                      <td style={{ borderTop: '1px solid #e2e8f0' }}>{session.current_node_id ?? '-'}</td>
                      <td style={{ borderTop: '1px solid #e2e8f0' }}>{session.updated_at ?? '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section style={cardStyle()}>
            <h2 style={{ marginTop: 0 }}>Últimos eventos</h2>
            <ul style={{ margin: 0, paddingLeft: 18, display: 'grid', gap: 8 }}>
              {events.map((event) => (
                <li key={event.id}>
                  <strong>{event.title}</strong> — {event.description} <small>({event.timestamp})</small>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
