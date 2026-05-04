'use client';

import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type ChartPoint = { date: string; sent: number; received: number };
type DashboardChartProps = { data?: ChartPoint[] };
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
  return <div className="rounded-xl border border-slate-700/40 bg-slate-900 px-3 py-2 text-xs text-slate-100 shadow-xl"><div className="mb-1 font-semibold">{label}</div><div>Enviadas: {sent}</div><div>Recebidas: {received}</div></div>;
}

export default function DashboardChart({ data = [] }: DashboardChartProps) {
  const normalizedData = data.map((item) => ({ ...item, date: formatDateLabel(item.date), sent: Number(item.sent) || 0, received: Number(item.received) || 0 }));
  const chartData = normalizedData.length ? normalizedData : Array.from({ length: 7 }, (_, index) => { const date = new Date(); date.setDate(date.getDate() - (6 - index)); return { date: formatDateLabel(date.toISOString()), sent: 0, received: 0 }; });

  return (
    <article className="h-full overflow-visible">
      <div className="mb-3 flex items-center justify-between"><h2 className="text-lg font-semibold text-slate-900">Mensagens — últimos 7 dias</h2><button type="button" className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-xs font-semibold text-slate-600">Diário</button></div>
      <div className="h-[300px] min-h-[300px] w-full overflow-visible">
        <ResponsiveContainer>
          <AreaChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 12 }}>
            <defs>
              <linearGradient id="receivedGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#3B82F6" stopOpacity={0.22} /><stop offset="95%" stopColor="#3B82F6" stopOpacity={0} /></linearGradient>
              <linearGradient id="sentGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#16A34A" stopOpacity={0.18} /><stop offset="95%" stopColor="#16A34A" stopOpacity={0} /></linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip content={<CustomTooltip />} />
            <Legend />
            <Area type="monotone" dataKey="received" stroke="#2196F3" fill="url(#receivedGradient)" fillOpacity={1} strokeWidth={2} dot={{ r: 3 }} name="Recebidas" />
            <Area type="monotone" dataKey="sent" stroke="#4CAF50" fill="url(#sentGradient)" fillOpacity={1} strokeWidth={2} dot={{ r: 3 }} name="Enviadas" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
