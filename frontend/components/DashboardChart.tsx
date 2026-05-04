'use client';

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from 'recharts';

type ChartPoint = {
  date: string;
  sent: number;
  received: number;
};

type DashboardChartProps = {
  data?: ChartPoint[];
};

type TooltipProps = {
  active?: boolean;
  payload?: {
    value: number;
    name: string;
    stroke: string;
    dataKey?: string;
  }[];
  label?: string;
};

function formatDateLabel(dateValue: string) {
  const parsed = new Date(dateValue);

  if (Number.isNaN(parsed.getTime())) return dateValue;
  return parsed.toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: 'short'
  });
}

function CustomTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null;

  const sent = payload.find((entry) => entry.dataKey === 'sent')?.value ?? 0;
  const received = payload.find((entry) => entry.dataKey === 'received')?.value ?? 0;
  const parsedDate = label ? new Date(label) : null;
  const date = parsedDate && !Number.isNaN(parsedDate.getTime())
    ? parsedDate.toLocaleDateString('pt-BR', {
        day: '2-digit',
        month: 'short'
      })
    : (label ?? '');

  return (
    <div
      style={{
        background: '#0F172A',
        padding: '10px 12px',
        borderRadius: 10,
        border: '1px solid rgba(148,163,184,0.35)',
        fontSize: 12,
        color: '#E2E8F0',
        boxShadow: '0 10px 25px rgba(2,6,23,0.35)',
        minWidth: 140
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 6 }}>{date}</div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
        <span style={{ width: 8, height: 8, borderRadius: '9999px', background: '#22C55E', display: 'inline-block' }} />
        <span>Enviadas: {sent}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: '9999px', background: '#3B82F6', display: 'inline-block' }} />
        <span>Recebidas: {received}</span>
      </div>
    </div>
  );
}

export default function DashboardChart({ data = [] }: DashboardChartProps) {
  const normalizedData = data.map((item) => ({
    ...item,
    date: formatDateLabel(item.date),
    sent: Number(item.sent) || 0,
    received: Number(item.received) || 0
  }));

  const chartData = normalizedData.length
    ? normalizedData
    : Array.from({ length: 7 }, (_, index) => {
        const date = new Date();
        date.setDate(date.getDate() - (6 - index));
        return {
          date: formatDateLabel(date.toISOString()),
          sent: 0,
          received: 0
        };
      });

  const hasActivity = normalizedData.some((item) => item.sent > 0 || item.received > 0);

  return (
    <article className="dashboard-card premium-card p-6 mt-6 cursor-pointer">
      <div className="dashboard-card-title flex items-center justify-between mb-2">
        <h2 className="text-xs text-gray-500 uppercase tracking-wide">Mensagens (últimos 7 dias)</h2>
        <button
          type="button"
          className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600"
          aria-label="Periodicidade Diário"
        >
          Diário
        </button>
      </div>

      <div style={{ width: '100%', height: 360 }}>
        <ResponsiveContainer>
          <LineChart data={chartData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip content={<CustomTooltip />} />
              <Legend />
              <Line
                type="monotone"
                dataKey="sent"
                stroke="#4CAF50"
                name="Enviadas"
                dot={{ r: 3 }}
              />
              <Line
                type="monotone"
                dataKey="received"
                stroke="#2196F3"
                name="Recebidas"
                dot={{ r: 3 }}
              />
          </LineChart>
        </ResponsiveContainer>
        {!hasActivity ? <p className="mt-2 text-center text-sm text-slate-500">Sem atividade nos últimos 7 dias</p> : null}
      </div>
    </article>
  );
}
