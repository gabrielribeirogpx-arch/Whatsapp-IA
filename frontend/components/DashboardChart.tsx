'use client';

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type ChartPoint = { date: string; sent: number; received: number };
type DashboardChartProps = { data?: ChartPoint[]; title?: string; xAxisTickInterval?: number };
type TooltipProps = { active?: boolean; payload?: { value: number; dataKey?: string }[]; label?: string };

function formatDateLabel(dateValue: string) {
  const parsed = new Date(dateValue);
  if (Number.isNaN(parsed.getTime())) return dateValue;
  return parsed.toLocaleDateString('pt-BR', { day: '2-digit', month: 'short' });
}

function CustomTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null;

  const sent = payload.find((entry) => entry.dataKey === 'sent')?.value ?? 0;
  const received = payload.find((entry) => entry.dataKey === 'received')?.value ?? 0;

  return (
    <div className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs text-slate-700 shadow-lg">
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
    <article className="h-full overflow-visible">
      <div className="mb-4 flex items-center justify-between"><h2 className="text-lg font-semibold text-slate-900">{title}</h2><button type="button" className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50">Diário</button></div>
      <div className="mb-3 flex items-center gap-4 text-xs">
        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-blue-500"></span>
          <span className="text-slate-600">Recebidas</span>
        </div>

        <div className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-full bg-emerald-500"></span>
          <span className="text-slate-600">Enviadas</span>
        </div>
      </div>
      <div className="h-[300px] min-h-[300px] w-full overflow-visible">
        <ResponsiveContainer>
          <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 12 }}>
            <defs>
              <linearGradient id="receivedGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3B82F6" stopOpacity={0.22} /><stop offset="95%" stopColor="#3B82F6" stopOpacity={0} /></linearGradient>
              <linearGradient id="sentGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#16A34A" stopOpacity={0.18} /><stop offset="95%" stopColor="#16A34A" stopOpacity={0} /></linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="4 4" stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="date"
              interval={xAxisTickInterval}
              tick={{ fill: '#64748b', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: '#94a3b8', fontSize: 12 }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="received"
              stroke="#3b82f6"
              fill="url(#receivedGradient)"
              strokeWidth={2.5}
              dot={{ r: 2 }}
              activeDot={{ r: 5 }}
              name="Recebidas"
            />
            <Area
              type="monotone"
              dataKey="sent"
              stroke="#22c55e"
              fill="url(#sentGradient)"
              strokeWidth={2.5}
              dot={{ r: 2 }}
              activeDot={{ r: 5 }}
              name="Enviadas"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
