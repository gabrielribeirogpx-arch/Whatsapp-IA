'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch, parseApiResponse } from '../lib/api';

type AnalyticsTimeseries = {
  conversations?: number[];
  leads?: number[];
  messages_received?: number[];
  messages_sent?: number[];
  conversions?: number[];
  labels?: string[];
};

type AnalyticsKpis = {
  conversations?: number;
  leads?: number;
  messages?: number;
  messages_received?: number;
  messages_sent?: number;
  response_rate?: number;
  conversions?: number;
};

type AnalyticsResponse = {
  kpis?: AnalyticsKpis;
  timeseries?: AnalyticsTimeseries;
};

export function useDashboardAnalytics() {
  const [data, setData] = useState<AnalyticsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      setIsLoading(true);
      try {
        const res = await apiFetch('/api/dashboard/analytics', { method: 'POST' });
        const payload = await parseApiResponse<AnalyticsResponse>(res);
        setData(payload ?? null);
        setError(null);
      } catch {
        setData(null);
        setError('Não foi possível carregar os indicadores do dashboard agora.');
      } finally {
        setIsLoading(false);
      }
    })();
  }, []);

  const normalized = useMemo(() => {
    const series = data?.timeseries ?? { labels: [], conversations: [], messages_received: [], messages_sent: [] };
    const labels = Array.isArray(series.labels) ? series.labels : [];
    const kpis = data?.kpis ?? {
      conversations: 0,
      leads: 0,
      messages: 0,
      messages_received: 0,
      messages_sent: 0,
      response_rate: 0,
      conversions: 0,
    };

    const ensure = (values?: number[]) => {
      const source = Array.isArray(values) ? values.map((item) => Number(item) || 0) : [];
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
      conversations: Number(kpis.conversations) || sum(padded.conversations),
      leads: Number(kpis.leads) || sum(padded.leads),
      messages_received: Number(kpis.messages_received ?? kpis.messages) || sum(padded.messages_received),
      messages_sent: Number(kpis.messages_sent) || sum(padded.messages_sent),
      response_rate: Number(kpis.response_rate)
        || (padded.messages_received.some((item) => item > 0)
          ? Number(((sum(padded.messages_sent) / Math.max(sum(padded.messages_received), 1)) * 100).toFixed(1))
          : 0),
      conversions: Number(kpis.conversions) || sum(padded.conversions),
    };

    return { kpis: calculated, timeseries: padded };
  }, [data]);

  return { ...normalized, isLoading, error };
}
