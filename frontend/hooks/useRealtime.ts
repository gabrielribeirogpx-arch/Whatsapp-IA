import { useEffect, useRef, useState } from 'react';

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

    const connect = () => {
        // Fecha conexões anteriores se existirem
        ws.current?.close();
        es.current?.close();

        if (!wsUrl) return;

        console.log("[WS URL]", wsUrl);
        const token = typeof window !== 'undefined' ? localStorage.getItem('token') : '';
        
        // Se não houver token, usar SSE diretamente (fallback)
        if (!token) {
            console.log("[WS FALLBACK] Sem token, usando SSE");
            connectSSE();
            return;
        }

        // WS com token real
        const socket = new WebSocket(`${wsUrl}?tenant_id=${encodeURIComponent(tenantId)}&token=${encodeURIComponent(token || '')}`);
        
        socket.onopen = () => {
            console.log("[WS OPEN]", socket.url);
        };
        
        socket.onmessage = (event) => {
            onMessage(JSON.parse(event.data));
        };
        
        socket.onerror = (e) => {
            console.log("[WS ERROR]", e);
            // Fallback para SSE se o WS falhar
            connectSSE();
        };

        socket.onclose = (e) => {
            console.log("[WS CLOSE]", e.code, e.reason);
        };
        
        ws.current = socket;
    };

    const connectSSE = () => {
        if (ws.current) ws.current.close();
        const source = new EventSource(`${sseUrl}?tenant_id=${encodeURIComponent(tenantId)}`);
        source.onmessage = (event) => {
            onMessage(JSON.parse(event.data));
        };
        es.current = source;
    };

    useEffect(() => {
        connect();
        return () => {
            ws.current?.close();
            es.current?.close();
            clearTimeout(reconnectTimeout.current);
        };
    }, [wsUrl, sseUrl, tenantId]);

    return { connected: !!ws.current || !!es.current };
}
