'use client';

import { useMemo } from 'react';
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

  const sent = payload.find((entry) => entry.name === 'Enviadas')?.value ?? 0;
  const received = payload.find((entry) => entry.name === 'Recebidas')?.value ?? 0;

  return (
    <div className="rounded-md border border-gray-200 bg-white px-2 py-1.5 shadow-sm">
      <p className="text-xs text-gray-500">Data: {label}</p>
      <p className="text-xs font-normal text-gray-700">Enviadas: {sent}</p>
      <p className="text-xs font-normal text-gray-700">Recebidas: {received}</p>
    </div>
  );
}

export default function DashboardChart({ data = [] }: DashboardChartProps) {
  const normalizedData = useMemo(
    () =>
      data.map((item) => ({
        ...item,
        date: formatDateLabel(item.date),
        sent: Number(item.sent) || 0,
        received: Number(item.received) || 0
      })),
    [data]
  );

  const peak = useMemo(() => {
    if (!normalizedData.length) return null;

    return normalizedData.reduce(
      (best, item) => {
        if (item.sent > best.value) return { key: 'sent', date: item.date, value: item.sent };
        if (item.received > best.value) return { key: 'received', date: item.date, value: item.received };
        return best;
      },
      { key: 'sent', date: normalizedData[0].date, value: 0 }
    );
  }, [normalizedData]);

  const hasActivity = normalizedData.some((item) => item.sent > 0 || item.received > 0);

  const summaryText = hasActivity && peak && peak.value > 0
    ? `Pico: ${peak.date.replace(' de ', ' ').replace('.', '')} • ${peak.value} msg`
    : 'Sem atividade significativa nos últimos dias';

  return (
    <article className="dashboard-card premium-card p-6 mt-6 cursor-pointer">
      <div className="dashboard-card-title">
        <h2 className="text-xs text-gray-500 uppercase tracking-wide">Mensagens (últimos 7 dias)</h2>
      </div>
      <p className="mt-2 mb-2 text-[13px] font-medium text-[#777] opacity-80">{summaryText}</p>

      <div style={{ width: '100%', height: 300 }}>
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
                dot={(props: any) => {
                  const isPeak = peak?.key === 'sent' && props.payload?.date === peak.date;
                  return <circle {...props} r={isPeak ? 6 : 3} />;
                }}
              />
              <Line
                type="monotone"
                dataKey="received"
                stroke="#2196F3"
                name="Recebidas"
                dot={(props: any) => {
                  const isPeak = peak?.key === 'received' && props.payload?.date === peak.date;
                  return <circle {...props} r={isPeak ? 6 : 3} />;
                }}
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
