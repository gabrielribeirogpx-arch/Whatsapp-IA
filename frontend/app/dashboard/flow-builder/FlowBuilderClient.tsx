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
import { getFlowGraph, getTenantSessionFromStorage, listFlowVersions, restoreFlowVersion } from '@/lib/api';
import { getLayoutedElements } from '@/lib/autoLayout';
import { orderChoiceChildrenEdges } from '@/lib/flowChoiceOrdering';
import { executeNode } from '@/lib/flowEngine';
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
  const [isEditing] = useState(true);
  const simulationStartedRef = useRef(false);
  const isLoadingFlowRef = useRef(false);
  const lastLoadedFlowIdRef = useRef<string | null>(null);
  const hasTriedAutoCreateRef = useRef(false);
  const nodesRef = useRef<Node[]>([]);

  const getTenantHeaders = useCallback(() => {
    if (typeof window === 'undefined') return {};
    const tenantId = window.localStorage.getItem('tenant_id');
    return tenantId ? { 'X-Tenant-ID': tenantId } : {};
  }, []);

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
    if (typeof window === 'undefined') return;
    if (!selectedFlowId) return;
    window.localStorage.setItem(`flow_draft_${selectedFlowId}`, JSON.stringify({ nodes, edges }));
  }, [edges, nodes, selectedFlowId]);

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
        const API_URL = process.env.NEXT_PUBLIC_API_URL;
        if (!API_URL) return;

        const response = await fetch(`${API_URL}/api/flows`, {
          headers: {
            ...getTenantHeaders(),
          },
        });
        if (!response.ok) {
          throw new Error('Erro ao listar flows');
        }

        const data = await response.json();
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
  }, [getTenantHeaders]);

  const createDefaultFlow = useCallback(async () => {
    const API_URL = process.env.NEXT_PUBLIC_API_URL;
    if (!API_URL) return null;

    try {
      setIsCreatingFlow(true);
      const response = await fetch(`${API_URL}/api/flows`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getTenantHeaders(),
        },
        body: JSON.stringify({
          name: 'Novo Flow',
          nodes: [
            {
              id: 'start',
              type: 'message',
              data: {
                text: 'Digite a mensagem...',
                isStart: true,
              },
            },
          ],
          edges: [],
        }),
      });

      if (!response.ok) {
        throw new Error('Erro ao criar flow base');
      }

      const newFlow = await response.json();
      const safeFlow = newFlow && typeof newFlow.id === 'string' ? newFlow : null;
      if (!safeFlow) return null;

      setFlows((prev) => {
        if (prev.some((flow) => flow.id === safeFlow.id)) return prev;
        return [...prev, safeFlow];
      });
      setSelectedFlowId(safeFlow.id);
      return safeFlow;
    } catch (error) {
      console.error('[FlowBuilder] erro ao criar flow base', error);
      return null;
    } finally {
      setIsCreatingFlow(false);
    }
  }, [getTenantHeaders]);

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
      const API_URL = process.env.NEXT_PUBLIC_API_URL;
      if (!API_URL) {
        setNodes([FALLBACK_START_NODE]);
        setEdges([]);
        return;
      }

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

      const requestPromise = fetch(`${API_URL}/api/flows/${flowId}`, {
        headers: {
          ...getTenantHeaders(),
        },
      }).then(async (res) => {
        if (!res.ok) {
          if (res.status === 404) {
            console.warn('[FlowBuilder] flow não encontrado, resetando estado');
            setSelectedFlowId(null);
            return null;
          }
          throw new Error('Erro ao carregar flow');
        }
        return res.json();
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

      if (typeof window !== 'undefined') {
        const rawDraft = window.localStorage.getItem(`flow_draft_${flowId}`);
        if (rawDraft) {
          try {
            const parsedDraft = JSON.parse(rawDraft) as { nodes?: Node[]; edges?: Edge[] };
            if (Array.isArray(parsedDraft.nodes) && Array.isArray(parsedDraft.edges)) {
              nodesToRender = parsedDraft.nodes;
              edgesToRender = parsedDraft.edges;
            }
          } catch (draftError) {
            console.warn('[FlowBuilder] erro ao restaurar draft local', draftError);
          }
        }
      }

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
  }, [applyLayoutAndSetFlow, buildFlowEdge, buildFlowNode, getTenantHeaders, rfInstance, setEdges, setNodes]);

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

  const runFlowStep = useCallback((startNodeId: string, initialActiveEdgeIds: string[] = [], userMessage?: string, lastUserMsg?: string) => {
    if (!startNodeId) return;

    let currentNodeToRun: string | null = startNodeId;
    let safety = 20;
    const traversedEdgeIds = [...initialActiveEdgeIds];
    const messagesBuffer: Array<{ type: 'bot' | 'user'; text: string }> = [];

    if (userMessage) {
      messagesBuffer.push({ type: 'user', text: userMessage });
    }

    // Contexto com a última mensagem do usuário para avaliação de condições
    const context = { lastUserMessage: lastUserMsg || userMessage || '' };

    while (currentNodeToRun && safety > 0) {
      const response = executeNode(flow, currentNodeToRun, context);
      if (!response || response.type === 'end') break;

      // MENSAGEM normal
      if (response.type === 'message') {
        if (response.text) {
          messagesBuffer.push({ type: 'bot', text: response.text });
        }
        // Bot falou — zera o contexto para que condições seguintes aguardem novo input
        context.lastUserMessage = '';
        if (response.nextNodeId) {
          const nextEdge = flow.edges.find((e) => e.source === currentNodeToRun);
          if (nextEdge?.id) traversedEdgeIds.push(nextEdge.id);
          currentNodeToRun = response.nextNodeId;
          safety--;
          continue;
        }
        // Sem próximo node — busca pela edge
        const nextEdge = flow.edges.find((e) => e.source === currentNodeToRun);
        if (!nextEdge?.target) { currentNodeToRun = null; break; }
        if (nextEdge.id) traversedEdgeIds.push(nextEdge.id);
        currentNodeToRun = nextEdge.target;
        safety--;
        continue;
      }

      // ESCOLHA — para e aguarda input do usuário
      if (response.type === 'choice') {
        if (response.text) {
          messagesBuffer.push({ type: 'bot', text: response.text });
        }
        setMessages((prev) => [...prev, ...messagesBuffer]);
        setActiveEdgeIds(traversedEdgeIds);
        setCurrentNodeId(currentNodeToRun);
        setCurrentChoices(response.buttons || []);
        return;
      }

      // AGUARDANDO INPUT — para o fluxo e espera o usuário digitar
      if (response.type === 'waiting_input') {
        if (messagesBuffer.length > 0) {
          setMessages((prev) => [...prev, ...messagesBuffer]);
        }
        setActiveEdgeIds(traversedEdgeIds);
        setCurrentNodeId(response.nodeId);
        setCurrentChoices([]);
        return;
      }

      // CONDIÇÃO — avalia e segue o caminho correto (true ou false)
      if (response.type === 'condition') {
        const nextId = response.result === 'true' ? response.trueNodeId : response.falseNodeId;
        const handleUsed = response.result;
        const condEdge = flow.edges.find(
          (e) => e.source === currentNodeToRun && (e.sourceHandle === handleUsed || (e.data as any)?.sourceHandle === handleUsed)
        );
        if (condEdge?.id) traversedEdgeIds.push(condEdge.id);
        currentNodeToRun = nextId || null;
        safety--;
        continue;
      }

      // DELAY — mostra indicador "digitando..." e continua após X segundos
      if (response.type === 'delay') {
        const delayMs = Math.min((response.seconds || 3) * 1000, 10000);
        const nextId = response.nextNodeId;
        const delayEdge = flow.edges.find((e) => e.source === currentNodeToRun);
        if (delayEdge?.id) traversedEdgeIds.push(delayEdge.id);

        // Commita mensagens acumuladas antes do delay
        if (messagesBuffer.length > 0) {
          setMessages((prev) => [...prev, ...messagesBuffer]);
          messagesBuffer.length = 0;
        }
        setActiveEdgeIds(traversedEdgeIds);
        setIsTyping(true);

        // Continua o fluxo após o delay
        setTimeout(() => {
          setIsTyping(false);
          if (nextId) {
            runFlowStep(nextId, traversedEdgeIds, undefined, context.lastUserMessage);
          }
        }, delayMs);
        return;
      }

      // AÇÃO — executa silenciosamente e continua o fluxo
      if (response.type === 'action') {
        const nextId = response.nextNodeId;
        const actionEdge = flow.edges.find((e) => e.source === currentNodeToRun);
        if (actionEdge?.id) traversedEdgeIds.push(actionEdge.id);
        currentNodeToRun = nextId || null;
        safety--;
        continue;
      }

      break;
    }

    if (messagesBuffer.length > 0) {
      setMessages((prev) => [...prev, ...messagesBuffer]);
    }
    setActiveEdgeIds(traversedEdgeIds);
  }, [flow, setIsTyping]);

  const handleChoiceClick = useCallback((handleId: string, label: string) => {
    if (!currentNodeId) return;

    const edge = flow.edges.find((item) => item.source === currentNodeId && item.sourceHandle === handleId);
    if (!edge?.target) return;

    setCurrentChoices([]);

    // Adiciona imediatamente a escolha do usuário como bolha no chat
    setMessages((prev) => [...prev, { type: 'user', text: label }]);

    // Continua o fluxo SEM passar userMessage (já foi adicionada acima)
    runFlowStep(edge.target, edge.id ? [edge.id] : [], undefined, label);
  }, [currentNodeId, flow.edges, runFlowStep]);

  const handleUserTextInput = useCallback((text: string) => {
    if (!currentNodeId) {
      setMessages((prev) => [...prev, { type: 'user', text }]);
      return;
    }

    setCurrentChoices([]);
    setMessages((prev) => [...prev, { type: 'user', text }]);

    // Verifica se o node atual é uma condição aguardando input
    const currentNode = flow.nodes.find((n) => n.id === currentNodeId);
    if (currentNode?.type === 'condition') {
      // Reavalia a condição com o texto digitado pelo usuário
      runFlowStep(currentNodeId, [], undefined, text);
      return;
    }

    // Caso contrário, segue para o próximo node
    const nextEdge = flow.edges.find((e) => e.source === currentNodeId);
    if (!nextEdge?.target) return;
    runFlowStep(nextEdge.target, nextEdge.id ? [nextEdge.id] : [], undefined, text);
  }, [currentNodeId, flow.edges, flow.nodes, runFlowStep]);

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

    const API_URL = process.env.NEXT_PUBLIC_API_URL;
    if (!API_URL) {
      console.error('NEXT_PUBLIC_API_URL não configurado');
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

    if (safeFlow.nodes.length < 2 || safeFlow.edges.length < 1) {
      alert('Fluxo inválido');
      return;
    }
    if (requireConfirmOverwrite && !confirm('Você está sobrescrevendo o fluxo atual. Deseja continuar?')) {
      return;
    }
    setFlowValidationError(null);

    console.log('SAVING PAYLOAD:', safeFlow);

    setIsSaving(true);
    try {
      const response = await fetch(`${API_URL}/api/flows/${selectedFlowId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...getTenantHeaders(),
        },
        body: JSON.stringify(safeFlow),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const backendMessage = payload?.detail || payload?.error;
        setFlowValidationError(backendMessage || 'Erro ao salvar fluxo.');
      }
    } catch (error) {
      console.error(error);
      setFlowValidationError('Erro ao salvar fluxo.');
    } finally {
      setIsSaving(false);
    }
  }, [getTenantHeaders, rfInstance, selectedFlowId]);



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
    const API_URL = process.env.NEXT_PUBLIC_API_URL;
    if (!API_URL) return;

    await fetch(`${API_URL}/api/flows/${selectedFlowId}/activate`, {
      method: 'PUT',
      headers: {
        ...getTenantHeaders(),
      },
    });

    setActiveFlowId(selectedFlowId);
    setFlows((prev) => prev.map((flow) => ({ ...flow, is_active: flow.id === selectedFlowId })));
  }, [getTenantHeaders, selectedFlowId]);

  const handleDeactivateFlow = useCallback(async () => {
    const API_URL = process.env.NEXT_PUBLIC_API_URL;
    if (!API_URL) return;

    await fetch(`${API_URL}/api/flows/deactivate`, {
      method: 'POST',
      headers: {
        ...getTenantHeaders(),
      },
    });

    setActiveFlowId(null);
    setFlows((prev) => prev.map((flow) => ({ ...flow, is_active: false })));
  }, [getTenantHeaders]);

  const deleteFlow = useCallback(async () => {
    if (!selectedFlowId) return;
    if (!confirm('Deseja excluir este flow?')) return;
    const API_URL = process.env.NEXT_PUBLIC_API_URL;
    if (!API_URL) return;

    await fetch(`${API_URL}/api/flows/${selectedFlowId}`, {
      method: 'DELETE',
      headers: {
        ...getTenantHeaders(),
      },
    });

    window.location.reload();
  }, [getTenantHeaders, selectedFlowId]);

  const renameFlow = useCallback(async () => {
    if (!selectedFlowId) return;
    const name = prompt('Novo nome do flow:');
    if (!name) return;
    const API_URL = process.env.NEXT_PUBLIC_API_URL;
    if (!API_URL) return;

    await fetch(`${API_URL}/api/flows/${selectedFlowId}/rename`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...getTenantHeaders(),
      },
      body: JSON.stringify({ name }),
    });

    setFlows((prev) => prev.map((flow) => (flow.id === selectedFlowId ? { ...flow, name } : flow)));
  }, [getTenantHeaders, selectedFlowId]);

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

  const decoratedNodes = useMemo(
    () => nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        running: node.id === currentNodeId,
        onToggleStart: toggleStartNode,
      },
    })),
    [currentNodeId, nodes, toggleStartNode],
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
          <select
            value={selectedFlowId || ''}
            onChange={async (e) => {
              const id = e.target.value || null;
              console.log('FLOW SELECIONADO:', id);
              setSelectedFlowId(id);
              await loadFlow(id);
            }}
            style={{
              padding: '6px 10px',
              borderRadius: 8,
              border: '1px solid #d6ddd3',
              background: '#fff',
              minWidth: 220,
            }}
            disabled={normalizedFlows.length === 0}
          >
            <option value="" disabled>
              {normalizedFlows.length === 0 ? 'Nenhum flow disponível' : 'Selecione um flow'}
            </option>
            {normalizedFlows.map((flow) => (
              <option key={flow.id} value={flow.id}>
                {(flow.name || flow.id) + (flow.id === activeFlowId ? ' 🟢' : '')}
              </option>
            ))}
          </select>
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
            className="flow-top-btn"
            onClick={handleActivateFlow}
            disabled={!selectedFlowId}
          >
            Ativar Flow
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
            className="flow-top-btn flow-top-btn-secondary"
            onClick={renameFlow}
            disabled={!selectedFlowId}
          >
            Renomear
          </button>
          <button
            type="button"
            className="flow-top-btn flow-top-btn-danger"
            onClick={deleteFlow}
            disabled={!selectedFlowId}
          >
            Excluir
          </button>
          <button
            type="button"
            className="flow-top-btn flow-top-btn-secondary"
            onClick={openVersionsModal}
            disabled={!selectedFlowId}
          >
            <History size={14} />
            Histórico
          </button>
        </div>
        {!isSimulatorOpen && (
          <button
            type="button"
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
                runFlowStep(startNode.id);
              }
            }}
            style={{
              position: 'absolute',
              top: '14px',
              right: '14px',
              padding: '8px 14px',
              borderRadius: '8px',
              background: '#16A34A',
              color: '#fff',
              border: 'none',
              fontSize: '12px',
              fontWeight: '500',
              cursor: 'pointer',
              boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
              zIndex: 10,
            }}
          >
            ▶ Simular fluxo
          </button>
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

              if (nodes.length > 0) {
                const markedStart = nodes.find((node) => (node.data as { isStart?: boolean }).isStart);
                const incomingTargets = new Set(edges.map((e) => e.target));
                const startNode = markedStart || nodes.find((n) => !incomingTargets.has(n.id)) || nodes[0];
                if (startNode) {
                  simulationStartedRef.current = true;
                  runFlowStep(startNode.id);
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
