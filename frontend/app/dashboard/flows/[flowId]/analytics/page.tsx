'use client';

import { useEffect, useMemo, useState } from 'react';
import { BarChart3, Funnel, GitBranch, MessageSquareText, Sparkles, TrendingUp } from 'lucide-react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getFlowAnalytics, listFlows } from '@/lib/api';
type Props = { params: { flowId: string } };

type FlowAnalyticsApi = {
  flow_id?: string;
  flow_name?: string;
  period?: string;
  kpis?: {
    entries?: number;
    conversion_rate?: number;
    abandonment_rate?: number;
    avg_time_seconds?: number;
    handled_messages?: number;
  };
  funnel?: Array<{ node_id: string; node_label: string; node_type: string; entries?: number; dropoff_rate?: number; conversion_to_next_rate?: number }>;
  dropoffs?: Array<{ node_id: string; node_label: string; node_type: string; entries?: number; dropoff_rate?: number; conversion_to_next_rate?: number }>;
  common_responses?: Array<{ reply?: string; response?: string; count?: number; rate?: number }>;
  timeseries?: Array<{ date?: string; entries?: number; conversions?: number; abandonments?: number; messages?: number }>;
};

const periods = ['24h', '7d', '30d', '90d'];
function formatDuration(totalSeconds?: number) {
  const seconds = Math.max(0, Math.round(Number(totalSeconds) || 0));
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;

  if (minutes <= 0) return `${seconds}s`;
  if (remainingSeconds === 0) return `${minutes}m`;
  return `${minutes}m ${remainingSeconds}s`;
}

