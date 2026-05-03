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
    ['Mensagens tratadas', data.summary.messages_sent],
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
        {kpis.map(([label, value], index) => (
          <div key={String(label)} className='card card-soft kpi-card'>
            <div className='kpi-top'>
              <span className={`kpi-icon kpi-icon-${index}`} aria-hidden />
              <div className='kpi-label'>{label}</div>
            </div>
            <div className='kpi-value'>{value}</div>
            <div className='kpi-trend secondary-text'>Variação: —</div>
          </div>
        ))}
      </div>

      {noData && (
        <div className='card info-card' role='status'>
          <span className='info-icon' aria-hidden>
            ℹ️
          </span>
          <span>Ainda não há dados suficientes. Assim que usuários passarem por este flow, os analytics aparecerão aqui.</span>
        </div>
      )}

      <div className='main-grid'>
        <div className='card card-soft'>
          <h3 className='section-title'>Funil do Flow</h3>
          {data.funnel.length === 0 ? (
            <div className='funnel-empty'>
              <svg viewBox='0 0 240 140' className='funnel-illustration' aria-hidden>
                <defs>
                  <linearGradient id='funnelGradient' x1='0%' y1='0%' x2='100%' y2='100%'>
                    <stop offset='0%' stopColor='#bfdbfe' />
                    <stop offset='100%' stopColor='#bbf7d0' />
                  </linearGradient>
                </defs>
                <rect x='18' y='24' width='204' height='18' rx='9' fill='url(#funnelGradient)' opacity='0.9' />
                <rect x='42' y='56' width='156' height='18' rx='9' fill='url(#funnelGradient)' opacity='0.75' />
                <rect x='72' y='88' width='96' height='18' rx='9' fill='url(#funnelGradient)' opacity='0.6' />
                <circle cx='120' cy='117' r='8' fill='#60a5fa' opacity='0.8' />
              </svg>
              <h4>Sem dados ainda</h4>
              <p className='secondary-text'>Quando houver tráfego nesse flow, o funil de etapas aparecerá aqui.</p>
            </div>
          ) : (
            data.funnel.map((n, i) => {
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
            })
          )}
        </div>

        <div className='side-stack'>
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
        .kpi-card {
          transition: transform 0.2s ease, box-shadow 0.25s ease;
        }
        .kpi-card:hover {
          transform: translateY(-3px);
          box-shadow: 0 18px 34px rgba(15, 23, 42, 0.12);
        }
        .card-rounded-lg {
          border-radius: 22px;
        }
        .kpi-top {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-bottom: 8px;
        }
        .kpi-icon {
          width: 28px;
          height: 28px;
          border-radius: 999px;
          display: inline-block;
        }
        .kpi-icon-0 { background: #dbeafe; }
        .kpi-icon-1 { background: #dcfce7; }
        .kpi-icon-2 { background: #fee2e2; }
        .kpi-icon-3 { background: #fef3c7; }
        .kpi-icon-4 { background: #e0e7ff; }
        .kpi-label {
          color: #64748b;
        }
        .kpi-value {
          font-size: 28px;
          font-weight: 700;
          color: #0f172a;
        }
        .kpi-trend {
          margin-top: 8px;
          font-size: 13px;
        }
        .info-card {
          margin-bottom: 14px;
          padding: 14px 16px;
          display: flex;
          align-items: center;
          gap: 10px;
          border-radius: 14px;
          border: 1px solid #cce9df;
          background: #f2fbf8;
          color: #134e4a;
        }
        .info-icon {
          width: 26px;
          height: 26px;
          border-radius: 999px;
          display: grid;
          place-items: center;
          background: #e0f2fe;
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
        .main-grid {
          display: grid;
          grid-template-columns: 2fr 1fr;
          gap: 12px;
        }
        .side-stack {
          display: grid;
          gap: 12px;
          align-content: start;
        }
        .funnel-empty {
          min-height: 220px;
          display: grid;
          place-items: center;
          text-align: center;
          padding: 18px;
        }
        .funnel-empty h4 {
          margin: 6px 0 4px;
          font-size: 20px;
          color: #0f172a;
        }
        .funnel-illustration {
          width: 220px;
          max-width: 100%;
          margin-bottom: 4px;
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
          .main-grid,
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
