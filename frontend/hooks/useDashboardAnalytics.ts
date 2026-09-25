'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiFetch, parseApiResponse } from '../lib/api';

type AnalyticsTimeseries = {
  conversations?: number[];
  leads?: number[];
  messages_received?: number[];
  messages_sent?: number[];
  conversions?: number[];
  labels?: string[];
  messages_last_7_days?: Array<{
    date: string;
    sent: number;
    received: number;
  }>;
};

type AnalyticsKpis = {
  active_conversations?: number;
  active_leads?: number;
  messages_today?: number;
  conversations?: number;
  leads?: number;
  messages?: number;
  messages_received?: number;
  messages_sent?: number;
  response_rate?: number | null;
  response_rate_current?: number | null;
  response_rate_previous?: number | null;
  response_rate_delta?: number | null;
  conversions?: number;
  conversions_current?: number;
  conversions_previous?: number;
  conversions_delta?: number | null;
  messages_sent_today?: number;
  messages_received_today?: number;
  messages_sent_current?: number;
  messages_received_current?: number;
  messages_sent_previous?: number;
  messages_received_previous?: number;
  messages_delta?: number | null;
};

type AnalyticsResponse = {
  kpis?: AnalyticsKpis;
  timeseries?: AnalyticsTimeseries;
};

type NormalizedSeries = {
  labels: string[];
  conversations: number[];
  leads: number[];
  messages_received: number[];
  messages_sent: number[];
  conversions: number[];
};

const DEFAULT_KPIS: AnalyticsKpis = {
  active_conversations: 0,
  active_leads: 0,
  messages_today: 0,
  conversations: 0,
  leads: 0,
  messages: 0,
  messages_received: 0,
  messages_sent: 0,
  response_rate: null,
  conversions: 0,
};

const DEFAULT_SERIES: NormalizedSeries = {
  labels: [],
  conversations: [],
  leads: [],
  messages_received: [],
  messages_sent: [],
  conversions: [],
};

export type DashboardPeriod =
  | { preset: '24h' | '7d' | '30d' | '90d'; startDate?: never; endDate?: never }
  | { preset?: never; startDate: string; endDate: string };


type DashboardSummary = {
  top_flows?: Array<{ flow_id: string; name: string; conversations: number; conversation_count: number; conversion_rate: number | null }>;
  channels?: Array<{ channel: string; count: number; percentage: number }>;
  channel_conversations_total?: number;
  performance?: {
    avg_response_time_seconds: number | null;
    resolved_conversations: number;
    csat: number | null;
    abandonment_rate: number | null;
    completed_sessions_current: number;
    completed_sessions_previous: number;
    completed_sessions_delta: number | null;
    abandonment_rate_current: number | null;
    abandonment_rate_previous: number | null;
    abandonment_rate_delta: number | null;
  };
};

