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

function formatDateLabel(dateValue: string) {
  const parsed = new Date(dateValue);

  if (Number.isNaN(parsed.getTime())) return dateValue;
  return parsed.toLocaleDateString('pt-BR', {
    day: '2-digit',
    month: 'short'
  });
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
    <article className="dashboard-card premium-card p-6 mt-6">
      <div className="dashboard-card-title">
        <h2 className="text-xs text-gray-500 uppercase tracking-wide">Mensagens (últimos 7 dias)</h2>
      </div>

      <div style={{ width: '100%', height: 300 }}>
        {hasActivity ? (
          <ResponsiveContainer>
            <LineChart data={normalizedData} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="date" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="sent" stroke="#4CAF50" name="Enviadas" />
              <Line type="monotone" dataKey="received" stroke="#2196F3" name="Recebidas" />
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
