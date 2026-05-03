'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getFlowAnalytics } from '@/lib/api';
import { FlowAnalytics } from '@/lib/types';

type Props = { params: { flowId: string } };

const periods = ['24h', '7d', '30d', '90d'];
const empty: FlowAnalytics = {
  flow_id: '',
  flow_name: 'Flow',
  period: '7d',
  summary: {
    entries: 0,
    messages_sent: 0,
    completed: 0,
    conversion_rate: 0,
    dropoff_rate: 0,
    avg_time_seconds: 0,
    avg_messages_per_user: 0,
  },
  funnel: [],
  top_dropoffs: [],
  common_replies: [],
  timeline: [],
  insights: [],
};

export default function Page({ params }: Props) {
  const [period, setPeriod] = useState('7d');
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<FlowAnalytics>(empty);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        setData(await getFlowAnalytics(params.flowId, period));
      } finally {
        setLoading(false);
      }
    })();
  }, [params.flowId, period]);

  const kpis = [
    ['Entradas', data.summary.entries],
    ['Conversão', `${data.summary.conversion_rate}%`],
    ['Abandono', `${data.summary.dropoff_rate}%`],
    ['Tempo médio', `${Math.round(data.summary.avg_time_seconds)}s`],
    ['Mensagens/usuário', data.summary.avg_messages_per_user],
  ];

  const noData = data.summary.entries === 0;

  return (
    <div className='analytics-page'>
      <header className='analytics-header'>
        <div className='header-left'>
          <div className='analytics-icon' aria-hidden>
            📊
          </div>
          <div>
            <h1 className='page-title'>Analytics do Flow</h1>
            <p className='breadcrumb'>Flows &gt; {data.flow_name}</p>
          </div>
        </div>

        <div className='header-right'>
          <div className='period-label'>Visão:</div>
          <div className='segmented-control'>
            {periods.map((p) => (
              <button
                key={p}
                onClick={() => setPeriod(p)}
                className={`segment-btn ${period === p ? 'active' : ''}`}
              >
                {p}
              </button>
            ))}
          </div>
          <Link href='/dashboard/flows' className='back-btn'>
            Voltar
          </Link>
        </div>
      </header>

      <div className='kpi-grid'>
        {kpis.map(([label, value]) => (
          <div key={String(label)} className='card card-soft'>
            <div className='kpi-label'>{label}</div>
            <div className='kpi-value'>{value}</div>
          </div>
        ))}
      </div>

      {noData && (
        <div className='card card-soft empty-state'>
          Ainda não há dados suficientes. Assim que usuários passarem por este flow, os analytics aparecerão aqui.
        </div>
      )}

      <div className='card card-soft'>
        <h3 className='section-title'>Funil do Flow</h3>
        {data.funnel.map((n, i) => {
          const color = n.dropoff_rate > 40 ? '#EF4444' : n.dropoff_rate > 20 ? '#EAB308' : '#22C55E';
          const pct = i === 0 ? 100 : Math.round((n.entries / (data.funnel[0]?.entries || 1)) * 100);
          return (
            <div key={n.node_id} className='funnel-row'>
              <div className='funnel-row-header'>
                <span>
                  {n.node_label} ({n.node_type})
                </span>
                <span>{pct}%</span>
              </div>
              <div className='progress-track'>
                <div className='progress-fill' style={{ width: `${pct}%`, background: color }} />
              </div>
              <small className='secondary-text'>
                Entradas {n.entries} • Dropoff {n.dropoff_rate}% • Conversão próximo {n.conversion_to_next_rate}%
              </small>
            </div>
          );
        })}
      </div>

      <div className='split-grid'>
        <div className='card card-soft'>
          <h3 className='section-title'>Pontos de abandono</h3>
          {data.top_dropoffs.map((n) => (
            <div key={n.node_id} className='secondary-text'>
              ⚠️ Node “{n.node_label}” — {n.dropoff_rate}% de abandono. Sugestão: simplifique a pergunta.
            </div>
          ))}
        </div>
        <div className='card card-soft'>
          <h3 className='section-title'>Respostas mais comuns</h3>
          {data.common_replies.map((r) => (
            <div key={r.reply} className='reply-row'>
              <span>{r.reply}</span>
              <span className='secondary-text'>{r.rate}%</span>
            </div>
          ))}
        </div>
      </div>

      <div className='card card-soft'>
        <h3 className='section-title'>Performance ao longo do tempo</h3>
        <div style={{ height: 280 }}>
          <ResponsiveContainer>
            <LineChart data={data.timeline}>
              <CartesianGrid strokeDasharray='3 3' stroke='#E2E8F0' />
              <XAxis dataKey='date' stroke='#64748B' />
              <YAxis stroke='#64748B' />
              <Tooltip />
              <Line dataKey='entries' stroke='#2563EB' strokeWidth={2} />
              <Line dataKey='messages_sent' stroke='#22C55E' strokeWidth={2} />
              <Line dataKey='completed' stroke='#16A34A' strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className='card card-soft card-rounded-lg'>
        <h3 className='section-title'>Insights automáticos</h3>
        {data.insights.map((insight, idx) => (
          <div key={idx} className='secondary-text'>
            <strong className='primary-text'>{insight.title}:</strong> {insight.message}
          </div>
        ))}
      </div>

      {loading && <div className='secondary-text'>Carregando...</div>}

      <style jsx>{`
        .analytics-page {
          max-width: 1220px;
          margin: 0 auto;
          padding: 32px;
          background: #f8fafc;
          color: #0f172a;
        }
        .analytics-header {
          display: grid;
          grid-template-columns: 1fr auto;
          align-items: center;
          gap: 16px;
          margin-bottom: 24px;
        }
        .header-left,
        .header-right {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .analytics-icon {
          width: 42px;
          height: 42px;
          border-radius: 12px;
          display: grid;
          place-items: center;
          background: #dbeafe;
          color: #2563eb;
          font-size: 20px;
        }
        .page-title {
          margin: 0;
          font-size: 30px;
          font-weight: 700;
        }
        .breadcrumb,
        .secondary-text,
        .period-label {
          color: #64748b;
        }
        .breadcrumb {
          margin: 4px 0 0;
        }
        .period-label {
          font-weight: 600;
        }
        .segmented-control {
          display: inline-flex;
          padding: 4px;
          border-radius: 999px;
          border: 1px solid #e5e7eb;
          background: #ffffff;
          gap: 4px;
        }
        .segment-btn {
          border: none;
          background: transparent;
          color: #64748b;
          border-radius: 999px;
          padding: 8px 12px;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .segment-btn:hover {
          background: #eff6ff;
          color: #2563eb;
        }
        .segment-btn.active {
          background: #2563eb;
          color: #fff;
        }
        .back-btn {
          color: #64748b;
          text-decoration: none;
          border: 1px solid #e5e7eb;
          padding: 8px 12px;
          border-radius: 10px;
          transition: all 0.2s ease;
        }
        .back-btn:hover {
          color: #0f172a;
          background: #fff;
          border-color: #cbd5e1;
        }
        .kpi-grid {
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 12px;
          margin-bottom: 18px;
        }
        .card {
          margin-bottom: 12px;
          padding: 16px;
        }
        .card-soft {
          background: #ffffff;
          border: 1px solid #e5e7eb;
          border-radius: 18px;
          box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
        }
        .card-rounded-lg {
          border-radius: 22px;
        }
        .kpi-label {
          color: #64748b;
          margin-bottom: 6px;
        }
        .kpi-value {
          font-size: 28px;
          font-weight: 700;
          color: #0f172a;
        }
        .section-title {
          margin: 0 0 14px;
          font-size: 18px;
          color: #0f172a;
        }
        .funnel-row {
          margin-bottom: 12px;
        }
        .funnel-row-header {
          display: flex;
          justify-content: space-between;
          margin-bottom: 4px;
        }
        .progress-track {
          height: 8px;
          background: #f1f5f9;
          border-radius: 999px;
          margin-bottom: 4px;
        }
        .progress-fill {
          height: 8px;
          border-radius: 999px;
        }
        .split-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
        }
        .reply-row {
          display: flex;
          justify-content: space-between;
          margin-bottom: 8px;
        }
        @media (max-width: 1024px) {
          .kpi-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
          .split-grid,
          .analytics-header {
            grid-template-columns: 1fr;
          }
          .header-right {
            justify-content: flex-start;
            flex-wrap: wrap;
          }
        }
      `}</style>
    </div>
  );
}
