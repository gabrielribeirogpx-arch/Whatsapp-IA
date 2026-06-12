import { useCallback, useEffect, useRef, useState } from 'react';

export function useRealtime({ 
    wsUrl, 
    sseUrl, 
    onMessage, 
    tenantId 
}: { 
    wsUrl: string; 
    sseUrl: string; 
    onMessage: (data: any) => void;
    tenantId: string;
}) {
    const ws = useRef<WebSocket | null>(null);
    const es = useRef<EventSource | null>(null);
    const reconnectTimeout = useRef<NodeJS.Timeout>();
    const onMessageRef = useRef(onMessage);
    const [connected, setConnected] = useState(false);

    useEffect(() => {
        onMessageRef.current = onMessage;
    }, [onMessage]);

    const sendJson = useCallback((payload: Record<string, unknown>) => {
        const socket = ws.current;
        if (!socket || socket.readyState !== WebSocket.OPEN) return false;
        socket.send(JSON.stringify(payload));
        return true;
    }, []);

    const connectSSE = useCallback(() => {
        if (ws.current) ws.current.close();
        if (!sseUrl) return;
        const source = new EventSource(`${sseUrl}?tenant_id=${encodeURIComponent(tenantId)}`);
        source.onopen = () => setConnected(true);
        source.onmessage = (event) => {
            onMessageRef.current(JSON.parse(event.data));
        };
        source.onerror = () => setConnected(false);
        es.current = source;
    }, [sseUrl, tenantId]);

    const connect = useCallback(() => {
        // Fecha conexões anteriores se existirem
        ws.current?.close();
        es.current?.close();
        setConnected(false);

        if (!wsUrl) {
            console.log("[WS CREATE] wsUrl vazio, abortando conexão");
            return;
        }

        console.log("[WS URL]", wsUrl);
        const token = typeof window !== 'undefined' ? localStorage.getItem('token') : '';

        // Se não houver token, usar SSE diretamente (fallback)
        if (!token) {
            console.log("[WS FALLBACK] Sem token, usando SSE");
            connectSSE();
            return;
        }

        // WS com token real
        console.log("[WS CREATE]");
        const socket = new WebSocket(`${wsUrl}?tenant_id=${encodeURIComponent(tenantId)}&token=${encodeURIComponent(token || '')}`);

        socket.onopen = () => {
            console.log("[WS OPEN]", socket.url);
            setConnected(true);
        };

        socket.onmessage = (event) => {
            console.log("[WS MESSAGE RECEIVED]", event.data);
            onMessageRef.current(JSON.parse(event.data));
        };

        socket.onerror = (e) => {
            console.log("[WS ERROR]", e);
            setConnected(false);
            // Fallback para SSE se o WS falhar
            connectSSE();
        };

        socket.onclose = (e) => {
            console.log("[WS CLOSE]", e.code, e.reason);
            setConnected(false);
        };

        ws.current = socket;
    }, [connectSSE, tenantId, wsUrl]);

    useEffect(() => {
        connect();
        return () => {
            ws.current?.close();
            es.current?.close();
            clearTimeout(reconnectTimeout.current);
        };
    }, [connect]);

    return { connected, sendJson };
}
