'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  MiniMap,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import type { Connection, Edge, Node } from 'reactflow';
import 'reactflow/dist/style.css';

import ActionNode from '@/components/flow/nodes/ActionNode';
import ChoiceNode from '@/components/flow/nodes/ChoiceNode';
import ConditionNode from '@/components/flow/nodes/ConditionNode';
import DelayNode from '@/components/flow/nodes/DelayNode';
import MessageNode from '@/components/flow/nodes/MessageNode';
import { getFlowGraph, getTenantSessionFromStorage, saveFlowGraph } from '@/lib/api';
import { FlowEdgePayload, FlowNodePayload } from '@/lib/types';

const FETCH_TIMEOUT_MS = 8000;

const nodeTypes = {
  message: MessageNode,
  choice: ChoiceNode,
  condition: ConditionNode,
  delay: DelayNode,
  action: ActionNode,
  messageNode: MessageNode,
  choiceNode: ChoiceNode,
  conditionNode: ConditionNode,
  delayNode: DelayNode,
  actionNode: ActionNode,
};

type FlowNodeKind = 'message' | 'choice' | 'condition' | 'delay' | 'action';

const NODE_PRESETS: Record<FlowNodeKind, { label: string; type: string; data: Record<string, unknown> }> = {
  message: { label: 'Mensagem', type: 'message', data: { content: '' } },
  choice: {
    label: 'Escolha',
    type: 'choice',
    data: { content: '', buttons: [{ label: 'Quero planos', next: '' }, { label: 'Falar com humano', next: '' }] },
  },
  condition: { label: 'Condição', type: 'condition', data: { condition: '' } },
  delay: { label: 'Delay', type: 'delay', data: { content: '3' } },
  action: { label: 'Ação', type: 'action', data: { action: '' } },
};

const initialNodes: Node[] = [];
const initialEdges: Edge[] = [];

type Button = {
  label: string;
};

function randomPosition() {
  return {
    x: Math.floor(Math.random() * 550),
    y: Math.floor(Math.random() * 450),
  };
}

function makeNodeId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function getChoiceLabelByHandle(nodes: Node[], sourceId: string | null, sourceHandle: string | null): string {
  if (!sourceId || !sourceHandle) return '';
  const sourceNode = nodes.find((node) => node.id === sourceId);
  const buttons: Button[] = Array.isArray(sourceNode?.data?.buttons)
    ? (sourceNode.data.buttons as Button[])
    : [];
  const matchedButton = buttons.find(
    (button: Button) =>
      typeof button.label === 'string' &&
      button.label.trim() === sourceHandle,
  );
  return matchedButton?.label?.trim() || sourceHandle;
}

