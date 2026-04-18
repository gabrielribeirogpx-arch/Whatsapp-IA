'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import ReactFlow, {
  addEdge,
  Background,
  Connection,
  Controls,
  Edge,
  MiniMap,
  Node,
  NodeProps,
  useEdgesState,
  useNodesState
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { getFlowGraph, saveFlowGraph } from '../../../lib/api';

const FLOW_ID = 'default';

function MessageNode({ data }: NodeProps) {
  return <div style={{ padding: 10, background: '#DCF8C6', borderRadius: 8 }}>{String(data?.label || '')}</div>;
}

function QuestionNode({ data }: NodeProps) {
  return <div style={{ padding: 10, background: '#FFF3CD', borderRadius: 8 }}>{String(data?.label || '')}</div>;
}

export default function FlowBuilderPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [status, setStatus] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const graph = await getFlowGraph(FLOW_ID);
        setNodes((graph.nodes as Node[]) ?? []);
        setEdges((graph.edges as Edge[]) ?? []);
      } catch {
        setStatus('Não foi possível carregar o fluxo.');
      }
    }

    void load();
  }, [setEdges, setNodes]);

  const onConnect = useCallback(
    (params: Edge | Connection) => {
      setEdges((eds) => addEdge(params, eds));
    },
    [setEdges]
  );

  const nodeTypes = useMemo(
    () => ({
      messageNode: MessageNode,
      questionNode: QuestionNode
    }),
    []
  );

  const save = useCallback(async () => {
    try {
      await saveFlowGraph(FLOW_ID, { nodes: nodes as never[], edges: edges as never[] });
      setStatus('Fluxo salvo com sucesso ✅');
    } catch {
      setStatus('Erro ao salvar fluxo.');
    }
  }, [edges, nodes]);

  return (
    <main style={{ height: 'calc(100vh - 24px)', padding: 12 }}>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', marginBottom: 8 }}>
        <button onClick={save} type="button">
          Salvar
        </button>
        <span>{status}</span>
      </div>

      <div style={{ height: '92%', border: '1px solid #e6e6e6', borderRadius: 8 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          nodeTypes={nodeTypes}
          fitView
        >
          <MiniMap />
          <Controls />
          <Background />
        </ReactFlow>
      </div>
    </main>
  );
}
