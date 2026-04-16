'use client';

import {
  CartesianGrid,
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

function formatDateLabel(dateValue: string) {
  const parsed = new Date(dateValue);

  if (Number.isNaN(parsed.getTime())) return dateValue;

  const day = String(parsed.getDate()).padStart(2, '0');
  const month = String(parsed.getMonth() + 1).padStart(2, '0');

  return `${day}/${month}`;
}

export default function DashboardChart({ data = [] }: DashboardChartProps) {
  const normalizedData = data.map((item) => ({
    ...item,
    date: formatDateLabel(item.date),
    sent: Number(item.sent) || 0,
    received: Number(item.received) || 0
  }));

  return (
    <article className="dashboard-card premium-card p-6 mt-6">
      <div className="dashboard-card-title">
        <h2 className="text-xs text-gray-500 uppercase tracking-wide">Mensagens (últimos 7 dias)</h2>
      </div>

      <div style={{ width: '100%', height: 300 }}>
        <ResponsiveContainer>
          <LineChart data={normalizedData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line type="monotone" dataKey="sent" stroke="#2563eb" name="Enviadas" strokeWidth={2} />
            <Line type="monotone" dataKey="received" stroke="#16a34a" name="Recebidas" strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </article>
  );
}
