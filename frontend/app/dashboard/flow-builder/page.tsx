'use client';

import { useEffect, useMemo, useState } from 'react';
import ReactFlow, { Background, Controls, Edge, Node } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

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

  const flowNodes: Node[] = useMemo(
    () =>
      nodes.map((node) => ({
        id: node.id,
        type: node.type,
        data: {
          ...node.data,
          label: node.data?.label || node.data?.content || `Node ${node.id}`,
        },
        position: node.position || {
          x: Math.random() * 400,
          y: Math.random() * 400,
        },
      })),
    [nodes],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label || edge.data?.condition,
      })),
    [edges],
  );

  if (isLoading) {
    return <div>Carregando fluxo...</div>;
  }

  if (isEmpty) {
    return <div>Nenhum fluxo ainda</div>;
  }

  return (
    <div style={{ width: '100%', height: '100vh' }}>
      <ReactFlow nodes={flowNodes} edges={flowEdges} fitView>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