export function useDashboardAnalytics(period: DashboardPeriod = { preset: '7d' }) {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<DashboardSummary | null>(null);

  const refetch = useCallback(async () => {
    setIsLoading(true);
    try {
      const params = new URLSearchParams(period.preset
        ? { period: period.preset }
        : { start_date: period.startDate, end_date: period.endDate });
      const res = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL}/api/dashboard/analytics?${params}`);
      const payload = await parseApiResponse<AnalyticsResponse>(res);

      if (!payload) {
        setData(null);
        setError(null);
        return;
      }

      setData(payload);
      const summaryRes = await apiFetch(`${process.env.NEXT_PUBLIC_API_URL}/api/dashboard/summary?${params}`);
      const summaryPayload = await parseApiResponse<DashboardSummary>(summaryRes);
      setSummary(summaryPayload ?? null);
      setError(null);
    } catch {
      setData(null);
      setSummary(null);
      setError('Não foi possível carregar os indicadores do dashboard agora.');
    } finally {
      setIsLoading(false);
    }
  }, [period.endDate, period.preset, period.startDate]);

  useEffect(() => {
    void refetch();
  }, [refetch]);

  const normalized = useMemo(() => {
    const rawSeries = data?.timeseries;

    let adaptedSeries: NormalizedSeries = DEFAULT_SERIES;

    if (rawSeries?.messages_last_7_days) {
      adaptedSeries = {
        labels: rawSeries.messages_last_7_days.map((d) => d.date),
        messages_sent: rawSeries.messages_last_7_days.map((d) => Number(d.sent) ?? 0),
        messages_received: rawSeries.messages_last_7_days.map((d) => Number(d.received) ?? 0),
        conversations: [],
        leads: [],
        conversions: [],
      };
    } else {
      adaptedSeries = {
        labels: Array.isArray(rawSeries?.labels) ? rawSeries.labels : [],
        conversations: Array.isArray(rawSeries?.conversations) ? rawSeries.conversations : [],
        leads: Array.isArray(rawSeries?.leads) ? rawSeries.leads : [],
        messages_received: Array.isArray(rawSeries?.messages_received) ? rawSeries.messages_received : [],
        messages_sent: Array.isArray(rawSeries?.messages_sent) ? rawSeries.messages_sent : [],
        conversions: Array.isArray(rawSeries?.conversions) ? rawSeries.conversions : [],
      };
    }

    const series = adaptedSeries;
    const labels = Array.isArray(series.labels) ? series.labels : [];
    const kpis = data?.kpis ?? DEFAULT_KPIS;

    const ensure = (values?: number[]) => {
      const source = Array.isArray(values) ? values.map((item) => Number(item) ?? 0) : [];
      if (source.length) return source;
      if (labels.length) return Array.from({ length: labels.length }, () => 0);
      return Array.from({ length: 7 }, () => 0);
    };

    const conversations = ensure(series.conversations);
    const leads = ensure(series.leads);
    const messages_received = ensure(series.messages_received);
    const messages_sent = ensure(series.messages_sent);
    const conversions = ensure(series.conversions);

    const maxLen = Math.max(labels.length, conversations.length, leads.length, messages_received.length, messages_sent.length, conversions.length);
    const pad = (arr: number[]) => (arr.length === maxLen ? arr : [...arr, ...Array.from({ length: maxLen - arr.length }, () => 0)]);

    const padded = {
      conversations: pad(conversations),
      leads: pad(leads),
      messages_received: pad(messages_received),
      messages_sent: pad(messages_sent),
      conversions: pad(conversions),
      labels: labels.length === maxLen ? labels : Array.from({ length: maxLen }, (_, index) => `P${index + 1}`),
    };

    const sum = (arr: number[]) => arr.reduce((acc, value) => acc + value, 0);
    const calculated = {
      conversations: Number(kpis.active_conversations ?? kpis.conversations ?? sum(padded.conversations)),
      leads: Number(kpis.active_leads ?? kpis.leads ?? sum(padded.leads)),
      messages_received: Number(kpis.messages_received_current ?? kpis.messages_received ?? kpis.messages_received_today ?? sum(padded.messages_received)),
      messages_sent: Number(kpis.messages_sent_current ?? kpis.messages_sent ?? kpis.messages_sent_today ?? sum(padded.messages_sent)),
      messages_today: Number(kpis.messages_today ?? ((kpis.messages_sent_current ?? kpis.messages_sent ?? kpis.messages_sent_today ?? sum(padded.messages_sent)) + (kpis.messages_received_current ?? kpis.messages_received ?? kpis.messages_received_today ?? sum(padded.messages_received)))),
      response_rate: kpis.response_rate_current ?? kpis.response_rate ?? null,
      conversions: Number(kpis.conversions_current ?? kpis.conversions ?? sum(padded.conversions)),
      messages_delta: kpis.messages_delta ?? null,
      response_rate_delta: kpis.response_rate_delta ?? null,
      conversions_delta: kpis.conversions_delta ?? null,
    };

    return { kpis: calculated, timeseries: padded };
  }, [data]);

  return { data, summary, ...normalized, isLoading, error, refetch };
}
