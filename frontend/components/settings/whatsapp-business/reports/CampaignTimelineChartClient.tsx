"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
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

type SeriesKey = "delivered" | "read" | "sent" | "failed";

type TooltipPayload = {
  dataKey?: string;
  name?: string;
  value?: number | string;
  color?: string;
};

type TimelineTooltipProps = {
  active?: boolean;
  label?: string;
  payload?: TooltipPayload[];
};

const seriesConfig: Record<SeriesKey, { label: string; color: string; gradient: string; areaOpacity: number }> = {
  delivered: {
    label: "Entregues",
    color: "#059669",
    gradient: "deliveredTimelineGradient",
    areaOpacity: 0.24,
  },
  read: {
    label: "Lidas",
    color: "#4f46e5",
    gradient: "readTimelineGradient",
    areaOpacity: 0.16,
  },
  sent: {
    label: "Enviadas",
    color: "#64748b",
    gradient: "sentTimelineGradient",
    areaOpacity: 0.18,
  },
  failed: {
    label: "Falhas",
    color: "#dc2626",
    gradient: "failedTimelineGradient",
    areaOpacity: 0.06,
  },
};

const visualOrder: SeriesKey[] = ["delivered", "read", "sent", "failed"];
const areaOrder: SeriesKey[] = ["sent", "read", "delivered", "failed"];
const tooltipOrder: SeriesKey[] = ["sent", "delivered", "read", "failed"];

const toFiniteNumber = (value: unknown) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

function TimelineTooltip({ active, label, payload }: TimelineTooltipProps) {
  if (!active || !payload?.length) return null;

  const values = new Map(
    payload.map((entry) => [entry.dataKey, toFiniteNumber(entry.value)]),
  );

  return (
    <div className="min-w-[210px] rounded-xl border border-slate-200/90 bg-white/95 px-3.5 py-3 text-xs text-slate-600 shadow-[0_18px_45px_-30px_rgba(15,23,42,.38)] backdrop-blur-sm">
      <div className="mb-2 border-b border-slate-100 pb-2 text-sm font-semibold text-slate-950">
        {formatDateTime(String(label ?? ""))}
      </div>
      <div className="space-y-1.5">
        {tooltipOrder.map((key) => (
          <div key={key} className="flex items-center justify-between gap-6">
            <span className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ backgroundColor: seriesConfig[key].color }}
              />
              {seriesConfig[key].label}
            </span>
            <span className="font-semibold tabular-nums text-slate-900">
              {formatInteger(values.get(key) ?? 0)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function CampaignTimelineChartClient({ data }: Props) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const [visibleSeries, setVisibleSeries] = useState<Record<SeriesKey, boolean>>({
    delivered: true,
    read: true,
    sent: true,
    failed: true,
  });
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
    <div ref={wrapperRef} className="w-full min-w-0">
      <div className="mb-3 flex flex-wrap items-center gap-3 text-xs">
        {visualOrder.map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={visibleSeries[key]}
            onClick={() =>
              setVisibleSeries((current) => ({
                ...current,
                [key]: !current[key],
              }))
            }
            className={`flex items-center gap-2 rounded-full border px-2.5 py-1 transition duration-200 ${
              visibleSeries[key]
                ? "border-slate-200 bg-white text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,.04)]"
                : "border-slate-100 bg-slate-50 text-slate-400 opacity-70"
            }`}
          >
            <span
              className="h-2 w-2 rounded-full"
              style={{ backgroundColor: seriesConfig[key].color }}
            />
            {seriesConfig[key].label}
          </button>
        ))}
      </div>
      <div className="h-[320px] w-full min-w-0 rounded-xl border border-slate-100/80 bg-gradient-to-b from-white via-white to-slate-50/50 px-1 pt-1">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart
            data={normalizedData}
            margin={{ top: 18, right: 20, bottom: 8, left: 0 }}
          >
            <defs>
              {visualOrder.map((key) => (
                <linearGradient key={key} id={seriesConfig[key].gradient} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={seriesConfig[key].color} stopOpacity={seriesConfig[key].areaOpacity} />
                  <stop offset="100%" stopColor={seriesConfig[key].color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="#eef2f7" />
            <XAxis
              dataKey="bucket"
              minTickGap={34}
              tickLine={false}
              axisLine={false}
              tick={{ fill: "#64748b", fontSize: 12 }}
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
              tick={{ fill: "#94a3b8", fontSize: 12 }}
            />
            <Tooltip content={<TimelineTooltip />} cursor={{ stroke: "#cbd5e1", strokeWidth: 1, strokeDasharray: "4 4" }} />
            {areaOrder.map((key) =>
              visibleSeries[key] ? (
                <Area
                  key={`area-${key}`}
                  type="monotone"
                  dataKey={key}
                  fill={`url(#${seriesConfig[key].gradient})`}
                  stroke="none"
                  isAnimationActive
                  animationDuration={500}
                />
              ) : null,
            )}
            {visualOrder.map((key) =>
              visibleSeries[key] ? (
                <Line
                  key={`line-${key}`}
                  dot={false}
                  activeDot={{ r: key === "failed" ? 4 : 5 }}
                  strokeWidth={key === "failed" ? 2 : 2.5}
                  type="monotone"
                  dataKey={key}
                  name={seriesConfig[key].label}
                  stroke={seriesConfig[key].color}
                  isAnimationActive
                  animationDuration={650}
                />
              ) : null,
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
