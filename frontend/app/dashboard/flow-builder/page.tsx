'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactFlow, {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import type { Connection, Edge, Node, ReactFlowInstance } from 'reactflow';
import 'reactflow/dist/style.css';

import ActionNode from '@/components/flow/nodes/ActionNode';
import ChoiceNode from '@/components/flow/nodes/ChoiceNode';
import ConditionNode from '@/components/flow/nodes/ConditionNode';
import DelayNode from '@/components/flow/nodes/DelayNode';
import MessageNode from '@/components/flow/nodes/MessageNode';
import { getFlowGraph, getTenantSessionFromStorage, saveFlowGraph } from '@/lib/api';
import { getLayoutedElements } from '@/lib/autoLayout';
import { orderChoiceChildrenEdges } from '@/lib/flowChoiceOrdering';
import { executeNode } from '@/lib/flowEngine';
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

function randomPosition() {
  return {
    x: Math.floor(Math.random() * 550),
    y: Math.floor(Math.random() * 450),
  };
}


const safeString = (v?: string | null) => (v ? v : '');
const toHandleId = (value: string, fallback: string) => {
  const normalized = value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return normalized || fallback;
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
  const inferredHandle =
    edge.sourceHandle ??
    edge.data?.sourceHandle ??
    edge.data?.condition ??
    edge.label ??
    null;
  const label = safeString(edge.label || inferredHandle);

  return {
    id: safeString(edge.id),
    source: safeString(edge.source),
    target: safeString(edge.target),
    sourceHandle: inferredHandle,
    targetHandle: safeString(edge.targetHandle),
    type: 'default',
    data: {
      condition: label,
      sourceHandle: inferredHandle,
    },
    label,
  };
};

function makeNodeId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