export default function FlowBuilderPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const updateNodeData = useCallback((nodeId: string, patch: Record<string, unknown>) => {
    setNodes((prev: Node[]) =>
      prev.map((node) => {
        if (node.id !== nodeId) return node;
        return {
          ...node,
          data: {
            ...node.data,
            ...patch,
          },
        };
      }),
    );
  }, [setNodes]);

  const buildFlowNode = useCallback(
    (node: FlowNodePayload): Node => ({
      id: node.id,
      type: node.type,
      position: node.position || randomPosition(),
      data: {
        ...node.data,
        label: node.data?.label || node.data?.content || `Node ${node.id}`,
        onChange: updateNodeData,
      },
    }),
    [updateNodeData],
  );

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

        const initialNodes = (data?.nodes || []).map(buildFlowNode);
        const initialEdges: Edge[] = (data?.edges || []).map((edge): Edge => ({
          id: edge.id,
          source: edge.source,
          sourceHandle: edge.sourceHandle || edge.data?.sourceHandle,
          target: edge.target,
          type: 'default',
          data: {
            sourceHandle: edge.sourceHandle || edge.data?.sourceHandle,
            condition: edge.data?.condition ?? edge.label ?? '',
          },
          label: edge.label || edge.data?.condition,
        }));

        setNodes(initialNodes);
        setEdges(initialEdges);
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
  }, [buildFlowNode, setEdges, setNodes]);

  const isEmpty = useMemo(() => nodes.length === 0 && edges.length === 0, [edges.length, nodes.length]);

  const onConnect = useCallback((params: Connection) => {
    const choiceLabel = getChoiceLabelByHandle(nodes, params.source || null, params.sourceHandle || null);
    const edgeLabel = choiceLabel || params.sourceHandle || '';

    setEdges((eds) =>
      addEdge(
        {
          ...params,
          sourceHandle: params.sourceHandle || undefined,
          label: edgeLabel || undefined,
          data: {
            sourceHandle: params.sourceHandle || undefined,
            condition: edgeLabel || undefined,
          },
        },
        eds,
      ),
    );
  }, [nodes, setEdges]);

  const addNode = useCallback(
    (kind: FlowNodeKind) => {
      const preset = NODE_PRESETS[kind];
      const newNode: Node = {
        id: makeNodeId(),
        type: preset.type,
        position: randomPosition(),
        data: {
          label: preset.label,
          ...preset.data,
          onChange: updateNodeData,
        },
      };

      setNodes((prev) => [...prev, newNode]);
    },
    [setNodes, updateNodeData],
  );

  const saveFlow = useCallback(async () => {
    const tenantSession = getTenantSessionFromStorage();
    const tenantId = tenantSession?.tenant_id;
    if (!tenantId) return;

    setIsSaving(true);
    try {
      const payloadNodes: FlowNodePayload[] = nodes.map((node) => {
        const { onChange, ...restData } = (node.data || {}) as FlowNodePayload['data'];
        return {
          id: node.id,
          type: node.type || 'message',
          position: node.position,
          data: restData,
        };
      });

      const payloadEdges: FlowEdgePayload[] = edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle || (edge.data as FlowEdgePayload['data'])?.sourceHandle,
        label: edge.label?.toString(),
        data: {
          ...(edge.data as FlowEdgePayload['data']),
          sourceHandle: edge.sourceHandle || (edge.data as FlowEdgePayload['data'])?.sourceHandle,
          condition:
            (edge.data as FlowEdgePayload['data'])?.condition ||
            edge.label?.toString() ||
            undefined,
        },
      }));

      const result = await saveFlowGraph(tenantId, { nodes: payloadNodes, edges: payloadEdges });
      setNodes((result.nodes || []).map(buildFlowNode));
      setEdges(
        (result.edges || []).map((edge): Edge => ({
          id: edge.id,
          source: edge.source,
          sourceHandle: edge.sourceHandle || edge.data?.sourceHandle,
          target: edge.target,
          type: 'default',
          data: {
            sourceHandle: edge.sourceHandle || edge.data?.sourceHandle,
            condition: edge.data?.condition ?? edge.label ?? '',
          },
          label: edge.label || edge.data?.condition,
        })),
      );
    } finally {
      setIsSaving(false);
    }
  }, [buildFlowNode, edges, nodes, setEdges, setNodes]);

  if (isLoading) {
    return <div>Carregando fluxo...</div>;
  }

  return (
    <div style={{ width: '100%', height: '100vh', display: 'flex' }}>
      <aside
        style={{ width: 220, borderRight: '1px solid #e5e7eb', padding: 12, display: 'grid', alignContent: 'start', gap: 8 }}
      >
        <strong>Blocos</strong>
        <button type="button" onClick={() => addNode('message')}>+ Mensagem</button>
        <button type="button" onClick={() => addNode('choice')}>+ Escolha</button>
        <button type="button" onClick={() => addNode('condition')}>+ Condição</button>
        <button type="button" onClick={() => addNode('delay')}>+ Delay</button>
        <button type="button" onClick={() => addNode('action')}>+ Ação</button>
        <hr style={{ borderColor: '#f3f4f6', width: '100%' }} />
        <button type="button" onClick={saveFlow} disabled={isSaving}>
          {isSaving ? 'Salvando...' : 'Salvar fluxo'}
        </button>
        {isEmpty ? <small>Nenhum node ainda.</small> : null}
      </aside>
      <main style={{ flex: 1 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodesDelete={(deleted) => {
            setNodes((nds) => nds.filter((node) => !deleted.find((item) => item.id === node.id)));
          }}
          nodeTypes={nodeTypes}
          nodesDraggable={true}
          nodesConnectable
          elementsSelectable
          deleteKeyCode={['Backspace', 'Delete']}
          snapToGrid
          snapGrid={[20, 20]}
          fitView
        >
          <Background />
          <MiniMap />
          <Controls />
        </ReactFlow>
      </main>
    </div>
  );
}