export default function Page({ params }: Props) {
  const [period, setPeriod] = useState('7d');
  const [timelineMetric, setTimelineMetric] = useState('entries');
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<FlowAnalyticsApi | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [flowStatus, setFlowStatus] = useState<'active' | 'draft' | 'inactive'>('inactive');

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError(null);
      try {
        setData((await getFlowAnalytics(params.flowId, period)) as FlowAnalyticsApi);
      } catch {
        setData(null);
        setError('Não foi possível carregar os analytics agora. Tente novamente em instantes.');
      } finally {
        setLoading(false);
      }
    })();
  }, [params.flowId, period]);

  useEffect(() => {
    (async () => {
      const flows = await listFlows();
      const flow = flows.find((item) => item.id === params.flowId);
      if (!flow) return;
      const status = (flow as { status?: string }).status;
      setFlowStatus(flow.is_active ? 'active' : status === 'draft' ? 'draft' : 'inactive');
    })();
  }, [params.flowId]);

  const kpis = useMemo(() => [
    ['Entradas', Number(data?.kpis?.entries ?? 0)],
    ['Conversão', `${Number(data?.kpis?.conversion_rate ?? 0)}%`],
    ['Abandono', `${Number(data?.kpis?.abandonment_rate ?? 0)}%`],
    ['Tempo médio', formatDuration(data?.kpis?.avg_time_seconds)],
    ['Mensagens tratadas', Number(data?.kpis?.handled_messages ?? 0)],
  ], [data]);

  const noData = Number(data?.kpis?.entries ?? 0) === 0;
  const timeseries = (data?.timeseries ?? []).map((point) => ({
    date: point.date ?? '',
    entries: Number(point.entries ?? 0),
    completed: Number(point.conversions ?? 0),
    abandonments: Number(point.abandonments ?? 0),
    messages_sent: Number(point.messages ?? 0),
  }));
  const timelineHasRelevantPoints = timeseries.some(
    (point) => point.entries > 0 || point.messages_sent > 0 || point.completed > 0 || point.abandonments > 0,
  );

  return (
    <div className='flex justify-center w-full'>
      <div className='w-full max-w-[1160px] px-6 lg:px-8'>
        <div className='analytics-page'>
      <header className='analytics-header'>
        <div className='header-left'>
          <div className='analytics-icon' aria-hidden>
            <BarChart3 size={16} />
          </div>
          <div>
            <h1 className='page-title'>Analytics do Flow <span className={`status-badge ${flowStatus}`}>{flowStatus === 'active' ? 'Ativo' : flowStatus === 'draft' ? 'Draft' : 'Inativo'}</span></h1>
            <p className='breadcrumb'>Flows &gt; <span>{data?.flow_name || 'Flow'}</span></p>
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
        </div>
      </header>


      <div className='kpi-grid'>
        {kpis.map(([label, value], index) => (
          <div key={String(label)} className='card card-soft kpi-card'>
            <div className='kpi-top'>
              <span className={`kpi-icon kpi-icon-${index}`} aria-hidden><BarChart3 size={15} /></span>
              <div className='kpi-label'>{label}</div>
            </div>
            <div className='kpi-value'>{value}</div>
            <div className='kpi-trend secondary-text'>Variação: —</div>
          </div>
        ))}
      </div>

      {error && (
        <div className='card info-card' role='alert'>
          <span className='info-icon' aria-hidden>⚠️</span>
          <span>{error}</span>
        </div>
      )}

      {noData && !error && (
        <div className='card info-card' role='status'>
          <span className='info-icon' aria-hidden>
            ℹ️
          </span>
          <span>Ainda não há dados suficientes. Assim que usuários passarem por este flow, os analytics aparecerão aqui.</span>
        </div>
      )}

      <div className='main-grid'>
        <div className='card card-soft'>
          <h3 className='section-title'><Funnel size={18} />Funil do Flow</h3>
          {(data?.funnel ?? []).length === 0 ? (
            <div className='funnel-empty'>
              <svg viewBox='0 0 320 180' className='funnel-illustration' aria-hidden>
                <defs>
                  <linearGradient id='funnelGradient' x1='0%' y1='0%' x2='100%' y2='100%'>
                    <stop offset='0%' stopColor='#22c55e' stopOpacity='0.3' />
                    <stop offset='100%' stopColor='#16a34a' stopOpacity='0.55' />
                  </linearGradient>
                </defs>
                <ellipse cx='116' cy='38' rx='92' ry='12' fill='url(#funnelGradient)' />
                <path d='M24 38h184l-22 35H46z' fill='url(#funnelGradient)' opacity='0.9' />
                <ellipse cx='116' cy='73' rx='70' ry='10' fill='url(#funnelGradient)' opacity='0.8' />
                <path d='M46 73h140l-18 30H64z' fill='url(#funnelGradient)' opacity='0.75' />
                <ellipse cx='116' cy='103' rx='50' ry='8' fill='url(#funnelGradient)' opacity='0.7' />
                <path d='M64 103h104l-14 25H78z' fill='url(#funnelGradient)' opacity='0.6' />
                <ellipse cx='116' cy='128' rx='34' ry='6' fill='url(#funnelGradient)' opacity='0.58' />
              </svg>
              <div>
                <h4>Sem dados ainda</h4>
                <p className='secondary-text'>O funil será exibido assim que houver movimentação de usuários neste flow.</p>
              </div>
            </div>
          ) : (
            (data?.funnel ?? []).map((n, i) => {
          const dropoffRate = Number(n.dropoff_rate ?? 0);
          const color = dropoffRate > 40 ? '#EF4444' : dropoffRate > 20 ? '#EAB308' : '#22C55E';
          const pct = i === 0 ? 100 : Math.round(((n.entries ?? 0) / ((data?.funnel ?? [])[0]?.entries || 1)) * 100);
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
                Entradas {n.entries ?? 0} • Dropoff {n.dropoff_rate ?? 0}% • Conversão próximo {n.conversion_to_next_rate ?? 0}%
              </small>
            </div>
          );
            })
          )}
        </div>

        <div className='side-stack'>
          <div className='card card-soft'>
          <h3 className='section-title'><GitBranch size={18} />Pontos de abandono</h3>
          {(data?.dropoffs ?? []).length === 0 ? <div className='side-empty'><span className='side-icon'><GitBranch size={22} /></span><strong>—</strong><span className='secondary-text'>Sem dados suficientes</span></div> : (data?.dropoffs ?? []).map((n) => (
            <div key={n.node_id} className='secondary-text'>
              ⚠️ Node “{n.node_label}” — {n.dropoff_rate}% de abandono. Sugestão: simplifique a pergunta.
            </div>
          ))}
        </div>
          <div className='card card-soft'>
            <h3 className='section-title'><MessageSquareText size={18} />Respostas mais comuns</h3>
            {(data?.common_responses ?? []).length === 0 ? <div className='side-empty'><span className='side-icon'><MessageSquareText size={22} /></span><strong>—</strong><span className='secondary-text'>Sem dados suficientes</span></div> : (data?.common_responses ?? []).map((r, idx) => (
              <div key={`${r.reply ?? r.response ?? 'response'}-${idx}`} className='reply-row'>
                <span>{r.reply ?? r.response ?? '—'}</span>
                <span className='secondary-text'>{Number(r.rate ?? 0)}%</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className='card card-soft card-full-width'>
        <div className='section-header'>
          <h3 className='section-title'><TrendingUp size={18} />Performance ao longo do tempo</h3>
          <select
            className='metric-select'
            value={timelineMetric}
            onChange={(event) => setTimelineMetric(event.target.value)}
            aria-label='Selecionar métrica do gráfico'
          >
            <option value='entries'>Entradas</option>
            <option value='messages_sent'>Mensagens tratadas</option>
            <option value='completed'>Concluídos</option>
          </select>
        </div>
        <div style={{ height: 280 }}>
          {timelineHasRelevantPoints ? (
            <ResponsiveContainer>
              <LineChart data={timeseries}>
                <CartesianGrid strokeDasharray='3 3' stroke='#E2E8F0' />
                <XAxis dataKey='date' stroke='#64748B' />
                <YAxis stroke='#64748B' />
                <Tooltip />
                <Line
                  dataKey={timelineMetric}
                  stroke={timelineMetric === 'entries' ? '#2563EB' : timelineMetric === 'messages_sent' ? '#22C55E' : '#16A34A'}
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className='timeline-empty'>
              <div className='timeline-lines' aria-hidden>
                <span />
                <span />
                <span />
              </div>
              <div className='timeline-empty-icon'><BarChart3 size={18} /></div>
              <p>Sem dados para o período selecionado</p>
            </div>
          )}
        </div>
      </div>

      <div className='card card-soft card-rounded-lg card-full-width'>
        <div className='section-header'>
          <h3 className='section-title'><Sparkles size={18} />Insights automáticos</h3>
          <span className='coming-soon-badge'>Em breve</span>
        </div>
        <p className='secondary-text insights-description'>
          Aqui você encontrará análises inteligentes para melhorar conversão, reduzir abandonos e acelerar otimizações do flow.
        </p>
      </div>

      {loading && <div className='secondary-text'>Carregando...</div>}

          <style jsx>{`
        .analytics-page {
          background: #f8fafc;
          color: #0f172a;
          padding: 16px 0 28px;
        }
        .analytics-header {
          display: grid;
          grid-template-columns: 1fr auto;
          align-items: center;
          gap: 18px;
          margin-bottom: 30px;
        }
        .header-left,
        .header-right {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .analytics-icon {
          width: 32px;
          height: 32px;
          border-radius: 8px;
          display: grid;
          place-items: center;
          background: #f3f4f6;
          color: #6b7280;
        }
        .page-title {
          margin: 0;
          font-size: 20px;
          font-weight: 600;
        }
        .status-badge {
          display: inline-flex;
          align-items: center;
          padding: 4px 10px;
          border-radius: 999px;
          font-size: 12px;
          margin-left: 10px;
          vertical-align: middle;
        }
        .status-badge.active { background: #dcfce7; color: #15803d; }
        .status-badge.draft { background: #fef3c7; color: #b45309; }
        .status-badge.inactive { background: #e2e8f0; color: #475569; }
        .btn { border-radius: 10px; padding: 8px 14px; border: 1px solid transparent; font-weight: 600; cursor: pointer; }
        .btn-primary { background: #16a34a; color: #fff; }
        .btn-secondary { background: #fff; border-color: #e2e8f0; color: #334155; }
        .btn-danger { background: #fff; border-color: #fecaca; color: #dc2626; }
        .btn-ghost { background: transparent; border-color: #e2e8f0; color: #64748b; padding: 6px 10px; }
        .breadcrumb,
        .secondary-text,
        .period-label {
          color: #64748b;
        }
        .breadcrumb {
          margin: 4px 0 0;
        }
        .breadcrumb span { color: #16a34a; font-weight: 600; }
        .period-label {
          font-weight: 600;
        }
        .segmented-control {
          display: inline-flex;
          padding: 4px;
          border-radius: 999px;
          border: 1px solid #e5e7eb;
          background: #fff;
          gap: 4px;
        }
        .segment-btn {
          border: none;
          background: transparent;
          color: #334155;
          border-radius: 999px;
          padding: 8px 12px;
          cursor: pointer;
          transition: all 0.2s ease;
        }
        .segment-btn:hover {
          background: #f0fdf4;
          color: #16a34a;
        }
        .segment-btn.active {
          background: #dcfce7;
          color: #15803d;
        }
        .back-btn {
          color: #64748b;
          text-decoration: none;
          border: 1px solid #e5e7eb;
          width: 36px; height: 36px; display:grid; place-items:center;
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
          margin-bottom: 22px;
        }
        .card {
          margin-bottom: 12px;
          padding: 18px 20px;
        }
        .card-soft {
          background: #ffffff;
          border: 1px solid #e5e7eb;
          border-radius: 18px;
          box-shadow: 0 4px 20px rgba(2, 6, 23, 0.04);
        }
        .kpi-card {
          transition: transform 0.2s ease, box-shadow 0.25s ease;
        }
        .kpi-card:hover {
          transform: translateY(-3px);
          box-shadow: 0 10px 30px rgba(2, 6, 23, 0.08);
        }
        .card-rounded-lg {
          border-radius: 22px;
        }
        .card-full-width {
          width: 100%;
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
          border-radius: 10px;
          display: inline-block;
          background: #f0fdf4;
          color: #16a34a;
          display:grid;
          place-items:center;
        }
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
          display:flex;
          align-items:center;
          gap:10px;
        }
        .section-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 12px;
          margin-bottom: 14px;
          flex-wrap: wrap;
        }
        .metric-select {
          border: 1px solid #e5e7eb;
          background: #fff;
          color: #0f172a;
          border-radius: 10px;
          padding: 8px 12px;
          font-size: 14px;
        }
        .timeline-empty {
          height: 100%;
          border: 1px dashed #dcfce7;
          border-radius: 14px;
          display: grid;
          place-items: center;
          text-align: center;
          padding: 20px;
          color: #64748b;
          background: linear-gradient(180deg, #f0fdf4 0%, #ffffff 100%);
        }
        .timeline-empty-icon {
          width: 40px;
          height: 40px;
          border-radius: 12px;
          background: #dcfce7;
          color: #16a34a;
          display: grid;
          place-items: center;
          margin: 6px auto 8px;
        }
        .timeline-lines {
          width: min(480px, 100%);
          display: grid;
          gap: 10px;
          margin-bottom: 12px;
        }
        .timeline-lines span {
          height: 6px;
          border-radius: 999px;
          background: linear-gradient(90deg, #e2e8f0 0%, #f1f5f9 60%, #e2e8f0 100%);
        }
        .coming-soon-badge {
          display: inline-flex;
          align-items: center;
          border-radius: 999px;
          padding: 4px 10px;
          font-size: 12px;
          font-weight: 700;
          color: #15803d;
          background: #dcfce7;
        }
        .insights-description {
          margin-top: -4px;
          margin-bottom: 12px;
        }
        .insights-list {
          display: grid;
          gap: 10px;
        }
        .insight-item {
          border-left: 3px solid #93c5fd;
          padding-left: 12px;
        }
        .insight-title {
          display: block;
          color: #0f172a;
          margin-bottom: 2px;
        }
        .insight-item p {
          margin: 0;
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
          gap: 16px;
        }
        .side-stack {
          display: grid;
          gap: 12px;
          align-content: start;
        }
        .funnel-empty {
          min-height: 320px;
          display: grid;
          grid-template-columns: 1.1fr 1fr;
          align-items: center;
          text-align: left;
          gap: 14px;
          padding: 24px;
          background: linear-gradient(180deg, #ffffff 0%, #f8fffb 100%);
          border-radius: 16px;
        }
        .funnel-empty h4 {
          margin: 6px 0 4px;
          font-size: 20px;
          color: #0f172a;
        }
        .funnel-illustration {
          width: 340px;
          max-width: 100%;
          margin-bottom: 4px;
          filter: drop-shadow(0 20px 30px rgba(34, 197, 94, 0.13));
        }
        .side-empty { min-height: 170px; display:flex; flex-direction:column; justify-content:center; gap:8px; }
        .side-empty strong { font-size: 34px; color: #0f172a; line-height:1; }
        .side-icon { width: 46px; height:46px; border-radius: 14px; display:grid; place-items:center; background:#dcfce7; color:#15803d; }
        .reply-row {
          display: flex;
          justify-content: space-between;
          margin-bottom: 8px;
        }
        @media (max-width: 1024px) {
          .kpi-grid {
            grid-template-columns: 1fr;
          }
          .main-grid,
          .analytics-header {
            grid-template-columns: 1fr;
          }
          .header-right {
            justify-content: flex-start;
            flex-wrap: wrap;
          }
          .funnel-empty { grid-template-columns: 1fr; text-align: center; }
        }
      `}</style>
        </div>
      </div>
    </div>
  );
}
