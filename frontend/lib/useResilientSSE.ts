'use client';

import { useEffect, useRef } from 'react';

type Options<T> = {
  url: string | null;
  enabled?: boolean;
  channel: string;
  reconnectDelayMs?: number;
  onEvent: (payload: T) => void;
};

export function useResilientSSE<T>({
  url,
  enabled = true,
  channel,
  reconnectDelayMs = 2000,
  onEvent,
}: Options<T>) {
  const onEventRef = useRef(onEvent);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!enabled || !url) return;

    let closed = false;
    let eventSource: EventSource | null = null;

    const connect = (isReconnect: boolean) => {
      if (closed) return;
      console.info(isReconnect ? '[SSE RECONNECT]' : '[SSE CONNECT]', { channel, url });
      eventSource = new EventSource(url);

      eventSource.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data || '{}') as T;
          onEventRef.current(payload);
        } catch {
          // ignore invalid event payload
        }
      };

      eventSource.onerror = () => {
        eventSource?.close();
        if (closed) return;
        if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = setTimeout(() => connect(true), reconnectDelayMs);
      };
    };

    connect(false);

    return () => {
      closed = true;
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      eventSource?.close();
      console.info('[SSE DISCONNECT]', { channel, url });
    };
  }, [channel, enabled, reconnectDelayMs, url]);
}
