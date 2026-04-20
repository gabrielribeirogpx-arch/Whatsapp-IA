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
        background: '#fff',
        padding: '6px 10px',
        borderRadius: 8,
        border: '1px solid #eee',
        fontSize: 12,
        color: '#444',
        boxShadow: '0 2px 6px rgba(0,0,0,0.05)',
        whiteSpace: 'nowrap'
      }}
    >
      {date} • E:{sent} R:{received}
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

  const hasActivity = normalizedData.some((item) => item.sent > 0 || item.received > 0);

  return (
    <article className="dashboard-card premium-card p-6 mt-6 cursor-pointer">
      <div className="dashboard-card-title">
        <h2 className="text-xs text-gray-500 uppercase tracking-wide">Mensagens (últimos 7 dias)</h2>
      </div>

      <div style={{ width: '100%', height: 360 }}>
        {hasActivity ? (
          <ResponsiveContainer>
            <LineChart data={normalizedData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
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
        ) : (
          <div className="h-full flex items-center justify-center">
            <p>Sem atividade nos últimos 7 dias</p>
          </div>
        )}
      </div>
    </article>
  );
}
