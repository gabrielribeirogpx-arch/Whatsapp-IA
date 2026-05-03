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
    ['Entradas', data.summary.entries, 'bg-blue-500'],
    ['Conversão', `${data.summary.conversion_rate}%`, 'bg-emerald-500'],
    ['Abandono', `${data.summary.dropoff_rate}%`, 'bg-amber-500'],
    ['Tempo médio', `${Math.round(data.summary.avg_time_seconds)}s`, 'bg-violet-500'],
    ['Mensagens/usuário', data.summary.avg_messages_per_user, 'bg-cyan-500'],
  ];

  const noData = data.summary.entries === 0;

  return (
    <div className='min-h-screen bg-slate-50 px-4 py-8 md:px-8'>
      <div className='mx-auto flex w-full max-w-[1180px] flex-col gap-6'>
        <header className='rounded-2xl border border-slate-200 bg-white p-8 shadow-sm'>
          <div className='flex flex-wrap items-start justify-between gap-4'>
            <div>
              <h1 className='text-3xl font-bold tracking-tight text-slate-900'>Analytics do Flow</h1>
              <p className='mt-2 text-sm text-slate-600'>
                {data.flow_name}{' '}
                <span className='ml-1 inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700'>
                  Ativo/OFF
                </span>
              </p>
            </div>

            <div className='flex flex-wrap items-center gap-3'>
              <Link
                href='/dashboard/flows'
                className='inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 transition-all duration-150 hover:bg-slate-100'
              >
                ← Voltar
              </Link>
              <div className='inline-flex rounded-xl border border-slate-200 bg-slate-100 p-1'>
                {periods.map((p) => (
                  <button
                    key={p}
                    onClick={() => setPeriod(p)}
                    className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-all duration-150 ${
                      period === p ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </header>

        <section className='grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-5'>
          {kpis.map(([label, value, color]) => (
            <div
              key={String(label)}
              className='rounded-[18px] border border-slate-200 bg-white p-5 shadow-sm transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md'
            >
              <div className='mb-3 flex items-center justify-between'>
                <span className='text-xs font-semibold uppercase tracking-wider text-slate-500'>{label}</span>
                <span className={`h-2.5 w-2.5 rounded-full ${color}`}></span>
              </div>
              <div className='text-3xl font-bold text-slate-900'>{value}</div>
              <div className='mt-1 text-xs font-medium text-emerald-600'>+0%</div>
            </div>
          ))}
        </section>

        {noData && (
          <section className='rounded-2xl border border-slate-200 bg-white p-8 shadow-sm'>
            <div className='flex items-start gap-4'>
              <div className='rounded-xl bg-slate-100 p-3 text-xl'>📊</div>
              <div>
                <h2 className='text-lg font-semibold text-slate-900'>Aguardando dados do flow</h2>
                <p className='mt-1 text-sm text-slate-600'>
                  Assim que usuários passarem por este fluxo, os indicadores serão preenchidos automaticamente.
                </p>
                <button className='mt-4 rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition-all duration-150 hover:bg-slate-100'>
                  Abrir builder
                </button>
              </div>
            </div>
          </section>
        )}

        <section className='rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-150 hover:shadow-md'>
          <h3 className='text-lg font-semibold text-slate-900'>Funil do Flow</h3>
          <p className='mb-5 text-sm text-slate-500'>Acompanhe as conversões por etapa do fluxo.</p>
          {!data.funnel.length ? (
            <div className='rounded-xl border border-dashed border-slate-200 bg-slate-50 p-8 text-center text-sm text-slate-500'>
              Sem etapas registradas ainda.
            </div>
          ) : (
            data.funnel.map((n, i) => {
              const color = n.dropoff_rate > 40 ? '#ef4444' : n.dropoff_rate > 20 ? '#eab308' : '#22c55e';
              const pct = i === 0 ? 100 : Math.round((n.entries / (data.funnel[0]?.entries || 1)) * 100);
              return (
                <div key={n.node_id} className='mb-4'>
                  <div className='mb-1 flex items-center justify-between text-sm'>
                    <span className='font-medium text-slate-700'>
                      {n.node_label} ({n.node_type})
                    </span>
                    <span className='text-base font-bold text-slate-900'>{pct}%</span>
                  </div>
                  <div className='h-2.5 rounded-full bg-slate-100'>
                    <div className='h-2.5 rounded-full' style={{ width: `${pct}%`, background: color }} />
                  </div>
                </div>
              );
            })
          )}
        </section>

        <div className='grid grid-cols-1 gap-4 md:grid-cols-2'>
          <section className='rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-150 hover:shadow-md'>
            <h3 className='text-lg font-semibold text-slate-900'>Pontos de abandono</h3>
            <p className='mb-4 text-sm text-slate-500'>Etapas com maior taxa de saída.</p>
            {!data.top_dropoffs.length ? (
              <div className='rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500'>
                Nenhum ponto de abandono detectado.
              </div>
            ) : (
              data.top_dropoffs.map((n) => (
                <div key={n.node_id} className='mb-2 text-sm text-slate-700'>
                  ⚠️ Node “{n.node_label}” — {n.dropoff_rate}% de abandono.
                </div>
              ))
            )}
          </section>

          <section className='rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-150 hover:shadow-md'>
            <h3 className='text-lg font-semibold text-slate-900'>Respostas mais comuns</h3>
            <p className='mb-4 text-sm text-slate-500'>Entradas mais frequentes de usuários.</p>
            {!data.common_replies.length ? (
              <div className='rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500'>
                Sem respostas registradas no período.
              </div>
            ) : (
              data.common_replies.map((r) => (
                <div key={r.reply} className='mb-2 flex items-center justify-between text-sm text-slate-700'>
                  <span>{r.reply}</span>
                  <span className='font-semibold text-slate-900'>{r.rate}%</span>
                </div>
              ))
            )}
          </section>
        </div>

        <section className='rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-150 hover:shadow-md'>
          <h3 className='text-lg font-semibold text-slate-900'>Performance ao longo do tempo</h3>
          <p className='mb-4 text-sm text-slate-500'>Eventos e volume no período selecionado.</p>
          {!data.timeline.length ? (
            <div className='flex h-[280px] items-center justify-center rounded-xl border border-slate-200 bg-white'>
              <div className='h-full w-full rounded-xl bg-[linear-gradient(to_right,#f1f5f9_1px,transparent_1px),linear-gradient(to_bottom,#f1f5f9_1px,transparent_1px)] bg-[size:28px_28px]'>
                <div className='flex h-full items-center justify-center text-sm text-slate-500'>
                  Sem eventos no período selecionado
                </div>
              </div>
            </div>
          ) : (
            <div className='h-[280px]'>
              <ResponsiveContainer>
                <LineChart data={data.timeline}>
                  <CartesianGrid strokeDasharray='3 3' stroke='#e2e8f0' />
                  <XAxis dataKey='date' stroke='#64748b' fontSize={12} />
                  <YAxis stroke='#64748b' fontSize={12} />
                  <Tooltip />
                  <Line dataKey='entries' stroke='#3b82f6' strokeWidth={2} dot={false} />
                  <Line dataKey='messages_sent' stroke='#22c55e' strokeWidth={2} dot={false} />
                  <Line dataKey='completed' stroke='#a855f7' strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className='rounded-2xl border border-slate-200 bg-white p-6 shadow-sm transition-all duration-150 hover:shadow-md'>
          <h3 className='text-lg font-semibold text-slate-900'>Insights automáticos</h3>
          <p className='mb-4 text-sm text-slate-500'>Achados relevantes gerados a partir dos dados.</p>
          {!data.insights.length ? (
            <div className='rounded-xl border border-dashed border-slate-200 bg-slate-50 p-6'>
              <div className='text-base font-semibold text-slate-900'>✨ Nenhum insight ainda</div>
              <p className='mt-1 text-sm text-slate-600'>Os insights aparecerão quando houver volume suficiente.</p>
            </div>
          ) : (
            data.insights.map((i, idx) => (
              <div key={idx} className='mb-2 text-sm text-slate-700'>
                <span className='font-semibold text-slate-900'>{i.title}:</span> {i.message}
              </div>
            ))
          )}
        </section>

        {loading && <div className='text-sm text-slate-500'>Carregando...</div>}
      </div>
    </div>
  );
}
