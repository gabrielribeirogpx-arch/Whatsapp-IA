'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
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
import { Clock, GitBranch, History, ListChecks, MessageSquare, RotateCcw, Zap } from 'lucide-react';

import ActionNode from '@/components/flow/nodes/ActionNode';
import ChoiceNode from '@/components/flow/nodes/ChoiceNode';
import ConditionNode from '@/components/flow/nodes/ConditionNode';
import DelayNode from '@/components/flow/nodes/DelayNode';
import MessageNode from '@/components/flow/nodes/MessageNode';
import { apiFetch, getFlowGraph, getTenantSessionFromStorage, listFlowVersions, parseApiResponse, restoreFlowVersion } from '@/lib/api';
import { getLayoutedElements } from '@/lib/autoLayout';
import { orderChoiceChildrenEdges } from '@/lib/flowChoiceOrdering';
import { normalizeFlow } from '@/lib/flowNormalization';
import { FlowNodePayload, FlowVersionItem } from '@/lib/types';

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
const FALLBACK_START_NODE: Node = {
  id: 'start',
  type: 'message',
  position: { x: 250, y: 100 },
  data: { label: 'Início', isStart: true },
};

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

const buildFlowEdge = (edge: any): Edge => {
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

type FlowValidationIssue = { code: string; node_id?: string | null; message: string };

type FlowBuilderClientProps = {
  flowId?: string;
};

export default function FlowBuilderClient({ flowId: _initialFlowId }: FlowBuilderClientProps) {
  const searchParams = useSearchParams();
  const urlFlowId = searchParams.get('flow_id') || searchParams.get('flowId') || _initialFlowId || '';
  const [flows, setFlows] = useState<Array<{ id: string; name?: string | null; created_at?: string | null; is_active?: boolean }>>([]);
  const normalizedFlows = useMemo(
    () =>
      flows.map((flow) => ({
        ...flow,
        is_active: !!flow.is_active,
      })),
    [flows],
  );
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(urlFlowId || null);
  const [activeFlowId, setActiveFlowId] = useState<string | null>(null);
  const [isFlowSelectOpen, setIsFlowSelectOpen] = useState(false);
  console.log('FLOW SELECIONADO:', selectedFlowId);
  console.log('FLOW ATIVO:', activeFlowId);
  console.log('FLOWS DISPONÍVEIS:', flows);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [messages, setMessages] = useState<Array<{ type: 'bot' | 'user'; text: string }>>([]);
  const [currentChoices, setCurrentChoices] = useState<Array<{ id?: string; label?: string; handleId?: string }>>([]);
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null);
  const [activeEdgeIds, setActiveEdgeIds] = useState<string[]>([]);
  const [isSimulatorOpen, setIsSimulatorOpen] = useState(false);
  const [isSidebarExpanded, setIsSidebarExpanded] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [userInputText, setUserInputText] = useState('');
  const [isVersionsModalOpen, setIsVersionsModalOpen] = useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [isRestoringVersion, setIsRestoringVersion] = useState(false);
  const [isCreatingFlow, setIsCreatingFlow] = useState(false);
  const [flowVersions, setFlowVersions] = useState<FlowVersionItem[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [flowSource, setFlowSource] = useState<string>('version');
  const [showEmptyFlowWarning, setShowEmptyFlowWarning] = useState(false);
  const [flowValidationError, setFlowValidationError] = useState<string | null>(null);
  const [validationWarnings, setValidationWarnings] = useState<FlowValidationIssue[]>([]);
  const [validationErrors, setValidationErrors] = useState<FlowValidationIssue[]>([]);
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [isEditing] = useState(true);
  const simulationStartedRef = useRef(false);
  const createSimulationSessionId = () => ((typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()));
  const simulationSessionIdRef = useRef<string>(createSimulationSessionId());
  const isLoadingFlowRef = useRef(false);
  const lastLoadedFlowIdRef = useRef<string | null>(null);
  const hasTriedAutoCreateRef = useRef(false);
  const nodesRef = useRef<Node[]>([]);

  const flowSelectRef = useRef<HTMLDivElement | null>(null);
  const selectedFlow = useMemo(
    () => normalizedFlows.find((flow) => flow.id === selectedFlowId) || null,
    [normalizedFlows, selectedFlowId],
  );

  const parseHttpStatus = useCallback((error: unknown): number | null => {
    if (!(error instanceof Error)) return null;
    const match = error.message.match(/HTTP\s+(\d{3})/i);
    return match ? Number(match[1]) : null;
  }, []);

  const logFlowHttpError = useCallback((method: string, endpoint: string, error: unknown) => {
    const tenantPresent = !!getTenantSessionFromStorage()?.tenant_id;
    console.error('[FlowBuilder] Falha HTTP em operação de flow', {
      method,
      endpoint,
      tenantPresent,
      status: parseHttpStatus(error),
      message: error instanceof Error ? error.message : String(error),
    });
  }, [parseHttpStatus]);

  useEffect(() => {
    if (urlFlowId && urlFlowId !== selectedFlowId) {
      setSelectedFlowId(urlFlowId);
      return;
    }
    if (urlFlowId || selectedFlowId) return;
    if (typeof window === 'undefined') return;
    const storedFlowId = window.localStorage.getItem('flow_builder_flow_id');
    if (storedFlowId) {
      setSelectedFlowId(storedFlowId);
    }
  }, [selectedFlowId, urlFlowId]);

  useEffect(() => {
    if (selectedFlowId && !normalizedFlows.find((flow) => flow.id === selectedFlowId)) {
      setSelectedFlowId(null);
      return;
    }

    if (!selectedFlowId && normalizedFlows.length > 0) {
      const currentActiveFlow = normalizedFlows.find((flow) => flow.is_active);
      setSelectedFlowId(currentActiveFlow?.id || normalizedFlows[0].id);
    }
  }, [normalizedFlows, selectedFlowId]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!selectedFlowId) {
      window.localStorage.removeItem('flow_builder_flow_id');
      return;
    }
    window.localStorage.setItem('flow_builder_flow_id', selectedFlowId);
  }, [selectedFlowId]);

  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);


  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      if (!flowSelectRef.current) return;
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;

      if (!flowSelectRef.current.contains(target)) {
        setIsFlowSelectOpen(false);
      }
    };

    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  useEffect(() => {
    console.log('NODES:', nodes);
    console.log('EDGES:', edges);
  }, [edges, nodes]);

  useEffect(() => {
    console.log(
      'FLOW STATUS:',
      normalizedFlows.map((flow) => ({
        name: flow.name,
        active: flow.is_active,
      })),
    );
  }, [normalizedFlows]);

  useEffect(() => {
    let active = true;

    const loadFlows = async () => {
      try {
        const response = await apiFetch('/api/flows', { method: 'GET' });
        const data = await parseApiResponse<Array<{ id: string; name?: string | null; created_at?: string | null; is_active?: boolean }>>(response);
        const safeFlows = Array.isArray(data) ? data : [];
        if (!active) return;
        setFlows(safeFlows);

        const currentActiveFlow = safeFlows.find((flow) => flow.is_active);
        setActiveFlowId(currentActiveFlow?.id || null);
      } catch (error) {
        console.error('[FlowBuilder] erro ao carregar lista de flows', error);
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    };

    void loadFlows();
    return () => {
      active = false;
    };
  }, []);

  const createDefaultFlow = useCallback(async () => {
    try {
      setIsCreatingFlow(true);
      setOperationError(null);
      const response = await apiFetch('/api/flows', {
        method: 'POST',
        body: JSON.stringify({
          name: 'Novo Flow',
          nodes: [],
          edges: [],
        }),
      });

      const newFlow = await parseApiResponse<{ id: string; name?: string | null; created_at?: string | null; is_active?: boolean }>(response);
      const safeFlow = newFlow && typeof newFlow.id === 'string' ? newFlow : null;
      if (!safeFlow) return null;

      setFlows((prev) => {
        if (prev.some((flow) => flow.id === safeFlow.id)) return prev;
        return [...prev, safeFlow];
      });
      setSelectedFlowId(safeFlow.id);
      return safeFlow;
    } catch (error) {
      const status = parseHttpStatus(error);
      logFlowHttpError('POST', '/api/flows', error);
      setOperationError(`Não foi possível criar o flow${status ? ` (HTTP ${status})` : ''}.`);
      return null;
    } finally {
      setIsCreatingFlow(false);
    }
  }, [logFlowHttpError, parseHttpStatus]);

  const handleCreateFlow = useCallback(async () => {
    await createDefaultFlow();
  }, [createDefaultFlow]);

  useEffect(() => {
    if (isLoading) return;
    if (normalizedFlows.length > 0) {
      hasTriedAutoCreateRef.current = false;
      return;
    }
    if (hasTriedAutoCreateRef.current || isCreatingFlow) return;
    hasTriedAutoCreateRef.current = true;
    void createDefaultFlow();
  }, [createDefaultFlow, isCreatingFlow, isLoading, normalizedFlows.length]);

  const formatVersionDate = useCallback((timestamp?: string | null) => {
    if (!timestamp) return 'Sem data';
    const parsed = new Date(timestamp);
    if (Number.isNaN(parsed.getTime())) return 'Sem data';
    return parsed.toLocaleString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }, []);

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

  const toggleStartNode = useCallback((nodeId: string) => {
    setNodes((prev) =>
      prev.map((node) => ({
        ...node,
        data: {
          ...node.data,
          isStart: node.id === nodeId ? !(node.data as { isStart?: boolean }).isStart : false,
        },
      }))
    );
  }, [setNodes]);

  const buildFlowNode = useCallback(
    (node: FlowNodePayload): Node => {
      // DEBUG — remover após confirmar que isStart chega da API
      if (node.data?.isStart) {
        console.log('[buildFlowNode] isStart=true para node:', node.id, node.data);
      }
      return {
        id: node.id,
        type: node.type,
        position: node.position || randomPosition(),
        data: {
          ...node.data,
          isStart: node.data?.isStart ?? false,
          buttons: node.type === 'choice' ? normalizeChoiceButtons(node.id, node.data?.buttons) : node.data?.buttons,
          label: node.data?.label || node.data?.content || `Node ${node.id}`,
          onChange: updateNodeData,
          onToggleStart: toggleStartNode,
        hasValidationError: node.id === highlightedNodeId,
        },
      };
    },
    [toggleStartNode, updateNodeData],
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
    requestAnimationFrame(() => { rfInstance?.fitView(); });
  }, [rfInstance, setEdges, setNodes]);

  const loadFlow = useCallback(async (flowId: string | null) => {
    try {
      if (!flowId) {
        setNodes([FALLBACK_START_NODE]);
        setEdges([]);
        setShowEmptyFlowWarning(false);
        setFlowSource('version');
        return;
      }

      isLoadingFlowRef.current = true;
      setIsLoading(true);
      setNodes([]);
      setEdges([]);
      lastLoadedFlowIdRef.current = flowId;

      const timeoutPromise = new Promise<never>((_, reject) => {
        const timeoutId = setTimeout(() => {
          clearTimeout(timeoutId);
          reject(new Error('Timeout carregando flow'));
        }, FETCH_TIMEOUT_MS);
      });

      const requestPromise = apiFetch(`/api/flows/${flowId}`, { method: 'GET' }).then(async (res) => {
        if (res.status === 404) {
          console.warn('[FlowBuilder] flow não encontrado, resetando estado');
          setSelectedFlowId(null);
          return null;
        }
        return parseApiResponse(res);
      });

      const data = await Promise.race([requestPromise, timeoutPromise]);
      if (!data) {
        setNodes([FALLBACK_START_NODE]);
        setEdges([]);
        setShowEmptyFlowWarning(false);
        setFlowSource('version');
        return;
      }
      const payload = data as {
        id?: string;
        source?: string;
        current_version?: { nodes?: unknown[] | null } | null;
        raw_nodes?: unknown[] | null;
      };
      console.log('FLOW DEBUG:', {
        id: payload?.id,
        version_nodes: Array.isArray(payload?.current_version?.nodes) ? payload.current_version.nodes.length : undefined,
        persisted_nodes: Array.isArray(payload?.raw_nodes) ? payload.raw_nodes.length : undefined,
      });
      const normalizedFlow = normalizeFlow(data);
      console.log('FLOW CARREGADO:', normalizedFlow);
      console.log('FLOW SELECIONADO:', flowId);

      const safeNodes = normalizedFlow.nodes;
      const safeEdges = normalizedFlow.edges;
      setFlowSource(payload?.source || 'version');
      setShowEmptyFlowWarning(!safeNodes || safeNodes.length === 0);
      console.log('NODES RECEBIDOS:', safeNodes);
      console.log('EDGES RECEBIDOS:', safeEdges);

      const formattedNodes: Node[] = safeNodes.map((n: FlowNodePayload) =>
        buildFlowNode({
          ...n,
          id: String(n.id),
          type: n.type || 'default',
          position: n.position || { x: 0, y: 0 },
          data: n.data || {},
        }),
      );

      const formattedEdges: Edge[] = safeEdges.map((e: any) => ({
        ...buildFlowEdge({
          ...e,
          id: String(e.id),
          source: String(e.source),
          target: String(e.target),
          label: e.label || '',
        }),
      }));

      let nodesToRender =
        formattedNodes.length === 0
          ? [FALLBACK_START_NODE]
          : formattedNodes;
      let edgesToRender = formattedEdges;

      console.log('NODES:', nodesToRender);
      console.log('EDGES:', edgesToRender);

      const hasStoredPositions = nodesToRender.some((n) => n.position && (n.position.x !== 0 || n.position.y !== 0));
      if (hasStoredPositions) {
        const orderedEdges = orderChoiceChildrenEdges(nodesToRender, edgesToRender);
        setNodes(nodesToRender);
        setEdges(orderedEdges);
        requestAnimationFrame(() => { rfInstance?.fitView(); });
      } else {
        applyLayoutAndSetFlow(nodesToRender, edgesToRender);
      }
    } catch (err) {
      console.error('Erro ao carregar flow', err);
      setSelectedFlowId(null);
      setNodes([FALLBACK_START_NODE]);
      setEdges([]);
    } finally {
      isLoadingFlowRef.current = false;
      setIsLoading(false);
    }
  }, [applyLayoutAndSetFlow, buildFlowEdge, buildFlowNode, rfInstance, setEdges, setNodes]);

  useEffect(() => {
    if (!flows || flows.length === 0) {
      setSelectedFlowId(null);
      lastLoadedFlowIdRef.current = null;
      setNodes([FALLBACK_START_NODE]);
      setEdges([]);
      return;
    }
    if (!selectedFlowId) return;
    if (lastLoadedFlowIdRef.current === selectedFlowId) return;
    void loadFlow(selectedFlowId);
  }, [flows, loadFlow, selectedFlowId, setEdges, setNodes]);

  const flow = useMemo(
    () => ({
      id: selectedFlowId || null,
      nodes: nodes.map((node) => ({
        id: node.id,
        type: node.type || 'message',
        data: node.data || {},
      })),
      edges,
    }),
    [edges, nodes, selectedFlowId],
  );

  const runFlowStep = useCallback(async (userMessage: string) => {
    if (!selectedFlowId) return;

    try {
      const response = await apiFetch(`/api/flows/${selectedFlowId}/simulate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: simulationSessionIdRef.current, message: userMessage }),
      });

      if (!response.ok) {
        let backendMessage: string | null = null;
        let rawBody = '';

        try {
          const errorJson = await response.json() as { error?: string; detail?: string; type?: string };
          backendMessage = [errorJson.error, errorJson.type, errorJson.detail].filter(Boolean).join(": ") || null;
        } catch {
          rawBody = await response.text();
          backendMessage = rawBody || null;
        }

        const friendlyMessage = backendMessage
          ? `Não foi possível iniciar o simulador: ${backendMessage}`
          : 'Não foi possível iniciar o simulador';
        const statusBadge = `[HTTP ${response.status}]`;

        console.error('[SIMULATOR ERROR]', response.status, backendMessage || rawBody);
        setMessages((prev) => [
          ...prev,
          { type: 'user', text: userMessage },
          { type: 'bot', text: `${statusBadge} ${friendlyMessage}` },
        ]);
        return;
      }

      const data = await parseApiResponse<any>(response);
      const backendMessages = Array.isArray(data?.messages)
        ? data.messages.map((item: unknown) => (typeof item === 'string' ? item.trim() : '')).filter(Boolean)
        : [];
      const fallbackReply = typeof data?.reply === 'string' ? data.reply : '';
      const botMessages = backendMessages.length > 0
        ? backendMessages
        : (fallbackReply ? [fallbackReply] : ['Simulação concluída sem resposta textual.']);
      setMessages((prev) => [
        ...prev,
        { type: 'user', text: userMessage },
        ...botMessages.map((text: string) => ({ type: 'bot' as const, text })),
      ]);
      setCurrentNodeId(data.next_node_id || null);
      setCurrentChoices([]);
      const active = flow.edges
        .filter((e) => e.source === data.current_node_id && data.selected_edge !== null && (e.sourceHandle === data.selected_edge || (e.data as any)?.sourceHandle === data.selected_edge))
        .map((e) => e.id)
        .filter(Boolean) as string[];
      setActiveEdgeIds(active);
    } catch (error) {
      console.error('[SIMULATOR ERROR] failed to fetch', error);
      setMessages((prev) => [...prev, { type: 'user', text: userMessage }, { type: 'bot', text: 'Não foi possível iniciar o simulador' }]);
    }
  }, [flow.edges, selectedFlowId]);

  const handleChoiceClick = useCallback((handleId: string, label: string) => {
    void runFlowStep(label);
  }, [runFlowStep]);

  const handleUserTextInput = useCallback((text: string) => {
    void runFlowStep(text);
  }, [runFlowStep]);

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
      if (!rfInstance) return;

      const preset = NODE_PRESETS[kind];

      // Usa o centro visível atual do viewport do ReactFlow
      // screenToFlowPosition converte coordenadas de tela para coordenadas do flow
      // O canvas ocupa a área entre a sidebar (240px) e o simulador (quando aberto)
      const simWidth = isSimulatorOpen ? 320 : 0;
      const canvasLeft = 240;
      const canvasRight = window.innerWidth - simWidth;
      const canvasCenterScreenX = (canvasLeft + canvasRight) / 2;
      const canvasCenterScreenY = window.innerHeight / 2;

      const flowPosition = rfInstance.screenToFlowPosition({
        x: canvasCenterScreenX,
        y: canvasCenterScreenY,
      });

      const newNode: Node = {
        id: makeNodeId(),
        type: preset.type,
        position: {
          x: flowPosition.x - 120,
          y: flowPosition.y - 70,
        },
        data: {
          label: preset.label,
          ...preset.data,
          onChange: updateNodeData,
          onToggleStart: toggleStartNode,
          hasValidationError: false,
        },
      };

      setNodes((prev) => [...prev, newNode]);
    },
    [rfInstance, isSimulatorOpen, setNodes, toggleStartNode, updateNodeData],
  );

  const handleSaveFlow = useCallback(async (requireConfirmOverwrite = false) => {
    if (!selectedFlowId) {
      console.error('selectedFlowId não definido');
      return;
    }

    if (!rfInstance) {
      console.error('ReactFlow não inicializado');
      return;
    }

    const flow = rfInstance.toObject() as {
      nodes?: Array<{
        id: string;
        type?: string;
        position?: { x: number; y: number };
        data?: Record<string, unknown>;
      }>;
      edges?: Array<Record<string, unknown>>;
    };

    flow.nodes = (flow.nodes || []).map((n) => ({
      ...n,
      id: n.id,
      type: n.type || 'default',
      position: n.position || { x: 0, y: 0 },
      data: {
        ...n.data,
        isStart: !!n.data?.isStart,
      },
    }));

    flow.edges = flow.edges || [];

    const realFlow = rfInstance?.toObject?.() || flow;
    const realFlowNodes = Array.isArray(realFlow.nodes) ? (realFlow.nodes as Node[]) : [];
    const realFlowEdges = Array.isArray(realFlow.edges) ? (realFlow.edges as Edge[]) : [];

    const payloadNodes: FlowNodePayload[] = realFlowNodes.map((node) => {
      const nodeData = node.data || {};
      // Remove funções e campos não serializáveis
      const { onChange, ...cleanData } = nodeData as Record<string, unknown>;

      return {
        id: node.id,
        type: node.type || 'message',
        position: node.position,
        data: cleanData,
      };
    });

    const nodeTypeById = new Map(realFlowNodes.map((node) => [node.id, node.type]));

    const cleanEdges = realFlowEdges
      .filter((edge) => edge.source && edge.target)
      .map((edge) => {
        const sourceNodeType = nodeTypeById.get(edge.source);
        const normalizedSourceHandle =
          sourceNodeType === 'condition'
            ? edge.sourceHandle === 'false'
              ? 'false'
              : 'true'
            : edge.sourceHandle ?? 'default';

        return {
          id: edge.id,
          source: edge.source,
          target: edge.target,
          sourceHandle: normalizedSourceHandle,
          targetHandle: edge.targetHandle ?? 'default',
          type: edge.type ?? 'default',
        };
      });

    const safeFlow = {
      nodes: payloadNodes,
      edges: cleanEdges,
    };

    if (requireConfirmOverwrite && !confirm('Você está sobrescrevendo o fluxo atual. Deseja continuar?')) {
      return;
    }
    setFlowValidationError(null);

    console.log('SAVING PAYLOAD:', safeFlow);

    setIsSaving(true);
    try {
      const response = await apiFetch(`/api/flows/${selectedFlowId}`, {
        method: 'PUT',
        body: JSON.stringify(safeFlow),
      });
      const data = await parseApiResponse<{ validation?: { warnings?: FlowValidationIssue[]; errors?: FlowValidationIssue[] } }>(response);
      setValidationWarnings(data?.validation?.warnings || []);
      setValidationErrors(data?.validation?.errors || []);
    } catch (error) {
      console.error(error);
      const message = error instanceof Error && error.message ? error.message : 'Erro ao salvar fluxo.';
      setFlowValidationError(message);
    } finally {
      setIsSaving(false);
    }
  }, [rfInstance, selectedFlowId]);



  const openVersionsModal = useCallback(async () => {
    if (!selectedFlowId) return;
    setIsVersionsModalOpen(true);
    setIsLoadingVersions(true);
    try {
      const versions = await listFlowVersions(selectedFlowId);
      setFlowVersions(versions);
      setActiveVersionId(versions.find((item) => item.is_current)?.id || null);
    } catch {
      setFlowVersions([]);
    } finally {
      setIsLoadingVersions(false);
    }
  }, [selectedFlowId]);

  const handleActivateFlow = useCallback(async () => {
    if (!selectedFlowId) return;
    if (validationErrors.length > 0) return;
    const response = await apiFetch(`/api/flows/${selectedFlowId}/publish`, { method: 'POST', body: JSON.stringify({}) });
    await parseApiResponse(response);
    const activateResponse = await apiFetch(`/api/flows/${selectedFlowId}/activate`, { method: 'PUT' });
    await parseApiResponse(activateResponse);

    setActiveFlowId(selectedFlowId);
    setFlows((prev) => prev.map((flow) => ({ ...flow, is_active: flow.id === selectedFlowId })));
  }, [selectedFlowId, validationErrors.length]);

  const handleDeactivateFlow = useCallback(async () => {
    const response = await apiFetch('/api/flows/deactivate', {
      method: 'POST',
    });
    await parseApiResponse(response);

    setActiveFlowId(null);
    setFlows((prev) => prev.map((flow) => ({ ...flow, is_active: false })));
  }, []);

  const deleteFlow = useCallback(async () => {
    if (!selectedFlowId) return;
    if (!confirm('Deseja excluir este flow?')) return;
    try {
      setOperationError(null);
      const response = await apiFetch(`/api/flows/${selectedFlowId}`, {
        method: 'DELETE',
      });
      await parseApiResponse(response);

      window.location.reload();
    } catch (error) {
      const endpoint = `/api/flows/${selectedFlowId}`;
      const status = parseHttpStatus(error);
      logFlowHttpError('DELETE', endpoint, error);
      setOperationError(`Não foi possível excluir o flow${status ? ` (HTTP ${status})` : ''}.`);
    }
  }, [logFlowHttpError, parseHttpStatus, selectedFlowId]);

  const renameFlow = useCallback(async () => {
    if (!selectedFlowId) return;
    const name = prompt('Novo nome do flow:');
    if (!name) return;
    const response = await apiFetch(`/api/flows/${selectedFlowId}/rename`, {
      method: 'PUT',
      body: JSON.stringify({ name }),
    });
    await parseApiResponse(response);

    setFlows((prev) => prev.map((flow) => (flow.id === selectedFlowId ? { ...flow, name } : flow)));
  }, [selectedFlowId]);

  const handleRestoreVersion = useCallback(async (versionId: string) => {
    const tenantSession = getTenantSessionFromStorage();
    const tenantId = tenantSession?.tenant_id;
    if (!tenantId || !selectedFlowId) return;

    setIsRestoringVersion(true);
    try {
      await restoreFlowVersion(selectedFlowId, versionId);
      const data = await getFlowGraph(tenantId, selectedFlowId);
      const normalizedFlow = normalizeFlow(data);
      setFlowSource(data.source || 'version');
      setShowEmptyFlowWarning(!normalizedFlow.nodes || normalizedFlow.nodes.length === 0);
      const restoredNodes = normalizedFlow.nodes.map(buildFlowNode);
      const restoredEdges: Edge[] = normalizedFlow.edges.map(buildFlowEdge);
      const orderedEdges = orderChoiceChildrenEdges(restoredNodes, restoredEdges);
      setNodes(restoredNodes);
      setEdges(orderedEdges);
      setActiveVersionId(versionId);
      setFlowVersions((prev) => prev.map((item) => ({ ...item, is_current: item.id === versionId })));
      requestAnimationFrame(() => { rfInstance?.fitView(); });
    } finally {
      setIsRestoringVersion(false);
    }
  }, [buildFlowNode, rfInstance, selectedFlowId, setEdges, setNodes]);

  const focusNodeIssue = useCallback((nodeId?: string | null) => {
    if (!nodeId) return;
    setHighlightedNodeId(nodeId);
    const target = nodesRef.current.find((n) => n.id === nodeId);
    if (target) {
      rfInstance?.setCenter(target.position.x, target.position.y, { zoom: 1.2, duration: 300 });
      console.info('[INVALID NODE HIGHLIGHTED]', nodeId);
    }
  }, [rfInstance]);

  useEffect(() => {
    const first = validationErrors.find((e) => e.node_id);
    if (first?.node_id) focusNodeIssue(first.node_id);
  }, [focusNodeIssue, validationErrors]);

  const decoratedNodes = useMemo(
    () => nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        running: node.id === currentNodeId,
        onToggleStart: toggleStartNode,
        hasValidationError: node.id === highlightedNodeId,
      },
    })),
    [currentNodeId, highlightedNodeId, nodes, toggleStartNode],
  );

  const safeNodes = useMemo(
    () =>
      decoratedNodes.map((node) => ({
        type: node.type || 'default',
        ...node,
      })),
    [decoratedNodes],
  );

  const decoratedEdges = useMemo(
    () =>
      edges.map((edge) => ({
        ...edge,
        className: activeEdgeIds.includes(edge.id) ? 'flow-edge flow-edge-active' : 'flow-edge',
      })),
    [activeEdgeIds, edges],
  );

  // Fecha o menu de contexto ao clicar fora
  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);

  if (isLoading) {
    return <div>Carregando fluxo...</div>;
  }
  return (
    <div className="flow-builder-page" style={{ width: '100%', height: '100vh', display: 'flex' }}>
      <nav
        className="dash-sidebar"
        onMouseEnter={() => setIsSidebarExpanded(true)}
        onMouseLeave={() => setIsSidebarExpanded(false)}
        style={{ zIndex: 20 }}
      >
        <div className="dash-sidebar-logo">
          <img
            src="/Logo.svg"
            alt="Ícone"
            className="logo-icon"
            style={{ display: isSidebarExpanded ? 'none' : 'block' }}
          />
          <img
            src="/Logo2.svg"
            alt="Logo"
            className="logo-full"
            style={{ display: isSidebarExpanded ? 'block' : 'none' }}
          />
        </div>

        <span className="dash-nav-section">Blocos</span>

        <button type="button" className="dash-nav-item" onClick={() => addNode('message')} title="Mensagem" style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
          <MessageSquare size={18} strokeWidth={1.8} className="text-current" />
          <span className="dash-nav-label">Mensagem</span>
        </button>

        <button type="button" className="dash-nav-item" onClick={() => addNode('choice')} title="Escolha" style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
          <ListChecks size={18} strokeWidth={1.8} className="text-current" />
          <span className="dash-nav-label">Escolha</span>
        </button>

        <button type="button" className="dash-nav-item" onClick={() => addNode('condition')} title="Condição" style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
          <GitBranch size={18} strokeWidth={1.8} className="text-current" />
          <span className="dash-nav-label">Condição</span>
        </button>

        <button type="button" className="dash-nav-item" onClick={() => addNode('delay')} title="Delay" style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
          <Clock size={18} strokeWidth={1.8} className="text-current" />
          <span className="dash-nav-label">Delay</span>
        </button>

        <button type="button" className="dash-nav-item" onClick={() => addNode('action')} title="Ação" style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
          <Zap size={18} strokeWidth={1.8} className="text-current" />
          <span className="dash-nav-label">Ação</span>
        </button>

        <div className="dash-nav-divider" />

        <button
          type="button"
          className="dash-nav-item"
          onClick={() => void handleSaveFlow(true)}
          disabled={isSaving}
          title={isEditing ? 'Salvar fluxo' : 'Visualização'}
          style={{ border: 'none', background: 'none', cursor: isSaving ? 'not-allowed' : 'pointer', width: '100%', textAlign: 'left', opacity: isSaving ? 0.6 : 1 }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
            <polyline points="17 21 17 13 7 13 7 21"/>
            <polyline points="7 3 7 8 15 8"/>
          </svg>
          <span className="dash-nav-label">{isSaving ? 'Salvando...' : 'Salvar fluxo'}</span>
        </button>

        <div style={{ marginTop: 'auto' }}>
          <div className="dash-nav-divider" />
          <a href="/dashboard" className="dash-nav-item" title="Dashboard" style={{ textDecoration: 'none' }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
            <span className="dash-nav-label">Voltar</span>
          </a>
        </div>
      </nav>

      {showEmptyFlowWarning && (
        <div style={{ position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)', zIndex: 25, background: '#fef3c7', color: '#92400e', border: '1px solid #f59e0b', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>
          ⚠️ Flow vazio ou inconsistente
        </div>
      )}
      {flowValidationError && (
        <div style={{ position: 'absolute', top: showEmptyFlowWarning ? 50 : 12, right: 16, zIndex: 25, background: '#fef2f2', color: '#b91c1c', border: '1px solid #fca5a5', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>
          {flowValidationError}
        </div>
      )}
      {validationWarnings.length > 0 && (
        <div style={{ position: 'absolute', top: 12, right: 16, zIndex: 25, background: '#fef3c7', color: '#92400e', border: '1px solid #f59e0b', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>
          ⚠️ {validationWarnings[0]?.message}
        </div>
      )}
      {validationErrors.length > 0 && (
        <div style={{ position: 'absolute', top: 50, right: 16, zIndex: 25, background: '#fef2f2', color: '#b91c1c', border: '1px solid #fca5a5', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>
          ❌ {validationErrors[0]?.message}
        </div>
      )}
      {operationError && (
        <div style={{ position: 'absolute', top: showEmptyFlowWarning ? 50 : 12, left: 16, zIndex: 25, background: '#fef2f2', color: '#b91c1c', border: '1px solid #fca5a5', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>
          {operationError}
        </div>
      )}
      {flowSource === 'fallback' && (
        <div style={{ position: 'absolute', top: showEmptyFlowWarning ? 50 : 12, left: '50%', transform: 'translateX(-50%)', zIndex: 25, background: '#eff6ff', color: '#1d4ed8', border: '1px solid #93c5fd', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
          Flow recuperado automaticamente
        </div>
      )}
      <main style={{ flex: 1, background: '#F7F7F5', position: 'relative' }}>
        <div className="flow-builder-top-actions">
          {normalizedFlows.length === 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ color: '#6b7280', fontSize: 14 }}>Nenhum fluxo criado ainda</span>
              <button
                type="button"
                className="flow-top-btn flow-top-btn-secondary"
                onClick={() => {
                  void createDefaultFlow();
                }}
                disabled={isCreatingFlow}
              >
                {isCreatingFlow ? 'Criando...' : 'Criar primeiro fluxo'}
              </button>
            </div>
          )}

          <div className="flow-toolbar-groups">
            <div className="flow-toolbar-section flow-toolbar-left">
              <div className="flow-toolbar-group flow-toolbar-group-select">
                <div className="flow-select-wrapper" ref={flowSelectRef}>
                  <button
                    type="button"
                    className="flow-select-trigger"
                    onClick={() => setIsFlowSelectOpen((prev) => !prev)}
                    disabled={normalizedFlows.length === 0}
                    aria-haspopup="listbox"
                    aria-expanded={isFlowSelectOpen}
                  >
                    <div className="flow-selected-label">
                      <span className="flow-name">
                        {selectedFlow ? (selectedFlow.name || selectedFlow.id) : (normalizedFlows.length === 0 ? 'Nenhum flow disponível' : 'Selecione um flow')}
                      </span>
                      {selectedFlowId && selectedFlowId === activeFlowId && <span className="flow-badge">Ativo</span>}
                    </div>
                  </button>
                  {isFlowSelectOpen && normalizedFlows.length > 0 && (
                    <div className="flow-select-dropdown" role="listbox">
                      {normalizedFlows.map((flow) => (
                        <button
                          key={flow.id}
                          type="button"
                          className="flow-select-option"
                          onClick={async () => {
                            console.log('FLOW SELECIONADO:', flow.id);
                            setSelectedFlowId(flow.id);
                            setIsFlowSelectOpen(false);
                            await loadFlow(flow.id);
                          }}
                        >
                          {flow.name || flow.id}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="flow-toolbar-section flow-toolbar-center">
              <div className="flow-toolbar-group flow-toolbar-group-main">
                <button
                  type="button"
                  className="flow-top-btn flow-top-btn-primary"
                  onClick={handleActivateFlow}
                  disabled={!selectedFlowId || validationErrors.length > 0}
                >
                  Ativar Flow
                </button>
              </div>

              <div className="flow-toolbar-group flow-toolbar-group-secondary">
                <button
                  type="button"
                  className="flow-top-btn flow-top-btn-secondary"
                  onClick={() => {
                    void handleCreateFlow();
                  }}
                  disabled={isCreatingFlow}
                >
                  {isCreatingFlow ? 'Criando...' : '+ Criar novo Flow'}
                </button>
                <button
                  type="button"
                  className="flow-top-btn flow-top-btn-secondary"
                  onClick={handleDeactivateFlow}
                  disabled={!activeFlowId}
                >
                  Desativar Flow
                </button>
                <button
                  type="button"
                  className="flow-top-btn flow-top-btn-neutral"
                  onClick={renameFlow}
                  disabled={!selectedFlowId}
                >
                  Renomear
                </button>
                <button
                  type="button"
                  className="flow-top-btn flow-top-btn-neutral"
                  onClick={openVersionsModal}
                  disabled={!selectedFlowId}
                >
                  <History size={14} />
                  Histórico
                </button>
              </div>

              <div className="flow-toolbar-group flow-toolbar-group-danger">
                <button
                  type="button"
                  className="flow-top-btn flow-top-btn-danger"
                  onClick={deleteFlow}
                  disabled={!selectedFlowId}
                >
                  Excluir
                </button>
              </div>
            </div>

            <div className="flow-toolbar-section flow-toolbar-right">
              {!isSimulatorOpen && (
                <button
                  type="button"
                  className="flow-top-btn flow-top-btn-simulate"
                  onClick={() => {
                    setIsSimulatorOpen(true);
                    if (simulationStartedRef.current || nodes.length === 0) return;

                    simulationStartedRef.current = true;
                    setMessages([]);
                    setCurrentChoices([]);
                    setCurrentNodeId(null);
                    setActiveEdgeIds([]);
                    setIsTyping(false);

                    const markedStart = nodes.find((node) => (node.data as { isStart?: boolean }).isStart);
                    const incomingTargets = new Set(edges.map((edge) => edge.target));
                    const startNode = markedStart || nodes.find((node) => !incomingTargets.has(node.id)) || nodes[0];
                    if (startNode) {
                      void runFlowStep('oi');
                    }
                  }}
                >
                  ▶ Simular fluxo
                </button>
              )}
            </div>
          </div>
        </div>
        {validationErrors.length > 0 && (
          <div style={{ margin: '8px 0', padding: 10, border: '1px solid #fecaca', borderRadius: 8, background: '#fff1f2', maxWidth: 420 }}>
            <strong style={{ fontSize: 12 }}>Problemas do Flow</strong>
            {validationErrors.map((issue, idx) => (
              <div key={`${issue.code}-${idx}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12, marginTop: 6 }}>
                <span>⚠️ {issue.message}</span>
                <button type="button" onClick={() => focusNodeIssue(issue.node_id)} style={{ color: '#b91c1c' }}>Ir para node</button>
              </div>
            ))}
          </div>
        )}
        {/* Menu de contexto — botão direito no canvas */}
        {contextMenu && (
          <div
            onClick={(e) => e.stopPropagation()}
            className="flow-context-menu"
            style={{
              position: 'absolute',
              top: contextMenu.y,
              left: contextMenu.x,
              zIndex: 1000,
              minWidth: 180,
            }}
          >
            <div style={{ fontSize: 10, fontWeight: 700, color: '#a8b0a0', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '4px 8px 2px' }}>
              Adicionar bloco
            </div>
            {([
              { kind: 'message' as FlowNodeKind, label: 'Mensagem', icon: MessageSquare },
              { kind: 'choice' as FlowNodeKind, label: 'Escolha', icon: ListChecks },
              { kind: 'condition' as FlowNodeKind, label: 'Condição', icon: GitBranch },
              { kind: 'delay' as FlowNodeKind, label: 'Delay', icon: Clock },
              { kind: 'action' as FlowNodeKind, label: 'Ação', icon: Zap },
            ]).map(({ kind, label, icon: Icon }) => (
              <button
                key={kind}
                type="button"
                onClick={() => { addNode(kind); setContextMenu(null); }}
                className="flow-context-menu-item flex items-center gap-2 px-3 py-2 rounded-md transition-all duration-150"
              >
                <span className="flow-context-menu-icon">
                  <Icon size={16} strokeWidth={1.8} className="text-current" />
                </span>
                <span className="flow-context-menu-label">{label}</span>
              </button>
            ))}
          </div>
        )}
        <ReactFlow
          key={flow?.id || 'no-flow'}
          onInit={setRfInstance}
          nodes={safeNodes}
          edges={decoratedEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onContextMenu={(e) => {
            e.preventDefault();
            const mainRect = (e.currentTarget as HTMLElement).getBoundingClientRect();
            setContextMenu({ x: e.clientX - mainRect.left, y: e.clientY - mainRect.top });
          }}
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
          minZoom={0.1}
          maxZoom={4}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1.2} color="rgba(22, 163, 74, 0.18)" />
          <MiniMap nodeBorderRadius={8} pannable style={{ background: '#FFFFFF', border: '1px solid #E8E6E0' }} />
          <Controls />
        </ReactFlow>
      </main>
      {isSimulatorOpen && (
        <aside style={{
          width: 320,
          borderLeft: '1px solid #E8E6E0',
          background: '#FFFFFF',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transform: isSimulatorOpen ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 0.25s ease',
        }}>
        {/* Header do simulador */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '14px 16px',
          borderBottom: '1px solid #E8E6E0',
          flexShrink: 0,
        }}>
          <strong style={{ fontSize: 13, color: '#1a1a18' }}>Simulador</strong>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11, fontWeight: 600, color: '#16a34a' }}>
              <div style={{
                width: 6, height: 6, borderRadius: '50%', background: '#16a34a',
                animation: 'blink 1.4s ease infinite',
              }} />
              Ao vivo
            </div>
            <button
              type="button"
              onClick={() => setIsSimulatorOpen(false)}
              style={{
                width: 24,
                height: 24,
                borderRadius: 6,
                border: '1px solid #e5e7eb',
                background: '#fff',
                color: '#4b5563',
                cursor: 'pointer',
                fontSize: 16,
                lineHeight: 1,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              aria-label="Fechar simulador"
            >
              ×
            </button>
          </div>
        </div>

        {/* Área de mensagens com scroll */}
        <div style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
          background: 'linear-gradient(180deg, #f9fafb 0%, #f3f6f4 100%)',
        }}>
          {messages.length === 0 && (
            <div style={{ textAlign: 'center', color: '#a8b0a0', fontSize: 12, marginTop: 32 }}>
              Nenhuma mensagem ainda.<br />Clique em “Simular fluxo” para iniciar.
            </div>
          )}
          {messages.map((message, index) => (
            <div
              key={`${message.type}-${index}`}
              style={{
                alignSelf: message.type === 'user' ? 'flex-end' : 'flex-start',
                background: message.type === 'user' ? '#dcf8c6' : '#FFFFFF',
                padding: '9px 12px',
                borderRadius: message.type === 'user' ? '14px 4px 14px 14px' : '4px 14px 14px 14px',
                maxWidth: '85%',
                fontSize: 12.5,
                lineHeight: 1.55,
                color: message.type === 'user' ? '#14532d' : '#111827',
                fontWeight: message.type === 'user' ? 500 : 400,
                border: message.type === 'user' ? 'none' : '1px solid #e4e8e0',
                boxShadow: message.type === 'user' ? 'none' : '0 1px 4px rgba(0,0,0,0.06)',
              }}
            >
              {message.text}
            </div>
          ))}
          {isTyping && (
            <div className="typing-indicator" style={{ alignSelf: 'flex-start', color: '#6b7280', fontSize: 12 }}>
              digitando...
            </div>
          )}
        </div>

        {/* Botões de escolha */}
        {currentChoices.length > 0 && (
          <div style={{
            padding: '10px 16px 12px',
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            borderTop: '1px solid #f0f4f0',
            flexShrink: 0,
          }}>
            {currentChoices.map((button, buttonIndex) => (
              <button
                key={button.id || `${button.handleId || 'choice'}-${buttonIndex}`}
                type="button"
                onClick={() => handleChoiceClick(button.handleId || '', button.label || button.handleId || `Opção ${buttonIndex + 1}`)}
                disabled={!button.handleId}
                className="flow-simulator-button"
                style={{ justifyContent: 'flex-start', gap: 8 }}
              >
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#16a34a', flexShrink: 0 }} />
                {button.label || button.handleId || `Opção ${buttonIndex + 1}`}
              </button>
            ))}
          </div>
        )}

        {/* Input de texto livre */}
        <div style={{
          padding: '8px 16px',
          borderTop: '1px solid #f0f4f0',
          flexShrink: 0,
          display: 'flex',
          gap: 6,
        }}>
          <input
            type="text"
            value={userInputText}
            onChange={(e) => setUserInputText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && userInputText.trim()) {
                handleUserTextInput(userInputText.trim());
                setUserInputText('');
              }
            }}
            placeholder="Digite uma mensagem..."
            style={{
              flex: 1,
              border: '1px solid #e4e8e0',
              borderRadius: 8,
              padding: '7px 10px',
              fontSize: 12,
              fontFamily: 'inherit',
              outline: 'none',
              color: '#111827',
            }}
          />
          <button
            type="button"
            onClick={() => {
              if (userInputText.trim()) {
                handleUserTextInput(userInputText.trim());
                setUserInputText('');
              }
            }}
            style={{
              background: '#16A34A',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              padding: '7px 12px',
              fontSize: 13,
              cursor: 'pointer',
              fontWeight: 600,
            }}
          >
            ➤
          </button>
        </div>

        {/* Footer */}
        <div style={{ padding: '10px 16px', borderTop: '1px solid #E8E6E0', flexShrink: 0 }}>
          <button
            type="button"
            onClick={() => {
              setMessages([]);
              setCurrentChoices([]);
              setCurrentNodeId(null);
              setActiveEdgeIds([]);
              setIsTyping(false);
              simulationStartedRef.current = false;
              simulationSessionIdRef.current = createSimulationSessionId();

              if (nodes.length > 0) {
                const markedStart = nodes.find((node) => (node.data as { isStart?: boolean }).isStart);
                const incomingTargets = new Set(edges.map((e) => e.target));
                const startNode = markedStart || nodes.find((n) => !incomingTargets.has(n.id)) || nodes[0];
                if (startNode) {
                  simulationStartedRef.current = true;
                  void runFlowStep('oi');
                }
              }
            }}
            style={{
              width: '100%',
              border: '1px solid #e4e8e0',
              background: 'transparent',
              borderRadius: 9,
              padding: '7px',
              fontSize: 12,
              color: '#6b7280',
              cursor: 'pointer',
              fontFamily: 'inherit',
            }}
          >
            ↺ Reiniciar simulação
          </button>
        </div>
        </aside>
      )}
      {isVersionsModalOpen && (
        <div className="flow-versions-backdrop" onClick={() => setIsVersionsModalOpen(false)}>
          <div className="flow-versions-modal" onClick={(event) => event.stopPropagation()}>
            <div className="flow-versions-header">
              <div>
                <h3>Histórico de versões</h3>
                <p>Restaure qualquer snapshot salvo do flow.</p>
              </div>
              <button type="button" onClick={() => setIsVersionsModalOpen(false)}>×</button>
            </div>

            <div className="flow-versions-list">
              {isLoadingVersions && <div className="flow-versions-empty">Carregando versões...</div>}
              {!isLoadingVersions && flowVersions.length === 0 && (
                <div className="flow-versions-empty">Nenhuma versão encontrada.</div>
              )}
              {!isLoadingVersions && flowVersions.map((item) => (
                <div key={item.id} className={`flow-version-row ${item.is_current ? 'is-current' : ''}`}>
                  <div>
                    <strong>Versão {item.version}</strong>
                    <span>{formatVersionDate(item.created_at)}</span>
                  </div>
                  {item.is_current ? (
                    <span className="flow-version-current-pill">Atual</span>
                  ) : (
                    <button
                      type="button"
                      disabled={isRestoringVersion || activeVersionId === item.id}
                      onClick={() => handleRestoreVersion(item.id)}
                    >
                      <RotateCcw size={13} />
                      Restaurar
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
