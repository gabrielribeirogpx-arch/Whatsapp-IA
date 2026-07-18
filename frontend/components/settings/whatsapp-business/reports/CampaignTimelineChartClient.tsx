"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from "recharts";

import { formatCompact, formatDateTime, formatInteger } from "./formatters";

export type TimelinePoint = {
  bucket: string;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
};

type Props = {
  data: TimelinePoint[];
};

const colors = {
  sent: "#64748b",
  delivered: "#059669",
  read: "#4f46e5",
  failed: "#dc2626",
};

const labels = {
  sent: "Enviadas",
  delivered: "Entregues",
  read: "Lidas",
  failed: "Falhas",
};

const toFiniteNumber = (value: unknown) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export default function CampaignTimelineChartClient({ data }: Props) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const normalizedData = useMemo(
    () =>
      data
        .map((row) => ({
          bucket: String(row.bucket || ""),
          sent: toFiniteNumber(row.sent),
          delivered: toFiniteNumber(row.delivered),
          read: toFiniteNumber(row.read),
          failed: toFiniteNumber(row.failed),
        }))
        .filter((row) => row.bucket),
    [data],
  );

  useEffect(() => {
    if (process.env.NODE_ENV !== "development") return;

    const wrapper = wrapperRef.current;
    const responsiveContainer = wrapper?.querySelector(
      ".recharts-responsive-container",
    );
    const surface = wrapper?.querySelector("svg.recharts-surface");
    const linePaths = wrapper?.querySelectorAll(".recharts-line-curve");

    console.info("[CampaignTimelineChart] diagnóstico", {
      timelineLength: normalizedData.length,
      wrapperHeight: wrapper?.getBoundingClientRect().height ?? 0,
      hasResponsiveContainer: Boolean(responsiveContainer),
      hasSurface: Boolean(surface),
      linePathCount: linePaths?.length ?? 0,
    });
  }, [normalizedData]);

  return (
    <div ref={wrapperRef} className="h-[320px] w-full min-w-0">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={normalizedData}
          margin={{ top: 18, right: 20, bottom: 0, left: 0 }}
        >
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#edf0f4" />
          <XAxis
            dataKey="bucket"
            minTickGap={34}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v) => {
              const date = new Date(v);
              return Number.isNaN(date.getTime())
                ? String(v)
                : date.toLocaleDateString("pt-BR", {
                    day: "2-digit",
                    month: "2-digit",
                  });
            }}
          />
          <YAxis
            tickFormatter={formatCompact}
            width={52}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip
            contentStyle={{
              borderRadius: 14,
              border: "1px solid #E7EAF0",
              boxShadow: "0 18px 40px -28px rgba(15,23,42,.5)",
            }}
            labelFormatter={(v) => formatDateTime(String(v))}
            formatter={(v: unknown, n) => [formatInteger(Number(v)), n]}
          />
          <Legend />
          {(Object.keys(colors) as Array<keyof typeof colors>).map((key) => (
            <Line
              key={key}
              dot={false}
              activeDot={{ r: 4 }}
              strokeWidth={2.5}
              type="monotone"
              dataKey={key}
              name={labels[key]}
              stroke={colors[key]}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
