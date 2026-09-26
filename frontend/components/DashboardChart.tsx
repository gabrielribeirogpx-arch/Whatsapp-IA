'use client';

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type ChartPoint = { date: string; sent: number; received: number };
type DashboardChartProps = { data?: ChartPoint[]; title?: string; xAxisTickInterval?: number };
type TooltipProps = { active?: boolean; payload?: { value: number; dataKey?: string }[]; label?: string };

function formatDateLabel(dateValue: string) {
  // API labels are civil dates, not UTC instants. Noon avoids browser timezone drift.
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(dateValue)
    ? new Date(`${dateValue}T12:00:00`)
    : new Date(dateValue);
  if (Number.isNaN(parsed.getTime())) return dateValue;
  return parsed.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

function CustomTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null;

  const sent = payload.find((entry) => entry.dataKey === 'sent')?.value ?? 0;
  const received = payload.find((entry) => entry.dataKey === 'received')?.value ?? 0;

  return (
    <div className="motion-tooltip rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-[0_8px_24px_rgba(15,23,42,0.10)]">
      <div className="mb-1 font-semibold text-slate-900">{label}</div>
      <div className="flex items-center justify-between gap-4">
        <span className="text-blue-500">Recebidas</span>
        <span className="font-semibold">{received}</span>
      </div>
      <div className="flex items-center justify-between gap-4">
        <span className="text-emerald-500">Enviadas</span>
        <span className="font-semibold">{sent}</span>
      </div>
    </div>
  );
}

export default function DashboardChart({ data = [], title = 'Mensagens — últimos 7 dias', xAxisTickInterval = 0 }: DashboardChartProps) {
  const normalizedData = (data || []).map((item) => ({ ...item, date: formatDateLabel(item.date), sent: Number(item.sent) || 0, received: Number(item.received) || 0 }));
  const chartData = normalizedData.length ? normalizedData : Array.from({ length: 7 }, (_, index) => { const date = new Date(); date.setDate(date.getDate() - (6 - index)); return { date: formatDateLabel(date.toISOString()), sent: 0, received: 0 }; });

  return (
    <article className="motion-chart h-full overflow-visible">
      <div className="mb-2 flex items-center justify-between gap-4"><h2 className="m-0 text-[15px] font-semibold tracking-[-0.01em] text-slate-900">{title}</h2><button type="button" className="h-8 rounded-lg border border-slate-200 bg-slate-50 px-3 text-xs font-medium text-slate-600 transition hover:border-slate-300 hover:bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-200">Diário</button></div>
      <div className="motion-chart-legend mb-3 flex items-center gap-4 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-blue-500"></span>
          <span className="text-slate-500">Recebidas</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500"></span>
          <span className="text-slate-500">Enviadas</span>
        </div>
      </div>
      <div className="h-[300px] min-h-[300px] w-full overflow-visible">
        <ResponsiveContainer>
          <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 12 }}>
            <defs>
              <linearGradient id="receivedGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3B82F6" stopOpacity={0.12} /><stop offset="95%" stopColor="#3B82F6" stopOpacity={0} /></linearGradient>
              <linearGradient id="sentGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#16A34A" stopOpacity={0.1} /><stop offset="95%" stopColor="#16A34A" stopOpacity={0} /></linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 5" stroke="#eef2f7" vertical={false} />
            <XAxis
              dataKey="date"
              interval={xAxisTickInterval}
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="received"
              stroke="#3b82f6"
              fill="url(#receivedGradient)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }}
              name="Recebidas"
            />
            <Area
              type="monotone"
              dataKey="sent"
              stroke="#22c55e"
              fill="url(#sentGradient)"
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: '#ffffff' }}
              name="Enviadas"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
