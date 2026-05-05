'use client';

import { useEffect, useId, useMemo, useState } from 'react';
import Link from 'next/link';
import { Cell, Pie, PieChart } from 'recharts';
import { useRouter } from 'next/navigation';
import { MessageSquare } from "lucide-react";

import DashboardChart from '../../components/DashboardChart';
import { createFlow, getConversations, listFlows } from '../../lib/api';
import { Conversation, FlowItem, FlowPayload } from '../../lib/types';
import { useDashboardAnalytics } from '../../hooks/useDashboardAnalytics';

type DashboardViewModel = {
  activeConversations: number;
  activeLeads: number;
  messagesToday: number;
  responseRate: number;
  conversions: number;
  topFlows: Array<{ name: string; value: number }>;
  channels: Array<{ name: string; value: number }>;
};

type Period = '24h' | '7d' | '30d' | '90d';

const FALLBACK_VIEW_MODEL: DashboardViewModel = {
  activeConversations: 0,
  activeLeads: 0,
  messagesToday: 0,
  responseRate: 0,
  conversions: 0,
  topFlows: [],
  channels: [{ name: 'WhatsApp', value: 100 }],
};

const cardClassName =
  'bg-white rounded-2xl border border-slate-100 shadow-[0_12px_30px_rgba(15,23,42,0.05)] p-5';

const kpiMeta = [
  { key: 'activeConversations', label: 'Conversas ativas', suffix: '' },
  { key: 'activeLeads', label: 'Leads ativos', suffix: '' },
  { key: 'messagesToday', label: 'Mensagens hoje', suffix: '' },
  { key: 'responseRate', label: 'Taxa de resposta', suffix: '%' },
  { key: 'conversions', label: 'Conversões', suffix: '' },
] as const;

export default function DashboardPage() {
  const { data, kpis, timeseries } = useDashboardAnalytics();

  if (!data) {
    return (
      <div className="p-6 text-sm text-gray-500">
        Carregando dashboard...
      </div>
    );
  }

  const viewModel = {
    activeConversations: Number(kpis.conversations) || 0,
    activeLeads: Number(kpis.leads) || 0,
    messagesToday: Number(kpis.messages_received) || 0,
    responseRate: Number(kpis.response_rate) || 0,
    conversions: Number(kpis.conversions) || 0,
  };

  const safeSeries = {
    labels: timeseries?.labels ?? [],
    messages_sent: timeseries?.messages_sent ?? [],
    messages_received: timeseries?.messages_received ?? [],
  };

  const chartData = safeSeries.labels.map((label, i) => ({
    name: String(label || ''),
    sent: Number(safeSeries.messages_sent?.[i] ?? 0),
    received: Number(safeSeries.messages_received?.[i] ?? 0),
  }));

  return (
    <section className="p-6 space-y-6">
      
      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-4">
        {kpiMeta.map((item) => {
          const rawValue = viewModel[item.key as keyof typeof viewModel];

          const value =
            typeof rawValue === 'number' || typeof rawValue === 'string'
              ? rawValue
              : 0;

          return (
            <div
              key={item.key}
              className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm"
            >
              <p className="text-sm text-gray-500">{item.label}</p>
              <p className="text-2xl font-bold">
                {value}
                {item.suffix}
              </p>
            </div>
          );
        })}
      </div>

      {/* Chart */}
      <div className={cardClassName}>
        {Array.isArray(chartData) && chartData.length > 0 && (
          <DashboardChart
            data={chartData.map((item) => ({
              date: item.name,
              received: item.received,
              sent: item.sent,
            }))}
          />
        )}
      </div>

    </section>
  );
}