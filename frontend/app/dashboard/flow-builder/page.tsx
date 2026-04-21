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
import { getLayoutedElements } from '@/lib/autoLayout';
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
type FlowConnection = Connection & { sourceHandle?: string | null };

const NODE_PRESETS: Record<FlowNodeKind, { label: string; type: string; data: Record<string, unknown> }> = {
  message: { label: 'Mensagem', type: 'message', data: { content: '' } },
  choice: {
    label: 'Escolha',
    type: 'choice',
    data: {
      content: '',
      buttons: [
        { id: 'choice-1', label: 'Quero planos', handleId: 'quero_planos', next: '' },
        { id: 'choice-2', label: 'Falar com humano', handleId: 'falar_com_humano', next: '' },
      ],
    },
  },
  condition: { label: 'Condição', type: 'condition', data: { condition: '' } },
  delay: { label: 'Delay', type: 'delay', data: { content: '3' } },
  action: { label: 'Ação', type: 'action', data: { action: '' } },
};

const initialNodes: Node[] = [];
const initialEdges: Edge[] = [];

const safeString = (v?: string | null) => (v ? v : '');
const toHandleId = (value: string, fallback: string) => {
  const normalized = value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return normalized || fallback;
};
const toOptionalHandleId = (value?: string | null) => {
  const normalized = toHandleId(safeString(value), '');
  return normalized || null;
};

const normalizeChoiceButtons = (nodeId: string, buttons: Array<{ id?: string; label?: string; handleId?: string; next?: string }> = []) =>
  buttons.map((button, index) => {
    const defaultLabel = button.label || `Opção ${index + 1}`;
    return {
      id: button.id || `${nodeId}-button-${index + 1}`,
      label: defaultLabel,
      handleId: toHandleId(button.handleId || defaultLabel, `option_${index + 1}`),
      next: button.next || '',
    };
  });

const buildFlowEdge = (edge: FlowEdgePayload): Edge => {
  const label = safeString(edge.label || edge.data?.condition || edge.sourceHandle || edge.data?.sourceHandle);
  const inferredHandle = toOptionalHandleId(edge.sourceHandle || edge.data?.sourceHandle || label);

  return {
    id: safeString(edge.id),
    source: safeString(edge.source),
    target: safeString(edge.target),
    sourceHandle: inferredHandle,
    targetHandle: safeString(edge.targetHandle),
    type: 'default',
    data: {
      condition: label,
      sourceHandle: inferredHandle || undefined,
    },
    label,
  };
};

const hasValidPosition = (node: Node) =>
  Number.isFinite(node.position?.x) && Number.isFinite(node.position?.y);

const getSortedElements = (inputNodes: Node[], inputEdges: Edge[]) => ({
  nodes: [...inputNodes].sort((a, b) => a.id.localeCompare(b.id)),
  edges: [...inputEdges].sort((a, b) =>
    `${a.source}${a.target}`.localeCompare(`${b.source}${b.target}`),
  ),
});

const nextIncrementalId = (prefix: string, existingIds: string[]) => {
  const maxId = existingIds.reduce((max, id) => {
    if (!id.startsWith(prefix)) return max;
    const suffix = Number.parseInt(id.slice(prefix.length), 10);
    if (!Number.isFinite(suffix)) return max;
    return Math.max(max, suffix);
  }, 0);

  return `${prefix}${maxId + 1}`;
};

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
      position: node.position ?? { x: 0, y: 0 },
      data: {
        ...node.data,
        buttons: node.type === 'choice' ? normalizeChoiceButtons(node.id, node.data?.buttons) : node.data?.buttons,
        label: node.data?.label || node.data?.content || `Node ${node.id}`,
        onChange: updateNodeData,
      },
    }),
    [updateNodeData],
  );

  const applyLayoutAndSetFlow = useCallback((nextNodes: Node[], nextEdges: Edge[]) => {
    if (nextNodes.length === 0) {
      setNodes(nextNodes);
      setEdges(nextEdges);
      return;
    }

    const { nodes: sortedNodes, edges: sortedEdges } = getSortedElements(nextNodes, nextEdges);
    const shouldApplyLayout = sortedNodes.some((node) => !hasValidPosition(node));

    if (!shouldApplyLayout) {
      setNodes(sortedNodes);
      setEdges(sortedEdges);
      return;
    }

    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(sortedNodes, sortedEdges);
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [setEdges, setNodes]);

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
        const initialEdges: Edge[] = (data?.edges || []).map(buildFlowEdge);

        applyLayoutAndSetFlow(initialNodes, initialEdges);
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
  }, [applyLayoutAndSetFlow, buildFlowNode, setEdges, setNodes]);

  const isEmpty = useMemo(() => nodes.length === 0 && edges.length === 0, [edges.length, nodes.length]);

  const onConnect = useCallback((params: FlowConnection) => {
    const edgeSourceHandle = toOptionalHandleId(params.sourceHandle);
    const edgeLabel = safeString(params.sourceHandle);
    const edgeBaseId = `${safeString(params.source)}-${edgeSourceHandle || 'default'}-${safeString(params.target)}-${safeString(params.targetHandle) || 'default'}`;

    setEdges((eds) =>
      addEdge(
        {
          id: eds.some((edge) => edge.id === edgeBaseId)
            ? `${edgeBaseId}-${eds.filter((edge) => edge.id.startsWith(edgeBaseId)).length + 1}`
            : edgeBaseId,
          source: safeString(params.source),
          target: safeString(params.target),
          sourceHandle: edgeSourceHandle,
          targetHandle: safeString(params.targetHandle),
          label: edgeLabel,
          data: {
            condition: edgeLabel,
            sourceHandle: edgeSourceHandle || undefined,
          },
          type: 'default',
        },
        eds,
      ),
    );
  }, [setEdges]);

  const addNode = useCallback(
    (kind: FlowNodeKind) => {
      const preset = NODE_PRESETS[kind];
      setNodes((prev) => {
        const nextNodeId = nextIncrementalId('node_', prev.map((node) => node.id));
        const newNode: Node = {
          id: nextNodeId,
          type: preset.type,
          position: { x: 0, y: 0 },
          data: {
            label: preset.label,
            ...preset.data,
            onChange: updateNodeData,
          },
        };

        return [...prev, newNode];
      });
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
        id: safeString(edge.id),
        source: safeString(edge.source),
        target: safeString(edge.target),
        sourceHandle: toOptionalHandleId(
          edge.sourceHandle || (edge.data as FlowEdgePayload['data'])?.sourceHandle || edge.label?.toString(),
        ) || undefined,
        targetHandle: safeString(edge.targetHandle),
        label: safeString(edge.label?.toString() ?? edge.sourceHandle ?? ''),
        data: {
          ...(edge.data as FlowEdgePayload['data']),
          sourceHandle:
            toOptionalHandleId(
              edge.sourceHandle || (edge.data as FlowEdgePayload['data'])?.sourceHandle || edge.label?.toString(),
            ) || undefined,
          condition: safeString(edge.label?.toString() || (edge.data as FlowEdgePayload['data'])?.condition || ''),
        },
      }));

      const result = await saveFlowGraph(tenantId, { nodes: payloadNodes, edges: payloadEdges });
      const savedNodes = (result.nodes || []).map(buildFlowNode);
      const savedEdges = (result.edges || []).map(buildFlowEdge);
      const { nodes: sortedNodes, edges: sortedEdges } = getSortedElements(savedNodes, savedEdges);
      setNodes(sortedNodes);
      setEdges(sortedEdges);
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
