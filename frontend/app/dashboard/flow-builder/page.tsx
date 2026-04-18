'use client';

import { useEffect, useMemo, useState } from 'react';

import { getFlowGraph, getTenantSessionFromStorage } from '@/lib/api';
import { FlowEdgePayload, FlowNodePayload } from '@/lib/types';

const FETCH_TIMEOUT_MS = 8000;

export default function FlowBuilderPage() {
  const [nodes, setNodes] = useState<FlowNodePayload[]>([]);
  const [edges, setEdges] = useState<FlowEdgePayload[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;

    const loadFlow = async () => {
      try {
        const tenantSession = getTenantSessionFromStorage();
        const tenantId = tenantSession?.tenant_id;

        if (!tenantId) {
          if (active) {
            setNodes([]);
            setEdges([]);
          }
          return;
        }

        const timeoutPromise = new Promise<never>((_, reject) => {
          const timeoutId = setTimeout(() => {
            clearTimeout(timeoutId);
            reject(new Error('Timeout carregando flow'));
          }, FETCH_TIMEOUT_MS);
        });

        const data = await Promise.race([getFlowGraph(tenantId), timeoutPromise]);

        if (!active) return;

        setNodes(data?.nodes || []);
        setEdges(data?.edges || []);
      } catch {
        if (!active) return;
        setNodes([]);
        setEdges([]);
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    };

    loadFlow();

    return () => {
      active = false;
    };
  }, []);

  const isEmpty = useMemo(() => nodes.length === 0 && edges.length === 0, [edges.length, nodes.length]);

  if (isLoading) {
    return <div>Carregando fluxo...</div>;
  }

  if (isEmpty) {
    return <div>Nenhum fluxo ainda</div>;
  }

  return (
    <div>
      <h1>Flow Builder</h1>
      <p>{nodes.length} nós carregados.</p>
      <p>{edges.length} conexões carregadas.</p>
    </div>
  );
}
