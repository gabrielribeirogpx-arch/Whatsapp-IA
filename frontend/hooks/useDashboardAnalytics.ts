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
        const res = await apiFetch('/api/dashboard/analytics');
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
    const timeseries = data?.timeseries ?? {};
    const labels = Array.isArray(timeseries.labels) ? timeseries.labels : [];

    const ensure = (values?: number[]) => {
      const source = Array.isArray(values) ? values.map((item) => Number(item) || 0) : [];
      if (source.length) return source;
      if (labels.length) return Array.from({ length: labels.length }, () => 0);
      return Array.from({ length: 7 }, () => 0);
    };

    const conversations = ensure(timeseries.conversations);
    const leads = ensure(timeseries.leads);
    const messages_received = ensure(timeseries.messages_received);
    const messages_sent = ensure(timeseries.messages_sent);
    const conversions = ensure(timeseries.conversions);

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
      conversations: sum(padded.conversations),
      leads: sum(padded.leads),
      messages_received: sum(padded.messages_received),
      messages_sent: sum(padded.messages_sent),
      response_rate: padded.messages_received.some((item) => item > 0)
        ? Number(((sum(padded.messages_sent) / Math.max(sum(padded.messages_received), 1)) * 100).toFixed(1))
        : 0,
      conversions: sum(padded.conversions),
    };

    return { kpis: calculated, timeseries: padded };
  }, [data]);

  return { ...normalized, isLoading, error };
}