export default function FlowBuilderPage() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [messages, setMessages] = useState<Array<{ type: 'bot' | 'user'; text: string }>>([]);
  const [currentChoices, setCurrentChoices] = useState<Array<{ id?: string; label?: string; handleId?: string }>>([]);
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null);
  const [activeEdgeId, setActiveEdgeId] = useState<string | null>(null);
  const [runningNodeId, setRunningNodeId] = useState<string | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const simulationRunRef = useRef(0);

  const currentNode = useMemo(
    () => nodes.find((node) => node.id === currentNodeId) || null,
    [currentNodeId, nodes],
  );

  const wait = useCallback((ms: number) => new Promise<void>((resolve) => {
    window.setTimeout(() => resolve(), ms);
  }), []);

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

    const orderedEdges = orderChoiceChildrenEdges(nextNodes, nextEdges);
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(nextNodes, orderedEdges);
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
    requestAnimationFrame(() => { reactFlowInstance?.fitView(); });
  }, [reactFlowInstance, setEdges, setNodes]);

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
  const flow = useMemo(
    () => ({
      nodes: nodes.map((node) => ({
        id: node.id,
        type: node.type || 'message',
        data: node.data || {},
      })),
      edges,
    }),
    [edges, nodes],
  );

  const runFlowFromNode = useCallback(async (startNodeId: string, initialActiveEdgeId?: string | null) => {
    if (!startNodeId) return;
    const runId = ++simulationRunRef.current;

    let currentId: string | null = startNodeId;
    let safety = 20;
    const messagesBuffer: Array<{ type: 'bot'; text: string }> = [];

    if (initialActiveEdgeId) {
      setActiveEdgeId(initialActiveEdgeId);
      await wait(420);
      if (runId !== simulationRunRef.current) return;
      setActiveEdgeId(null);
    }

    while (currentId && safety-- > 0) {
      setRunningNodeId(currentId);
      setCurrentNodeId(currentId);
      await wait(300);
      if (runId !== simulationRunRef.current) return;

      const response = executeNode(flow, currentId);
      if (!response) break;

      if ('text' in response && response.text) {
        messagesBuffer.push({ type: 'bot', text: response.text });
      }

      if (response.type === 'choice') {
        setCurrentChoices(response.buttons || []);
        break;
      }

      const nextEdge = flow.edges.find((edge) => edge.source === currentId);
      if (!nextEdge?.target) {
        setCurrentNodeId(null);
        setCurrentChoices([]);
        break;
      }

      if (nextEdge.id) {
        setActiveEdgeId(nextEdge.id);
        await wait(420);
        if (runId !== simulationRunRef.current) return;
        setActiveEdgeId(null);
      }

      currentId = nextEdge.target;
    }

    if (messagesBuffer.length > 0) {
      setMessages((prev) => [...prev, ...messagesBuffer]);
    }

    setRunningNodeId(null);
  }, [flow, wait]);

  useEffect(() => {
    if (nodes.length === 0) {
      setMessages([]);
      setCurrentNodeId(null);
      setActiveEdgeId(null);
      setRunningNodeId(null);
      setIsTyping(false);
      return;
    }

    const incomingTargets = new Set(edges.map((edge) => edge.target));
    const startNode = nodes.find((node) => !incomingTargets.has(node.id)) || nodes[0];
    if (!startNode) return;

    setMessages([]);
    setCurrentChoices([]);
    setCurrentNodeId(null);
    setActiveEdgeId(null);
    setRunningNodeId(null);
    setIsTyping(false);
    void runFlowFromNode(startNode.id);
  }, [edges, nodes, runFlowFromNode]);

  useEffect(() => {
    if (!messages || messages.length === 0) {
      setMessages([
        {
          type: 'bot',
          text: 'Você quer vendas, suporte ou atendimento?',
        },
      ]);
    }
  }, [messages]);

  useEffect(() => {
    console.log('SIMULADOR STATE', {
      messages,
      currentNode,
    });
  }, [currentNode, messages]);

  const handleChoiceClick = useCallback(async (handleId: string, label: string) => {
    if (!currentNodeId || isTyping) return;

    setMessages((prev) => [...prev, { type: 'user', text: label }]);
    const edge = flow.edges.find((item) => item.source === currentNodeId && item.sourceHandle === handleId);
    if (!edge?.target) return;

    setCurrentChoices([]);
    setIsTyping(true);
    await wait(300 + Math.floor(Math.random() * 501));
    setIsTyping(false);
    await runFlowFromNode(edge.target, edge.id || null);
  }, [currentNodeId, flow.edges, isTyping, runFlowFromNode, wait]);

  const onConnect = useCallback((params: FlowConnection) => {
    const sourceHandle = params.sourceHandle?.toString() || null;
    const source = safeString(params.source);
    const target = safeString(params.target);
    const targetHandle = safeString(params.targetHandle);

    setEdges((eds) => addEdge({
      ...params,
      id: `${source}-${target}-${Date.now()}`,
      source,
      target,
      sourceHandle,
      targetHandle,
      label: safeString(sourceHandle),
      type: 'default',
      data: {
        sourceHandle: sourceHandle || undefined,
      },
    }, eds));
  }, [setEdges]);


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
        id: safeString(edge.id),
        source: safeString(edge.source),
        target: safeString(edge.target),
        sourceHandle:
          edge.sourceHandle ||
          (edge.data as FlowEdgePayload['data'])?.sourceHandle ||
          edge.label?.toString() ||
          undefined,
        targetHandle: safeString(edge.targetHandle),
        label: safeString(edge.label?.toString() ?? edge.sourceHandle ?? ''),
        data: {
          ...(edge.data as FlowEdgePayload['data']),
          sourceHandle:
            edge.sourceHandle ||
            (edge.data as FlowEdgePayload['data'])?.sourceHandle ||
            edge.label?.toString() ||
            undefined,
          condition: safeString(edge.label?.toString() || (edge.data as FlowEdgePayload['data'])?.condition || ''),
        },
      }));

      const result = await saveFlowGraph(tenantId, { nodes: payloadNodes, edges: payloadEdges });
      const savedNodes = (result.nodes || []).map(buildFlowNode);
      const savedEdges = (result.edges || []).map(buildFlowEdge);
      applyLayoutAndSetFlow(savedNodes, savedEdges);
    } finally {
      setIsSaving(false);
    }
  }, [applyLayoutAndSetFlow, buildFlowNode, edges, nodes, setEdges, setNodes]);

  const decoratedNodes = useMemo(
    () => nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        running: node.id === runningNodeId,
      },
    })),
    [nodes, runningNodeId],
  );

  const decoratedEdges = useMemo(
    () =>
      edges.map((edge) => ({
        ...edge,
        className: edge.id === activeEdgeId ? 'flow-edge edge-active' : 'flow-edge',
      })),
    [activeEdgeId, edges],
  );

  if (isLoading) {
    return <div>Carregando fluxo...</div>;
  }
  return (
    <div className="flow-builder-page" style={{ width: '100%', height: '100vh', display: 'flex' }}>
      <aside
        style={{ width: 240, borderRight: '1px solid #E8E6E0', padding: 16, display: 'grid', alignContent: 'start', gap: 10, background: '#FFFFFF' }}
      >
        <strong style={{ fontSize: 14 }}>Blocos</strong>
        <button className="flow-sidebar-button" type="button" onClick={() => addNode('message')}>💬 + Mensagem</button>
        <button className="flow-sidebar-button" type="button" onClick={() => addNode('choice')}>🔘 + Escolha</button>
        <button className="flow-sidebar-button" type="button" onClick={() => addNode('condition')}>🧭 + Condição</button>
        <button className="flow-sidebar-button" type="button" onClick={() => addNode('delay')}>⏱️ + Delay</button>
        <button className="flow-sidebar-button" type="button" onClick={() => addNode('action')}>⚡ + Ação</button>
        <hr style={{ borderColor: '#f3f4f6', width: '100%' }} />
        <button className="primary-button" type="button" onClick={saveFlow} disabled={isSaving}>
          {isSaving ? 'Salvando...' : 'Salvar fluxo'}
        </button>
        {isEmpty ? <small>Nenhum node ainda.</small> : null}
      </aside>
      <main style={{ flex: 1, background: '#F7F7F5' }}>
        <ReactFlow
          onInit={setReactFlowInstance}
          nodes={decoratedNodes}
          edges={decoratedEdges}
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
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="rgba(22, 163, 74, 0.18)" />
          <MiniMap nodeBorderRadius={8} pannable style={{ background: '#FFFFFF', border: '1px solid #E8E6E0' }} />
          <Controls />
        </ReactFlow>
      </main>
      <aside className="simulator-container" style={{ width: 320, borderLeft: '1px solid #E8E6E0', padding: 16, background: '#FFFFFF' }}>
        <strong>Simulador</strong>
        <div className="simulator-messages" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {messages.map((message, index) => (
            <div
              key={`${message.type}-${index}`}
              className={message.type === 'bot' ? 'chat-message-bot' : 'chat-message-user'}
              style={{
                alignSelf: message.type === 'user' ? 'flex-end' : 'flex-start',
                background: message.type === 'user' ? '#DCFCE7' : '#FFF',
                padding: 8,
                borderRadius: 12,
                maxWidth: '80%',
                color: message.type === 'user' ? '#166534' : '#111827',
                border: '1px solid #E8E6E0',
              }}
            >
              {message.text}
            </div>
          ))}
          {isTyping ? (
            <div
              className="chat-message-bot"
              style={{
                alignSelf: 'flex-start',
                background: '#FFF',
                padding: 8,
                borderRadius: 12,
                maxWidth: '80%',
                color: '#6B7280',
                border: '1px solid #E8E6E0',
                fontStyle: 'italic',
              }}
            >
              digitando...
            </div>
          ) : null}
        </div>
        {currentChoices.length > 0 ? (
          <div style={{ display: 'grid', gap: 6 }}>
            {currentChoices.map((button, buttonIndex) => (
              <button
                key={button.id || `${button.handleId || 'choice'}-${buttonIndex}`}
                type="button"
                onClick={() => handleChoiceClick(button.handleId || '', button.label || button.handleId || `Opção ${buttonIndex + 1}`)}
                disabled={!button.handleId || isTyping}
                className="flow-simulator-button"
              >
                {button.label || button.handleId || `Opção ${buttonIndex + 1}`}
              </button>
            ))}
          </div>
        ) : null}
      </aside>
    </div>
  );
}
