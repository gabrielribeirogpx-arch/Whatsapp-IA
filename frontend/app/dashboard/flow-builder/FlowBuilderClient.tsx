'use client';

import { FlowBuilderSkeleton } from '@/components/ui/loading';
import { MobileBottomSheet } from '@/components/layout/MobileBottomSheet';
import { buildMobileFlowSequence } from '@/lib/mobileFlowSequence';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import ReactFlow, {
  addEdge,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  useEdgesState,
  useNodesState,
} from 'reactflow';
import type { Connection, Edge, EdgeChange, Node, NodeChange, ReactFlowInstance } from 'reactflow';
import 'reactflow/dist/style.css';
import { BookOpen, CalendarDays, ChevronDown, Clock, ExternalLink, FileDown, FileImage, FileText, GitBranch, HelpCircle, History, ListChecks, MessageSquare, RotateCcw, Sparkles, Tags, Zap, AlertTriangle, ChevronRight, Plus, Save, MoreHorizontal, Play, GitFork } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import ActionNode from '@/components/flow/nodes/ActionNode';
import AiRagNode from '@/components/flow/nodes/AiRagNode';
import AiResponseNode from '@/components/flow/nodes/AiResponseNode';
import AiClassificationNode from '@/components/flow/nodes/AiClassificationNode';
import AiExtractionNode from '@/components/flow/nodes/AiExtractionNode';
import AiSummaryNode from '@/components/flow/nodes/AiSummaryNode';
import AiAgentNode from '@/components/flow/nodes/AiAgentNode';
import AiSupervisorNode from '@/components/flow/nodes/AiSupervisorNode';
import AiSpecializedAgentNode from '@/components/flow/nodes/AiSpecializedAgentNode';
import AiSystemNode from '@/components/flow/nodes/AiSystemNode';
import ChoiceNode from '@/components/flow/nodes/ChoiceNode';
import ConditionNode from '@/components/flow/nodes/ConditionNode';
import CtaUrlNode from '@/components/flow/nodes/CtaUrlNode';
import DelayNode from '@/components/flow/nodes/DelayNode';
import MessageNode from '@/components/flow/nodes/MessageNode';
import MediaNode from '@/components/flow/nodes/MediaNode';
import CreateFlowModal from '@/components/flows/CreateFlowModal';
import AIStoreModal from '@/components/ai-store/AIStoreModal';
import AISystemModal from '@/components/flow/AISystemModal';
import { apiFetch, getFlowAnalytics, getFlowGraph, getTenantSessionFromStorage, listFlowVersions, parseApiResponse, restoreFlowVersion, listFlows } from '@/lib/api';
import { getLayoutedElements } from '@/lib/autoLayout';
import { orderChoiceChildrenEdges } from '@/lib/flowChoiceOrdering';
import { normalizeFlow } from '@/lib/flowNormalization';
import { filterGoogleSheetsTools } from '@/lib/features';
import { FlowAnalytics, FlowEdgePayload, FlowNodePayload, FlowVersionItem } from '@/lib/types';
import { AGENT_SYSTEM_TEMPLATES, ENABLE_AGENT_SYSTEM_TEMPLATES, instantiateAgentSystemTemplate } from '@/lib/agentSystemTemplates';

const FETCH_TIMEOUT_MS = 8000;
const INVALID_UPLOAD_PUBLIC_URL_MESSAGE = 'Upload concluído, mas a URL pública gerada é inválida.';


const nodeTypes = {
  message: MessageNode,
  choice: ChoiceNode,
  condition: ConditionNode,
  delay: DelayNode,
  action: ActionNode,
  media: MediaNode,
  cta_url: CtaUrlNode,
  ai_rag: AiRagNode,
  ai_response: AiResponseNode,
  ai_classification: AiClassificationNode,
  ai_extraction: AiExtractionNode,
  ai_summary: AiSummaryNode,
  ai_agent: AiAgentNode,
  ai_supervisor: AiSupervisorNode,
  ai_dispatcher: AiSpecializedAgentNode,
  ai_greeting: AiSpecializedAgentNode,
  ai_calendar_agent: AiSpecializedAgentNode,
  ai_safe_fallback: AiSpecializedAgentNode,
  ai_system: AiSystemNode,
  cta_link: CtaUrlNode,
  messageNode: MessageNode,
  choiceNode: ChoiceNode,
  conditionNode: ConditionNode,
  delayNode: DelayNode,
  actionNode: ActionNode,
  mediaNode: MediaNode,
  ctaUrlNode: CtaUrlNode,
};

type FlowNodeKind = 'message' | 'choice' | 'condition' | 'delay' | 'action' | 'media' | 'cta_url' | 'ai_rag' | 'ai_response' | 'ai_classification' | 'ai_extraction' | 'ai_summary' | 'ai_agent' | 'ai_supervisor' | 'ai_dispatcher' | 'ai_greeting' | 'ai_calendar_agent' | 'ai_safe_fallback' | 'ai_system';
type FlowConnection = Connection & { sourceHandle?: string | null };
type NodePaletteItem = { kind: FlowNodeKind; label: string; icon: LucideIcon; description?: string };
type NodePaletteGroup = { id: 'communication' | 'ai' | 'logic' | 'actions'; title: string; icon: LucideIcon; nodes: NodePaletteItem[] };

type FlowListOption = { id: string; name?: string | null; created_at?: string | null; is_active?: boolean; status?: string | null; is_published?: boolean | null; published_version_id?: string | null; flow_version_id?: string | null; version_id?: string | null };
type MCPServerOption = { id: string; name?: string | null; is_enabled?: boolean };
type MCPToolOption = { id: string; server_id?: string | null; tool_name?: string | null; display_name?: string | null; description?: string | null; input_schema?: Record<string, unknown> | null; is_enabled?: boolean; server_name?: string | null; metadata?: Record<string, unknown> | null };
type SubflowToolDraft = Record<string, unknown> & {
  tool_id?: string;
  label?: string;
  description?: string;
  flow_id?: string;
  flow_version_id?: string | null;
  input_variable?: string;
  output_variable?: string;
  timeout_seconds?: number;
};

const SUBFLOW_TOOL_ID_PATTERN = /^[A-Za-z0-9_]+$/;

const slugifyToolId = (value: string) =>
  value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_{2,}/g, '_');

const getFlowDisplayName = (flow?: FlowListOption | null) => flow?.name || (flow?.id ? `Fluxo ${flow.id.slice(0, 8)}` : 'Fluxo não selecionado');
const isPublishedFlow = (flow: FlowListOption) => flow.is_published === true || flow.status === 'published' || flow.status === 'active' || flow.is_active === true;
const getPublishedVersionId = (flow: FlowListOption) => flow.published_version_id || flow.flow_version_id || flow.version_id || null;

const AI_SYSTEM_CARDS = [
  {
    id: 'ai_calendar_agent_system',
    icon: '📅',
    title: 'Agenda Inteligente',
    subtitle: 'Atenda pedidos de agenda, consulte disponibilidade e crie compromissos com uma experiência natural no WhatsApp.',
    category: 'Produtividade',
    setupTime: '2 min',
    difficulty: 'Fácil',
    integrations: ['Google Calendar', 'WhatsApp'],
    capabilities: ['Criar eventos', 'Consultar agenda', 'Cancelar compromissos', 'Responder saudações'],
    recommended: true,
    productionReady: true,
    details: 'Sistema com roteamento de intenção, saudação, agente de agenda e resposta segura para casos não reconhecidos.',
  },
  {
    id: 'ai_support_agent_system',
    icon: '💬',
    title: 'Atendimento Inteligente',
    subtitle: 'Organize a primeira resposta, resolva dúvidas frequentes e encaminhe conversas importantes para o time humano.',
    category: 'Atendimento',
    setupTime: '3 min',
    difficulty: 'Fácil',
    integrations: ['WhatsApp', 'Atendimento humano'],
    capabilities: ['Triagem inicial', 'Respostas rápidas', 'Handoff humano', 'Padronização de atendimento'],
    recommended: true,
    productionReady: false,
    details: 'Template inicial para fluxos de suporte e relacionamento com clientes.',
  },
  {
    id: 'ai_sales_agent_system',
    icon: '💼',
    title: 'Comercial Inteligente',
    subtitle: 'Capture oportunidades, qualifique leads e mantenha seu CRM atualizado durante a conversa.',
    category: 'Vendas',
    setupTime: '4 min',
    difficulty: 'Intermediário',
    integrations: ['CRM', 'WhatsApp'],
    capabilities: ['Qualificar leads', 'Registrar interesse', 'Atualizar CRM', 'Priorizar oportunidades'],
    recommended: true,
    productionReady: false,
    details: 'Template comercial preparado para jornadas de prospecção e qualificação.',
  },
  {
    id: 'ai_rag_agent_system',
    icon: '📚',
    title: 'Conhecimento (RAG)',
    subtitle: 'Responda perguntas usando documentos, políticas, conteúdos internos e bases de conhecimento.',
    category: 'Conhecimento',
    setupTime: '5 min',
    difficulty: 'Intermediário',
    integrations: ['Documentos', 'Base de conhecimento'],
    capabilities: ['Buscar respostas', 'Usar documentos', 'Reduzir retrabalho', 'Apoiar suporte'],
    recommended: false,
    productionReady: false,
    details: 'Template inicial para atendimento orientado por conteúdo e consultas a conhecimento.',
  },
  {
    id: 'ai_mcp_advanced_system',
    icon: '🛠',
    title: 'MCP Automation',
    subtitle: 'Conecte ferramentas externas e acione automações para processos operacionais sob demanda.',
    category: 'Automação',
    setupTime: '6 min',
    difficulty: 'Avançado',
    integrations: ['MCP', 'Ferramentas externas'],
    capabilities: ['Executar ferramentas', 'Orquestrar tarefas', 'Conectar sistemas', 'Automatizar rotinas'],
    recommended: false,
    productionReady: false,
    details: 'Template para automações com ferramentas MCP conectadas ao sistema.',
  },
  {
    id: 'ai_custom_system',
    icon: '➕',
    title: 'Sistema Personalizado',
    subtitle: 'Comece com uma estrutura em branco e adapte seu próprio sistema inteligente para o negócio.',
    category: 'Personalizados',
    setupTime: '1 min',
    difficulty: 'Flexível',
    integrations: ['Personalizável'],
    capabilities: ['Partida rápida', 'Arquitetura livre', 'Ajuste por caso de uso', 'Expansão gradual'],
    recommended: false,
    productionReady: false,
    details: 'Opção para criar uma experiência personalizada mantendo o mesmo fluxo de inserção no canvas.',
  },
] as const;

const normalizeFlowHandleId = (value: unknown) => String(value ?? '').trim().toLowerCase();

const toBuilderHandleId = (value: unknown, fallback: string) => {
  const normalized = String(value ?? '').toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return normalized || fallback;
};

const getNodeAvailableHandles = (node: Pick<Node, 'type' | 'data'> | FlowNodePayload) => {
  const data = (node.data || {}) as Record<string, any>;
  const nodeType = String(node.type || 'message');
  const source = new Set(['', 'default']);
  const target = new Set(['', 'default']);

  if (nodeType === 'condition') {
    source.add('true');
    source.add('false');
  } else if (nodeType === 'choice') {
    const choices = Array.isArray(data.buttons) ? data.buttons : Array.isArray(data.options) ? data.options : [];
    choices.forEach((choice: Record<string, unknown>, index: number) => {
      source.add(toBuilderHandleId(choice?.handleId || choice?.handle_id || choice?.value || choice?.id || choice?.label, `option_${index + 1}`));
    });
  }

  return { source, target };
};

const flowHandleExists = (available: Set<string>, handle: unknown) => available.has(normalizeFlowHandleId(handle));

const AI_SYSTEM_INTERNAL_NODE_TYPES = new Set(['ai_dispatcher', 'ai_greeting', 'ai_calendar_agent', 'ai_safe_fallback', 'ai_agent']);
const AI_SYSTEM_EXPANDED_AGENT_ORIGINAL_TYPES = new Set(['ai_dispatcher', 'ai_greeting', 'ai_calendar_agent', 'ai_safe_fallback']);

const isAiSystemInternalNode = (node: Pick<Node, 'type' | 'data'> | FlowNodePayload) => {
  const data = (node.data || {}) as Record<string, unknown>;
  const hasRuntimeParent = !!data.parent_system_id || !!data.system_id || !!data.ai_system_parent_id || !!data.parentSystemId || data.runtime_generated === true;
  const isExpandedAgent = String(node.type || '') === 'ai_agent' && AI_SYSTEM_EXPANDED_AGENT_ORIGINAL_TYPES.has(String(data.original_type || ''));
  return (AI_SYSTEM_INTERNAL_NODE_TYPES.has(String(node.type || '')) && hasRuntimeParent) || isExpandedAgent;
};

const sanitizeAiSystemCanvasGraph = <TNode extends Node | FlowNodePayload, TEdge extends Edge | FlowEdgePayload>(
  nodes: TNode[],
  edges: TEdge[],
) => {
  const systemNodes = nodes.filter((node) => node.type === 'ai_system');
  const systemById = new Map(systemNodes.map((node) => [String(node.id), node]));
  const migratedBySystem = new Map<string, TNode[]>();
  const internalNodeToSystemId = new Map<string, string>();
  const migratedEdgesBySystem = new Map<string, TEdge[]>();
  const removedIds = new Set<string>();

  for (const systemNode of systemNodes) {
    const systemId = String(systemNode.id);
    const data = (systemNode.data || {}) as Record<string, unknown>;
    const internalNodes = Array.isArray(data.internal_nodes) ? data.internal_nodes : [];
    internalNodes.forEach((internalNode) => {
      if (!internalNode || typeof internalNode !== 'object') return;
      const internalId = String((internalNode as { id?: unknown }).id || '');
      if (internalId) internalNodeToSystemId.set(internalId, systemId);
    });
  }

  for (const node of nodes) {
    if (!isAiSystemInternalNode(node)) continue;
    const data = (node.data || {}) as Record<string, unknown>;
    const parentId = String(data.parent_system_id || data.system_id || data.ai_system_parent_id || '');
    if (!parentId || !systemById.has(parentId)) continue;
    removedIds.add(String(node.id));
    internalNodeToSystemId.set(String(node.id), parentId);
    migratedBySystem.set(parentId, [...(migratedBySystem.get(parentId) || []), node]);
  }

  const resolveInternalSystemId = (nodeId: unknown) => {
    const id = String(nodeId || '');
    if (!id) return null;
    if (removedIds.has(id) || internalNodeToSystemId.has(id)) return internalNodeToSystemId.get(id) || null;
    const prefixMatch = Array.from(systemById.keys()).find((systemId) => id.startsWith(`${systemId}__`));
    return prefixMatch || null;
  };

  const sanitizedEdges: TEdge[] = [];
  let removedEdgesCount = 0;

  for (const edge of edges) {
    const sourceSystemId = resolveInternalSystemId(edge.source);
    const targetSystemId = resolveInternalSystemId(edge.target);
    const hasInternalEndpoint = !!sourceSystemId || !!targetSystemId;
    const hasExpandedInternalId = String(edge.source || '').includes('__') || String(edge.target || '').includes('__');

    if (hasInternalEndpoint || hasExpandedInternalId) {
      removedEdgesCount += 1;
      const systemId = sourceSystemId || targetSystemId || Array.from(systemById.keys()).find((id) => String(edge.source || '').startsWith(`${id}__`) || String(edge.target || '').startsWith(`${id}__`));
      if (systemId) migratedEdgesBySystem.set(systemId, [...(migratedEdgesBySystem.get(systemId) || []), edge]);
      continue;
    }

    sanitizedEdges.push(edge);
  }

  const shouldRewriteSystemData = removedIds.size > 0 || migratedEdgesBySystem.size > 0;
  const sanitizedNodes = (!shouldRewriteSystemData ? nodes : nodes
    .filter((node) => !removedIds.has(String(node.id)))
    .map((node) => {
      if (node.type !== 'ai_system') return node;
      const migrated = migratedBySystem.get(String(node.id)) || [];
      const migratedEdges = migratedEdgesBySystem.get(String(node.id)) || [];
      if (!migrated.length && !migratedEdges.length) return node;
      const data = (node.data || {}) as Record<string, unknown>;
      const currentInternalNodes = Array.isArray(data.internal_nodes) ? data.internal_nodes : [];
      const currentIds = new Set(currentInternalNodes.map((internalNode) => String((internalNode as { id?: unknown }).id || '')));
      const currentInternalEdges = Array.isArray(data.internal_edges) ? data.internal_edges : [];
      const currentEdgeIds = new Set(currentInternalEdges.map((internalEdge) => String((internalEdge as { id?: unknown }).id || '')));
      const nextInternalNodes = [
        ...currentInternalNodes,
        ...migrated
          .filter((internalNode) => !currentIds.has(String(internalNode.id)))
          .map((internalNode) => ({
            ...internalNode,
            data: {
              ...((internalNode.data || {}) as Record<string, unknown>),
              parent_system_id: String(node.id),
            },
          })),
      ];
      const nextInternalEdges = [
        ...currentInternalEdges,
        ...migratedEdges.filter((internalEdge) => !currentEdgeIds.has(String(internalEdge.id || `${internalEdge.source}->${internalEdge.target}:${internalEdge.sourceHandle || ''}`))),
      ];
      return { ...node, data: { ...data, internal_nodes: nextInternalNodes, internal_edges: nextInternalEdges } };
    }));

  const nodeById = new Map(sanitizedNodes.map((node) => [String(node.id), node]));
  const validatedEdges = sanitizedEdges.filter((edge) => {
    if (removedIds.has(String(edge.source)) || removedIds.has(String(edge.target))) return false;
    const sourceNode = nodeById.get(String(edge.source));
    const targetNode = nodeById.get(String(edge.target));
    if (!sourceNode || !targetNode) {
      console.warn('FLOW_EDGE_SANITIZED_ORPHAN_NODE', { edge_id: edge.id, source: edge.source, target: edge.target, node_ids: Array.from(nodeById.keys()) });
      return false;
    }
    const sourceHandles = getNodeAvailableHandles(sourceNode).source;
    const targetHandles = getNodeAvailableHandles(targetNode).target;
    if (!flowHandleExists(sourceHandles, edge.sourceHandle ?? (edge.data as any)?.sourceHandle)) {
      console.warn('FLOW_EDGE_SANITIZED_SOURCE_HANDLE', { edge_id: edge.id, source: edge.source, sourceHandle: edge.sourceHandle ?? (edge.data as any)?.sourceHandle, available: Array.from(sourceHandles) });
      return false;
    }
    if (!flowHandleExists(targetHandles, edge.targetHandle ?? (edge.data as any)?.targetHandle)) {
      console.warn('FLOW_EDGE_SANITIZED_TARGET_HANDLE', { edge_id: edge.id, target: edge.target, targetHandle: edge.targetHandle ?? (edge.data as any)?.targetHandle, available: Array.from(targetHandles) });
      return false;
    }
    return true;
  });
  return { nodes: sanitizedNodes, edges: validatedEdges, removedIds, removedEdgesCount };
};


const sanitizeEditorSaveGraph = (nodes: FlowNodePayload[], edges: FlowEdgePayload[]) => {
  const migratedGraph = sanitizeAiSystemCanvasGraph(nodes, edges);
  const blockedIds = new Set<string>(Array.from(migratedGraph.removedIds));
  const editorNodes = (migratedGraph.nodes as FlowNodePayload[]).filter((node) => {
    if (!isAiSystemInternalNode(node)) return true;
    blockedIds.add(String(node.id));
    return false;
  });
  const editorNodeIds = new Set(editorNodes.map((node) => String(node.id)));
  const editorEdges = (migratedGraph.edges as FlowEdgePayload[]).filter(
    (edge) => !blockedIds.has(String(edge.source)) && !blockedIds.has(String(edge.target)) && editorNodeIds.has(String(edge.source)) && editorNodeIds.has(String(edge.target)),
  );
  return { nodes: editorNodes, edges: editorEdges, removedIds: blockedIds };
};


type FlowHydrationSource = 'editor' | 'runtime' | 'published_snapshot' | 'published-snapshot' | 'runtime-inspector' | 'runtime_snapshot' | 'compiled_graph' | 'none' | 'unknown';

const getFlowHydrationStats = (nodes: Array<Pick<Node, 'type' | 'data'> | FlowNodePayload>, edges: Array<Edge | FlowEdgePayload> = []) => ({
  nodes_count: nodes.length,
  edges_count: edges.length,
  contains_ai_system: nodes.some((node) => node.type === 'ai_system'),
  contains_expanded_ai_agents: nodes.some(isAiSystemInternalNode),
});

const logFlowEditorHydrationSource = (
  source: FlowHydrationSource,
  nodes: Array<Pick<Node, 'type' | 'data'> | FlowNodePayload>,
  edges: Array<Edge | FlowEdgePayload>,
  flowId?: string | null,
) => {
  console.info('FLOW_EDITOR_HYDRATE_SOURCE', {
    source,
    flow_id: flowId || null,
    ...getFlowHydrationStats(nodes, edges),
  });
};

const logFlowEditorSetGraph = (
  source: string,
  nodes: Array<Pick<Node, 'type' | 'data'> | FlowNodePayload>,
  edges: Array<Edge | FlowEdgePayload>,
  flowId?: string | null,
) => {
  console.info('FLOW_EDITOR_SET_GRAPH', {
    source,
    flow_id: flowId || null,
    ...getFlowHydrationStats(nodes, edges),
  });
};

const shouldBlockEditorHydrationSource = (source?: string | null) => ['runtime', 'published_snapshot', 'published-snapshot', 'runtime-inspector', 'runtime_snapshot', 'compiled_graph'].includes(String(source || ''));

const logBlockedRuntimeGraphEditorHydration = (
  source: FlowHydrationSource | string,
  nodes: Array<Pick<Node, 'type' | 'data'> | FlowNodePayload>,
  edges: Array<Edge | FlowEdgePayload>,
  flowId?: string | null,
) => {
  console.warn('BLOCKED_RUNTIME_GRAPH_EDITOR_HYDRATION', {
    source,
    flow_id: flowId || null,
    ...getFlowHydrationStats(nodes, edges),
  });
};

const NODE_GROUPS: NodePaletteGroup[] = [
  {
    id: 'communication',
    title: 'Comunicação',
    icon: MessageSquare,
    nodes: [
      { kind: 'message', label: 'Mensagem', icon: MessageSquare },
      { kind: 'media', label: 'Mídia', icon: FileImage },
      { kind: 'cta_url', label: 'CTA / Link', icon: ExternalLink },
    ],
  },
  {
    id: 'ai',
    title: 'Inteligência Artificial',
    icon: Sparkles,
    nodes: [
      {
        kind: 'ai_response',
        label: 'IA Resposta',
        icon: Sparkles,
        description: 'Converse utilizando Inteligência Artificial sem utilizar Base de Conhecimento.',
      },
      {
        kind: 'ai_rag',
        label: 'IA Conhecimento',
        icon: BookOpen,
        description: 'Responde utilizando documentos e base de conhecimento.',
      },
      {
        kind: 'ai_classification',
        label: 'IA Classificação',
        icon: Tags,
        description: 'Classifica automaticamente a intenção da mensagem.',
      },
      {
        kind: 'ai_extraction',
        label: 'IA Extração',
        icon: FileDown,
        description: 'Extrai informações estruturadas da conversa.',
      },
      {
        kind: 'ai_summary',
        label: 'IA Resumo',
        icon: FileText,
        description: 'Resume histórico ou texto para handoff, CRM e notas internas.',
      },
      { kind: 'ai_agent', label: 'IA Agente', icon: Sparkles, description: 'Usa IA para decidir e executar ferramentas permitidas.' },
      { kind: 'ai_supervisor', label: 'Supervisor IA', icon: Sparkles, description: 'Escolhe automaticamente um IA Agente especializado.' },
    ],
  },
  {
    id: 'logic',
    title: 'Lógica',
    icon: GitBranch,
    nodes: [
      { kind: 'choice', label: 'Escolha', icon: ListChecks },
      { kind: 'condition', label: 'Condição', icon: GitBranch },
      { kind: 'delay', label: 'Delay', icon: Clock },
    ],
  },
  {
    id: 'actions',
    title: 'Ações',
    icon: Zap,
    nodes: [
      { kind: 'action', label: 'Ação', icon: Zap },
    ],
  },
];

const NODE_GROUPS_DEFAULT_OPEN: Record<NodePaletteGroup['id'], boolean> = {
  communication: true,
  ai: true,
  logic: true,
  actions: true,
};
type ChoiceConnectDebug = {
  nodeId: string;
  handleId: string | null;
  handleType: string | null;
  optionValue?: string;
  isConnectable?: boolean;
  completed?: boolean;
};


const NOTIFICATION_PRIORITY_OPTIONS = [
  { value: 'low', label: 'Baixa' },
  { value: 'normal', label: 'Normal' },
  { value: 'high', label: 'Alta' },
] as const;

type NotificationPriority = (typeof NOTIFICATION_PRIORITY_OPTIONS)[number]['value'];
const isNotificationPriority = (value: string): value is NotificationPriority => NOTIFICATION_PRIORITY_OPTIONS.some((option) => option.value === value);

const ACTION_TYPE_OPTIONS = [
  { value: 'create_lead', label: 'Criar Lead' },
  { value: 'add_tag', label: 'Adicionar Tag' },
  { value: 'notify_team', label: 'Notificar Equipe' },
  { value: 'create_task', label: 'Criar tarefa' },
  { value: 'transfer_human', label: 'Transferir para Humano' },
  { value: 'set_conversation_mode', label: 'Alterar modo da conversa' },
] as const;

type ActionType = (typeof ACTION_TYPE_OPTIONS)[number]['value'];

const CONVERSATION_MODE_OPTIONS = [
  { value: 'human', label: 'Humano' },
  { value: 'bot', label: 'Bot' },
  { value: 'ai', label: 'IA' },
] as const;

type ConversationMode = (typeof CONVERSATION_MODE_OPTIONS)[number]['value'];
const isConversationMode = (value: string): value is ConversationMode => CONVERSATION_MODE_OPTIONS.some((option) => option.value === value);

const isActionType = (value: string): value is ActionType => ACTION_TYPE_OPTIONS.some((option) => option.value === value);

const NODE_PRESETS: Record<FlowNodeKind, { label: string; type: string; data: Record<string, unknown> }> = {
  message: { label: 'Mensagem', type: 'message', data: { content: '', wait_for_reply: false } },
  choice: {
    label: 'Escolha',
    type: 'choice',
    data: {
      content: '',
      display_mode: 'buttons',
      buttons: [
        { id: 'choice-1', label: 'Quero planos', handleId: 'quero_planos', next: '' },
        { id: 'choice-2', label: 'Falar com humano', handleId: 'falar_com_humano', next: '' },
      ],
    },
  },
  condition: { label: 'Condição', type: 'condition', data: { condition: '' } },
  delay: { label: 'Delay', type: 'delay', data: { seconds: 3, show_typing: false } },
  action: { label: 'Ação', type: 'action', data: { action_type: 'create_lead', action: 'create_lead', params: {} } },
  media: { label: 'Mídia', type: 'media', data: { media_type: 'image', media_url: '', caption: '', filename: '' } },
  cta_url: { label: 'CTA / Link', type: 'cta_url', data: { content: '', text: '', button_text: '', url: '', is_terminal: false } },
  ai_rag: { label: 'IA / RAG', type: 'ai_rag', data: { after_answer_behavior: 'end_flow', instruction: 'Responda como atendente da prefeitura.', question: '{{last_message}}', top_k: 5, use_workspace_ai_settings: true, model_override: '', temperature: 0.2, max_tokens: 1200, knowledge_only: true, memory_enabled: true, memory_max_messages: 10, memory_max_chars: 4000, fallback_message: 'Não encontrei essa informação com segurança na base disponível. Quer que eu encaminhe para um atendente?', is_terminal: false } },
  ai_response: { label: 'IA Resposta', type: 'ai_response', data: { after_answer_behavior: 'end_flow', instruction: 'Responda como atendente.', question: '{{last_message}}', model_override: '', temperature: 0.2, max_tokens: 1200, memory_enabled: true, memory_max_messages: 10, memory_max_chars: 4000 } },
  ai_classification: { label: 'IA Classificação', type: 'ai_classification', data: { instruction: '', input_template: '{{last_message}}', categories: ['financeiro', 'vendas', 'suporte', 'outro'], allow_other: true, confidence_threshold: 0.6, output_variable: 'ai.classification', save_to_contact: false, save_to_lead: false, send_debug_message: false } },
  ai_extraction: { label: 'IA Extração', type: 'ai_extraction', data: { instruction: '', input_template: '{{last_message}}', fields: [{ name: 'nome', type: 'string', description: 'Nome da pessoa' }, { name: 'email', type: 'email', description: 'E-mail' }], include_conversation_history: true, output_variable: 'ai.extraction', save_to_contact: false, save_to_lead: true, send_debug_message: false } },
  ai_summary: { label: 'IA Resumo', type: 'ai_summary', data: { summary_source: 'conversation_history', input_template: '{{last_message}}', instruction: '', summary_format: 'handoff', max_history_messages: 30, max_history_chars: 8000, output_variable: 'ai.summary', send_message: false, continue_on_error: true, model_override: '', temperature: 0.2, max_tokens: 800 } },
  ai_supervisor: { label: 'Supervisor IA', type: 'ai_supervisor', data: { name: 'Supervisor', description: '', supervisor_prompt: 'Escolha o especialista mais adequado para atender a solicitação.', input_template: '{{last_message}}', max_agents: 1, mode: 'single', agent_ids: [], fallback_agent_id: '', memory_max_messages: 10, memory_max_chars: 4000 } },
  ai_dispatcher: { label: 'IA Dispatcher', type: 'ai_dispatcher', data: { instruction: 'Classifique a intenção da mensagem do usuário. Responda apenas com uma intent válida. Não execute ações.', input_template: '{{last_message}}', intents: ['greeting', 'calendar_create', 'calendar_list', 'calendar_delete', 'support_question', 'sales_lead', 'rag_question', 'human_handoff', 'unknown'], allow_mcp_tools: false, allowed_tools: ['responder'], after_agent_behavior: 'continue_to_next' } },
  ai_greeting: { label: 'IA Greeting', type: 'ai_greeting', data: { instruction: 'Você responde saudações de forma curta, humana e natural no WhatsApp.', input_template: '{{last_message}}', allow_mcp_tools: false, allowed_tools: ['responder'], fallback_message: 'Olá! 👋 Como posso ajudar?', after_agent_behavior: 'end_flow' } },
  ai_calendar_agent: { label: 'IA Calendar Agent', type: 'ai_calendar_agent', data: { instruction: 'Você é um agente especializado em agenda. Use Google Calendar apenas quando necessário. Nunca confirme evento sem retorno real da ferramenta. Use o DateResolver determinístico.', input_template: '{{last_message}}', allowed_tools: ['responder', 'chamar_mcp'], allow_mcp_tools: true, mcp_tool_ids: ['google_calendar_create_event', 'google_calendar_list_events', 'google_calendar_delete_event'], max_mcp_calls: 3, use_date_resolver: true, after_agent_behavior: 'end_flow' } },
  ai_safe_fallback: { label: 'IA Fallback Seguro', type: 'ai_safe_fallback', data: { instruction: 'Não consegui entender totalmente. Você quer agendar algo, tirar uma dúvida ou falar com um atendente?', input_template: '{{last_message}}', allow_mcp_tools: false, allowed_tools: ['responder'], fallback_message: 'Não consegui entender totalmente. Você quer agendar algo, tirar uma dúvida ou falar com um atendente?', after_agent_behavior: 'end_flow' } },
  ai_system: { label: 'Sistema IA', type: 'ai_system', data: { name: 'Sistema IA', description: '', system_type: 'custom', collapsed: true, model_override: '', temperature: 0.2, memory_enabled: true, tools: [], integrations: [], language: 'pt-BR', timezone: 'America/Sao_Paulo', logs_enabled: true, global_prompt: '', internal_nodes: [], internal_edges: [], version: '1.0.0', isEnd: true, end: true, terminal: true } },
  ai_agent: { label: 'IA Agente', type: 'ai_agent', data: { instruction: 'Você é um agente de atendimento. Use apenas as ferramentas permitidas.', input_template: '{{last_message}}', allowed_tools: ['responder', 'definir_variavel'], allow_node_tools: false, node_tools: [], max_node_tool_calls: 3, allow_subflow_tools: false, subflow_tools: [], max_subflow_calls: 2, allow_mcp_tools: false, mcp_tool_ids: [], max_mcp_calls: 3, max_steps: 3, use_memory: true, memory_max_messages: 10, memory_max_chars: 4000, model_override: '', temperature: 0.2, max_tokens: 1200, after_agent_behavior: 'wait_same_node', after_answer_behavior: 'wait_same_node', fallback_message: 'Não consegui concluir essa ação agora. Quer que eu encaminhe para um atendente?', webhooks: [] } },
};

const initialNodes: Node[] = [];
const initialEdges: Edge[] = [];
function randomPosition() {
  return {
    x: Math.floor(Math.random() * 550),
    y: Math.floor(Math.random() * 450),
  };
}


const safeString = (v?: unknown) => (typeof v === 'string' ? v : v == null ? '' : String(v));
const toHandleId = (value: string, fallback: string) => {
  const normalized = value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');
  return normalized || fallback;
};

const normalizeChoiceButtons = (nodeId: string, buttons: Array<{ id?: string; label?: string; value?: string; handleId?: string; next?: string }> = []) =>
  buttons.map((button, index) => {
    const defaultLabel = button.label || button.value || `Opção ${index + 1}`;
    const optionValue = button.value || button.label || button.id || defaultLabel;
    return {
      id: button.id || `${nodeId}-button-${index + 1}`,
      label: defaultLabel,
      value: optionValue,
      handleId: toHandleId(button.handleId || optionValue, `option_${index + 1}`),
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

const parseDelaySeconds = (value: unknown): number | undefined => {
  if (value === null || value === undefined || value === '') return undefined;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return undefined;
  return Number.isInteger(parsed) ? parsed : parsed;
};

const normalizeDelayNodePayload = (node: FlowNodePayload): FlowNodePayload => {
  if (node.type !== 'delay') return node;
  const data = (node.data || {}) as Record<string, unknown>;
  const seconds = parseDelaySeconds(
    (node as FlowNodePayload & { seconds?: unknown }).seconds ??
    data.seconds ??
    data.content ??
    data.delay ??
    data.wait_seconds ??
    data.duration,
  );
  const { content, delay, wait_seconds, duration, seconds: _dataSeconds, ...cleanData } = data;
  const nextNode = {
    ...node,
    type: 'delay',
    ...(seconds !== undefined ? { seconds } : {}),
    data: {
      ...cleanData,
      ...(cleanData.isStart ? { isStart: true } : {}),
    },
  };
  if (Object.keys(nextNode.data).length === 0) {
    delete (nextNode as FlowNodePayload & { data?: FlowNodePayload['data'] }).data;
  }
  return nextNode;
};

const serializeFlowGraph = (nodes: Node[], edges: Edge[]) => {
  const sanitizedGraph = sanitizeAiSystemCanvasGraph(nodes, edges);
  const cleanCanvasNodes = sanitizedGraph.nodes;
  const cleanCanvasEdges = sanitizedGraph.edges;
  const payloadNodes: FlowNodePayload[] = cleanCanvasNodes.map((node) => {
    const nodeData = node.data || {};
    const { onChange, onToggleStart, running, hasValidationError, ...cleanData } = nodeData as Record<string, unknown>;

    return normalizeDelayNodePayload({
      id: node.id,
      type: node.type || 'message',
      position: node.position || { x: 0, y: 0 },
      data: {
        ...cleanData,
        isStart: !!cleanData.isStart,
      },
    });
  });

  const nodeIds = new Set(cleanCanvasNodes.map((node) => node.id));
  const nodeTypeById = new Map(cleanCanvasNodes.map((node) => [node.id, node.type]));
  const cleanEdges: FlowEdgePayload[] = cleanCanvasEdges
    .filter((edge) => edge.source && edge.target && nodeIds.has(edge.source) && nodeIds.has(edge.target))
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
        label: safeString(edge.label ?? normalizedSourceHandle),
        data: {
          ...(edge.data || {}),
          condition: edge.data?.condition ?? safeString(edge.label ?? normalizedSourceHandle),
          sourceHandle: normalizedSourceHandle,
        },
      };
    });

  return {
    nodes: payloadNodes,
    edges: cleanEdges,
  };
};

const getFlowGraphSignature = (flow: { nodes: FlowNodePayload[]; edges: FlowEdgePayload[] }) => JSON.stringify({
  nodes: [...flow.nodes].sort((a, b) => String(a.id).localeCompare(String(b.id))),
  edges: [...flow.edges].sort((a, b) => String(a.id || `${a.source}->${a.target}:${a.sourceHandle || ''}`).localeCompare(String(b.id || `${b.source}->${b.target}:${b.sourceHandle || ''}`))),
});

function makeNodeId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }

  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}


const TEMP_ID_PREFIXES = ['template-', 'temp-', 'mock-'];

function flowContainsTemporaryIds(nodes: Array<{ id: string }>, edges: Array<{ id?: string; source: string; target: string }>) {
  const hasTempId = (value: string) => TEMP_ID_PREFIXES.some((prefix) => value.startsWith(prefix));
  return nodes.some((node) => hasTempId(node.id))
    || edges.some((edge) => hasTempId(edge.id || '') || hasTempId(edge.source) || hasTempId(edge.target));
}

type FlowValidationIssue = { code: string; node_id?: string | null; message: string };


type EditorButton = { id?: string; label?: string; handleId?: string; next?: string };
const toText = (value: unknown) => (typeof value === 'string' ? value : value == null ? '' : String(value));
const fieldHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;
const getBuilderNodeKind = (node?: Node | null) => {
  const normalized = String(node?.type || 'message').toLowerCase();
  return normalized === 'cta_link' ? 'cta_url' : normalized;
};
const getBuilderNodeTitle = (node?: Node | null) => NODE_PRESETS[getBuilderNodeKind(node) as FlowNodeKind]?.label || 'Node';
const getMiniMapNodeColor = (type: string) => {
  const normalized = type.toLowerCase();
  if (normalized === 'ai_system') return '#8b5cf6';
  if (normalized === 'message') return '#3b82f6';
  if (normalized === 'media') return '#06b6d4';
  if (normalized === 'cta_url' || normalized === 'cta_link') return '#7c3aed';
  if (normalized === 'ai_classification' || normalized === 'ai_extraction' || normalized === 'ai_summary') return '#06b6d4';
  if (['choice', 'condition', 'delay', 'action'].includes(normalized)) return '#f97316';
  return '#94a3b8';
};


const FLOW_TEMPLATE_VARIABLES = ['{{contact.name}}', '{{contact.phone}}', '{{last_message}}', '{{lead.name}}', '{{today}}', '{{now}}'];


const QUICK_VARIABLES = [
  { icon: '👤', label: 'Nome', value: '{{contact.name}}' },
  { icon: '📞', label: 'Telefone', value: '{{contact.phone}}' },
  { icon: '💬', label: 'Última mensagem', value: '{{last_message}}' },
  { icon: '🏷️', label: 'Lead', value: '{{lead.name}}' },
  { icon: '📅', label: 'Hoje', value: '{{today}}' },
  { icon: '⏰', label: 'Agora', value: '{{now}}' },
] as const;

type VariableInputElement = HTMLInputElement | HTMLTextAreaElement;

function insertVariableAtCursor(
  targetRef: React.RefObject<VariableInputElement>,
  currentValue: string,
  variable: string,
  onChange: (nextValue: string) => void,
) {
  const target = targetRef.current;
  const selectionStart = target?.selectionStart ?? currentValue.length;
  const selectionEnd = target?.selectionEnd ?? selectionStart;
  const nextValue = `${currentValue.slice(0, selectionStart)}${variable}${currentValue.slice(selectionEnd)}`;
  const nextCursorPosition = selectionStart + variable.length;

  onChange(nextValue);

  requestAnimationFrame(() => {
    target?.focus();
    target?.setSelectionRange(nextCursorPosition, nextCursorPosition);
  });
}

function VariableChips({
  targetRef,
  value,
  onChange,
}: {
  targetRef: React.RefObject<VariableInputElement>;
  value: string;
  onChange: (nextValue: string) => void;
}) {
  return (
    <div className="flow-variable-chips" aria-label="Variáveis rápidas">
      <span>Variáveis rápidas</span>
      <div className="flow-variable-chip-list">
        {QUICK_VARIABLES.map((variable) => (
          <button
            key={variable.value}
            type="button"
            title={variable.value}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => insertVariableAtCursor(targetRef, value, variable.value, onChange)}
          >
            {variable.icon} {variable.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function FlowVariablesHelp({ onClose }: { onClose: () => void }) {
  return (
    <div className="flow-editor-variables-popover" role="dialog" aria-label="Variáveis disponíveis">
      <div className="flow-editor-variables-popover-header">
        <strong>Variáveis disponíveis</strong>
        <button type="button" onClick={onClose} aria-label="Fechar ajuda de variáveis">×</button>
      </div>
      <div className="flow-editor-variable-list">
        {FLOW_TEMPLATE_VARIABLES.map((variable) => (
          <code key={variable}>{variable}</code>
        ))}
      </div>
      <small>Variáveis serão preenchidas quando o fluxo rodar.</small>
    </div>
  );
}

function FlowNodeEditorPanel({
  node,
  draft,
  onDraftChange,
  onClose,
  onUpload,
  isUploading,
  uploadError,
  flows,
  currentFlowId,
  allNodes,
  mcpTools,
}: {
  node: Node | null;
  draft: Record<string, unknown>;
  onDraftChange: (patch: Record<string, unknown>) => void;
  onClose: () => void;
  onUpload: (file: File | null, mediaType: 'image' | 'document' | 'audio' | 'video') => void;
  isUploading: boolean;
  uploadError: string | null;
  flows: FlowListOption[];
  currentFlowId: string | null;
  allNodes: Node[];
  mcpTools: MCPToolOption[];
}) {
  const messageContentRef = useRef<HTMLTextAreaElement>(null);
  const ctaTextRef = useRef<HTMLTextAreaElement>(null);
  const ctaButtonTextRef = useRef<HTMLInputElement>(null);
  const ctaUrlRef = useRef<HTMLInputElement>(null);
  const mediaUrlRef = useRef<HTMLInputElement>(null);
  const mediaCaptionRef = useRef<HTMLTextAreaElement>(null);
  const mediaFilenameRef = useRef<HTMLInputElement>(null);
  const notificationTitleRef = useRef<HTMLInputElement>(null);
  const notificationMessageRef = useRef<HTMLTextAreaElement>(null);
  const taskTitleRef = useRef<HTMLInputElement>(null);
  const taskDescriptionRef = useRef<HTMLTextAreaElement>(null);
  const taskAssigneeRef = useRef<HTMLInputElement>(null);
  const transferReasonRef = useRef<HTMLInputElement>(null);
  const [showVariablesHelp, setShowVariablesHelp] = useState(false);
  const [agentSearch, setAgentSearch] = useState('');
  const [agentAdvancedView, setAgentAdvancedView] = useState(false);
  const [agentQuickAddOpen, setAgentQuickAddOpen] = useState(false);
  const [agentDrawerItem, setAgentDrawerItem] = useState<{ title: string; icon: string; description: string; config?: unknown; variables?: string; limits?: string } | null>(null);

  useEffect(() => {
    setShowVariablesHelp(false);
  }, [node?.id]);

  if (!node) return null;
  const kind = getBuilderNodeKind(node);
  const title = getBuilderNodeTitle(node);
  const displayMode = toText(draft.display_mode || 'buttons') === 'list' ? 'list' : 'buttons';
  const buttons = ((draft.buttons as EditorButton[] | undefined) || []).slice(0, displayMode === 'buttons' ? 3 : undefined);
  const updateButton = (index: number, label: string) => {
    const next = [...buttons];
    next[index] = { ...next[index], label, handleId: fieldHandleId(label, `option_${index + 1}`) };
    onDraftChange({ buttons: next });
  };
  const addButton = () => {
    const nextIndex = buttons.length + 1;
    if (displayMode === 'buttons' && buttons.length >= 3) return;
    onDraftChange({ buttons: [...buttons, { id: `${node.id}-button-${nextIndex}`, label: `Opção ${nextIndex}`, handleId: `option_${nextIndex}` }] });
  };
  const supportsVariables = ['message', 'choice', 'media', 'cta_url', 'condition', 'action', 'ai_rag', 'ai_response', 'ai_classification', 'ai_extraction', 'ai_summary', 'ai_agent', 'ai_supervisor', 'ai_system'].includes(kind);
  const isAiSystem = kind === 'ai_system';
  const publishedSubflowOptions = flows.filter((flow) => flow.id !== currentFlowId && isPublishedFlow(flow));
  const subflowTools = Array.isArray(draft.subflow_tools) ? (draft.subflow_tools as SubflowToolDraft[]) : [];
  const subflowToolIds = subflowTools.map((tool) => toText(tool.tool_id).trim());
  const subflowErrors = subflowTools.flatMap((tool, index) => {
    const errors: string[] = [];
    const toolId = toText(tool.tool_id).trim();
    if (!toolId) errors.push(`Subflow ${index + 1}: tool_id obrigatório.`);
    if (toolId && !SUBFLOW_TOOL_ID_PATTERN.test(toolId)) errors.push(`Subflow ${index + 1}: tool_id aceita apenas letras, números e underscore.`);
    if (toolId && subflowToolIds.filter((id) => id === toolId).length > 1) errors.push(`Subflow ${index + 1}: tool_id duplicado.`);
    if (!toText(tool.flow_id).trim()) errors.push(`Subflow ${index + 1}: selecione um fluxo publicado.`);
    if (toText(tool.label).length > 80) errors.push(`Subflow ${index + 1}: nome da ferramenta deve ter no máximo 80 caracteres.`);
    if (toText(tool.description).length > 300) errors.push(`Subflow ${index + 1}: descrição deve ter no máximo 300 caracteres.`);
    const timeout = Number(tool.timeout_seconds || 20);
    if (timeout < 3 || timeout > 60) errors.push(`Subflow ${index + 1}: timeout deve ficar entre 3 e 60 segundos.`);
    return errors;
  });
  if (draft.allow_subflow_tools === true && subflowTools.length === 0) subflowErrors.push('Ative pelo menos 1 subflow ou desative esta opção.');
  const maxSubflowCalls = Number(draft.max_subflow_calls || 2);
  if (maxSubflowCalls < 1 || maxSubflowCalls > 3) subflowErrors.push('Limite de chamadas deve ficar entre 1 e 3.');
  const updateSubflowTool = (index: number, patch: Partial<SubflowToolDraft>) => {
    const next = [...subflowTools];
    next[index] = { ...next[index], ...patch };
    onDraftChange({ subflow_tools: next });
  };
  const addSubflowTool = () => {
    const flow = publishedSubflowOptions[0];
    const baseLabel = flow ? getFlowDisplayName(flow) : 'Nova ferramenta';
    const toolId = slugifyToolId(baseLabel) || `subflow_${subflowTools.length + 1}`;
    onDraftChange({
      allow_subflow_tools: true,
      subflow_tools: [
        ...subflowTools,
        {
          tool_id: toolId,
          label: baseLabel.slice(0, 80),
          description: '',
          flow_id: flow?.id || '',
          ...(flow ? { flow_version_id: getPublishedVersionId(flow) } : {}),
          input_variable: 'agent.subflow_input',
          output_variable: `agent.subflows.${toolId}.output`,
          timeout_seconds: 20,
        },
      ],
    });
  };
  const agentToolCatalog = [
    { id: 'responder', icon: '💬', name: 'Responder', description: 'Permite responder o usuário.' },
    { id: 'definir_variavel', icon: '🏷️', name: 'Definir variável', description: 'Salva informações no contexto.' },
    { id: 'chamar_webhook', icon: '🔗', name: 'Chamar webhook', description: 'Executa integrações HTTP autorizadas.' },
    { id: 'criar_evento', icon: '📅', name: 'Criar evento', description: 'Agenda eventos quando disponível.' },
    { id: 'consultar_crm', icon: '👤', name: 'Consultar CRM', description: 'Consulta dados do cliente.' },
    { id: 'criar_pedido', icon: '🛒', name: 'Criar pedido', description: 'Cria pedidos em sistemas conectados.' },
    { id: 'enviar_email', icon: '📧', name: 'Enviar Email', description: 'Permite disparar e-mails.' },
    { id: 'transferir_humano', icon: '🙋', name: 'Transferir para humano', description: 'Encaminha para atendimento humano.' },
  ];
  const allowedTools = Array.isArray(draft.allowed_tools) ? draft.allowed_tools.map(String) : ['responder', 'definir_variavel'];
  const nodeTools = Array.isArray(draft.node_tools) ? (draft.node_tools as Array<Record<string, unknown>>) : [];
  const allowedNodeKinds = new Set(['ai_response', 'ai_rag', 'ai_classification', 'ai_extraction', 'ai_summary', 'message', 'action']);
  const nodeToolOptions = allNodes.filter((item) => item.id !== node.id && allowedNodeKinds.has(getBuilderNodeKind(item)));
  const addNodeTool = () => {
    const selected = nodeToolOptions.find((item) => !nodeTools.some((tool) => toText(tool.node_id) === item.id)) || nodeToolOptions[0];
    if (!selected) return;
    const label = getBuilderNodeTitle(selected);
    const toolId = slugifyToolId(label) || `node_tool_${nodeTools.length + 1}`;
    onDraftChange({ allow_node_tools: true, node_tools: [...nodeTools, { tool_id: toolId, node_id: selected.id, label, description: `Executa o bloco ${label}.`, pass_context: true }] });
  };
  const updateNodeTool = (index: number, patch: Record<string, unknown>) => { const next = [...nodeTools]; next[index] = { ...next[index], ...patch }; onDraftChange({ node_tools: next }); };
  const nodeToolIds = nodeTools.map((tool) => toText(tool.tool_id).trim());
  const nodeToolErrors = nodeTools.flatMap((tool, index) => { const errors: string[] = []; const toolId = toText(tool.tool_id).trim(); if (!toolId) errors.push(`Ferramenta ${index + 1}: tool_id obrigatório.`); if (toolId && !SUBFLOW_TOOL_ID_PATTERN.test(toolId)) errors.push(`Ferramenta ${index + 1}: tool_id aceita apenas letras, números e underscore.`); if (toolId && nodeToolIds.filter((id) => id === toolId).length > 1) errors.push(`Ferramenta ${index + 1}: tool_id duplicado.`); if (!toText(tool.label).trim()) errors.push(`Ferramenta ${index + 1}: label obrigatório.`); if (!toText(tool.description).trim()) errors.push(`Ferramenta ${index + 1}: descrição obrigatória.`); return errors; });
  const modelUsesGlobal = !toText(draft.model_override).trim();
  const modelLabel = modelUsesGlobal ? 'Configuração global' : toText(draft.model_override);
  const webhooks = Array.isArray(draft.webhooks) ? (draft.webhooks as Array<Record<string, unknown>>) : [];
  const mcpToolIds = Array.isArray(draft.mcp_tool_ids) ? draft.mcp_tool_ids.map(String) : [];
  const activeMcpTools = filterGoogleSheetsTools(mcpTools).filter((tool) => tool.is_enabled !== false);
  const selectedMcpTools = activeMcpTools.filter((tool) => mcpToolIds.includes(tool.id));
  const addMcpTool = (toolId: string) => { if (!toolId) return; onDraftChange({ allow_mcp_tools: true, mcp_tool_ids: Array.from(new Set([...mcpToolIds, toolId])), allowed_tools: Array.from(new Set([...allowedTools, 'chamar_mcp'])) }); };
  const removeMcpTool = (toolId: string) => { const nextIds = mcpToolIds.filter((id) => id !== toolId); onDraftChange({ allow_mcp_tools: nextIds.length > 0, mcp_tool_ids: nextIds }); };
  const agentFilter = agentSearch.trim().toLowerCase();
  const matchesAgentFilter = (...values: string[]) => !agentFilter || values.some((value) => value.toLowerCase().includes(agentFilter));
  const enabledAgentTools = agentToolCatalog.filter((tool) => allowedTools.includes(tool.id));
  const filteredAgentTools = enabledAgentTools.filter((tool) => matchesAgentFilter(tool.name, tool.id, tool.description));
  const filteredNodeTools = nodeTools.filter((tool) => matchesAgentFilter(toText(tool.label), toText(tool.tool_id), toText(tool.description)));
  const filteredSubflowTools = subflowTools.filter((tool) => matchesAgentFilter(toText(tool.label), toText(tool.tool_id), toText(tool.description)));
  const filteredWebhooks = webhooks.filter((webhook) => matchesAgentFilter(toText(webhook.name || webhook.label || webhook.webhook_id), toText(webhook.webhook_id), toText(webhook.description)));
  const filteredMcpTools = selectedMcpTools.filter((tool) => matchesAgentFilter(toText(tool.display_name || tool.tool_name), tool.id, toText(tool.description), toText(tool.server_name)));
  const complexityScore = allowedTools.length + nodeTools.length + subflowTools.length * 2 + webhooks.length + selectedMcpTools.length;
  const complexity = complexityScore >= 8 ? { label: 'Avançado', tone: 'danger' } : complexityScore >= 4 ? { label: 'Intermediário', tone: 'warning' } : { label: 'Agente simples', tone: 'success' };


  return (
    <aside className="flow-node-editor-panel">
      <div className="flow-node-editor-header">
        <div>
          <span className="flow-node-editor-kicker">{isAiSystem ? 'Editar AI System' : 'Editar bloco'}</span>
          <h3>{title}</h3>
        </div>
        <div className="flow-node-editor-actions">
          {supportsVariables ? (
            <button
              type="button"
              className="flow-node-editor-help-button"
              onClick={() => setShowVariablesHelp((current) => !current)}
              aria-expanded={showVariablesHelp}
            >
              <HelpCircle size={14} /> Variáveis disponíveis
            </button>
          ) : null}
          <button type="button" className="flow-node-editor-close-button" onClick={onClose} aria-label="Fechar painel">×</button>
        </div>
      </div>
      {showVariablesHelp && supportsVariables ? <FlowVariablesHelp onClose={() => setShowVariablesHelp(false)} /> : null}

      <div className="flow-node-editor-content">
        {isAiSystem ? (
          <section className="flow-editor-tab-section flow-editor-system-panel"><h4>Sistema</h4><label className="flow-editor-field">Nome<input value={toText(draft.name || draft.label)} onChange={(event) => onDraftChange({ name: event.target.value, label: event.target.value })} /></label><label className="flow-editor-field">Descrição<textarea value={toText(draft.description)} onChange={(event) => onDraftChange({ description: event.target.value })} /></label><div className="flow-editor-panel-divider" /><h4>IA</h4><div className="flow-editor-row"><label className="flow-editor-field">Modelo<input value={toText(draft.model_override)} onChange={(event) => onDraftChange({ model_override: event.target.value })} placeholder="Configuração global" /></label><label className="flow-editor-field">Temperatura<input type="number" step="0.1" min="0" max="2" value={toText(draft.temperature ?? 0.2)} onChange={(event) => onDraftChange({ temperature: Number(event.target.value || 0.2) })} /></label></div><label className="flow-editor-field">Idioma<input value={toText(draft.language || 'pt-BR')} onChange={(event) => onDraftChange({ language: event.target.value })} /></label><div className="flow-editor-panel-divider" /><h4>Integrações</h4><label className="flow-editor-field">Google Calendar<input value={(Array.isArray(draft.integrations) ? draft.integrations : []).map(String).join(', ')} onChange={(event) => onDraftChange({ integrations: event.target.value.split(',').map((item) => item.trim()).filter(Boolean) })} /></label><div className="flow-editor-panel-divider" /><h4>Memória</h4><label className="flow-editor-radio"><input type="checkbox" checked={draft.memory_enabled !== false} onChange={(event) => onDraftChange({ memory_enabled: event.target.checked })} />Long Memory</label><div className="flow-editor-panel-divider" /><h4>Observabilidade</h4><label className="flow-editor-radio"><input type="checkbox" checked={draft.logs_enabled !== false} onChange={(event) => onDraftChange({ logs_enabled: event.target.checked })} />Logs</label><label className="flow-editor-radio flow-editor-disabled"><input type="checkbox" disabled />Tracing</label><label className="flow-editor-radio flow-editor-disabled"><input type="checkbox" disabled />Replay</label><div className="flow-editor-panel-divider" /><h4>Prompt Global</h4><label className="flow-editor-field"><textarea value={toText(draft.global_prompt)} onChange={(event) => onDraftChange({ global_prompt: event.target.value })} /></label></section>
        ) : <div className="flow-editor-info-card" title="Use isto para definir o objetivo do fluxo. Ex: lead qualificado, fatura acessada, pedido criado, atendimento encaminhado.">
          <label className="flow-editor-radio">
            <input
              type="checkbox"
              checked={draft.is_conversion === true}
              onChange={(event) => onDraftChange({ is_conversion: event.target.checked, ...(event.target.checked ? {} : { conversion_label: '' }) })}
            />
            Marcar como conversão do fluxo
          </label>
          <small>Use isto para definir o objetivo do fluxo. Ex: lead qualificado, fatura acessada, pedido criado, atendimento encaminhado.</small>
          {draft.is_conversion === true ? (
            <label className="flow-editor-field">
              Label da conversão (opcional)
              <input value={toText(draft.conversion_label)} onChange={(event) => onDraftChange({ conversion_label: event.target.value })} placeholder="Ex.: Lead qualificado" />
            </label>
          ) : null}
        </div>}
        {kind === 'message' && (
          <>
            <label className="flow-editor-field">
              Mensagem
              <textarea ref={messageContentRef} value={toText(draft.content)} onChange={(event) => onDraftChange({ content: event.target.value })} placeholder="Digite a mensagem..." />
              <VariableChips targetRef={messageContentRef} value={toText(draft.content)} onChange={(next) => onDraftChange({ content: next })} />
            </label>
            <label className="flow-editor-radio">
              <input
                type="checkbox"
                checked={draft.wait_for_reply === true}
                onChange={(event) => onDraftChange({ wait_for_reply: event.target.checked })}
              />
              Aguardar resposta antes de continuar
            </label>
            <small>Quando marcado, o fluxo envia esta mensagem e só avança para o próximo bloco após a próxima resposta do usuário.</small>
          </>
        )}

        {kind === 'choice' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> Decisão WhatsApp <span>CHOICE</span></div>
            <fieldset className="flow-editor-field">
              <legend>Tipo de exibição</legend>
              <label className="flow-editor-radio">
                <input type="radio" name={`display-mode-${node.id}`} checked={displayMode === 'buttons'} onChange={() => onDraftChange({ display_mode: 'buttons' })} />
                Botões WhatsApp
              </label>
              <label className="flow-editor-radio">
                <input type="radio" name={`display-mode-${node.id}`} checked={displayMode === 'list'} onChange={() => onDraftChange({ display_mode: 'list' })} />
                Lista WhatsApp
              </label>
            </fieldset>
            <label className="flow-editor-field">
              Texto
              <textarea value={toText(draft.content || draft.body_text)} onChange={(event) => onDraftChange({ content: event.target.value, body_text: event.target.value })} placeholder="Escolha uma opção" />
            </label>
            <div className="flow-editor-repeatable">
              <strong>Opções {displayMode === 'buttons' ? `(${buttons.length}/3)` : `(${buttons.length})`}</strong>
              {buttons.map((button, index) => (
                <div key={button.id || index} className="flow-editor-row">
                  <input value={button.label || ''} onChange={(event) => updateButton(index, event.target.value)} placeholder={`Opção ${index + 1}`} />
                  <button type="button" onClick={() => onDraftChange({ buttons: buttons.filter((_, buttonIndex) => buttonIndex !== index) })}>Remover</button>
                </div>
              ))}
              <button type="button" className="flow-editor-secondary-btn" onClick={addButton} disabled={displayMode === 'buttons' && buttons.length >= 3}>+ Adicionar opção</button>
            </div>
          </>
        )}

        {kind === 'cta_url' && (() => {
          const buttonText = toText(draft.button_text);
          const url = toText(draft.url);
          const urlInvalid = url.trim().length > 0 && !url.trim().startsWith('https://') && !url.includes('{{');
          const buttonInvalid = buttonText.length > 20;
          return (
            <>
              <div className="flow-editor-info-card"><strong>Tipo:</strong> Botão com link externo <span>CTA URL</span></div>
              <label className="flow-editor-field">
                Texto da mensagem
                <textarea ref={ctaTextRef} value={toText(draft.content || draft.text || draft.message)} onChange={(event) => onDraftChange({ content: event.target.value, text: event.target.value, message: event.target.value })} placeholder="Sua fatura está disponível." required />
                <VariableChips targetRef={ctaTextRef} value={toText(draft.content || draft.text || draft.message)} onChange={(next) => onDraftChange({ content: next, text: next, message: next })} />
              </label>
              <label className="flow-editor-field">
                Texto do botão
                <input ref={ctaButtonTextRef} value={buttonText} maxLength={20} onChange={(event) => onDraftChange({ button_text: event.target.value })} placeholder="Acessar Fatura" required />
                <VariableChips targetRef={ctaButtonTextRef} value={buttonText} onChange={(next) => onDraftChange({ button_text: next })} />
                <small>{buttonText.length}/20 caracteres</small>
                {buttonInvalid ? <small className="flow-editor-error">O botão deve ter no máximo 20 caracteres.</small> : null}
              </label>
              <label className="flow-editor-field">
                URL
                <input ref={ctaUrlRef} value={url} onChange={(event) => onDraftChange({ url: event.target.value })} placeholder="https://exemplo.com/fatura" required />
                <VariableChips targetRef={ctaUrlRef} value={url} onChange={(next) => onDraftChange({ url: next })} />
                {urlInvalid ? <small className="flow-editor-error">A URL precisa começar com https:// ou conter variável</small> : null}
              </label>
            </>
          );
        })()}

        {kind === 'condition' && (
          <label className="flow-editor-field">
            Regras / palavras-chave
            <textarea value={toText(draft.condition)} onChange={(event) => onDraftChange({ condition: event.target.value })} placeholder="sim, suporte, ajuda" />
            <small>Separe múltiplas palavras por vírgula. Saídas: Sim e Não.</small>
          </label>
        )}

        {kind === 'ai_classification' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> IA Classificação <span>IA</span></div>
            <label className="flow-editor-field">Instrução<textarea value={toText(draft.instruction)} onChange={(event) => onDraftChange({ instruction: event.target.value })} /></label>
            <label className="flow-editor-field">Input template<input value={toText(draft.input_template || '{{last_message}}')} onChange={(event) => onDraftChange({ input_template: event.target.value })} /></label>
            <label className="flow-editor-field">Categorias<textarea value={((draft.categories as string[] | undefined) || []).join('\n')} onChange={(event) => onDraftChange({ categories: event.target.value.split(/\n|,/).map((v) => v.trim()).filter(Boolean) })} placeholder="financeiro\nvendas\nsuporte\noutro" /><small>Uma por linha ou separadas por vírgula.</small></label>
            <div className="flow-editor-row"><label className="flow-editor-field">Threshold<input type="number" min="0" max="1" step="0.1" value={toText(draft.confidence_threshold ?? 0.6)} onChange={(event) => onDraftChange({ confidence_threshold: Number(event.target.value || 0.6) })} /></label><label className="flow-editor-field">Output variable<input value={toText(draft.output_variable || 'ai.classification')} onChange={(event) => onDraftChange({ output_variable: event.target.value })} /></label></div>
            <label className="flow-editor-radio"><input type="checkbox" checked={draft.send_debug_message === true} onChange={(event) => onDraftChange({ send_debug_message: event.target.checked })} /> Enviar debug message</label>
          </>
        )}

        {kind === 'ai_extraction' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> IA Extração <span>IA</span></div>
            <label className="flow-editor-field">Instrução<textarea value={toText(draft.instruction)} onChange={(event) => onDraftChange({ instruction: event.target.value })} /></label>
            <label className="flow-editor-field">Input template<input value={toText(draft.input_template || '{{last_message}}')} onChange={(event) => onDraftChange({ input_template: event.target.value })} /></label>
            <div className="flow-editor-repeatable"><strong>Campos</strong>{(((draft.fields as any[]) || [])).map((field, index) => <div key={index} className="flow-editor-row"><input value={toText(field.name)} onChange={(event) => { const next = [...(((draft.fields as any[]) || []))]; next[index] = { ...field, name: event.target.value }; onDraftChange({ fields: next }); }} placeholder="nome" /><select value={toText(field.type || 'string')} onChange={(event) => { const next = [...(((draft.fields as any[]) || []))]; next[index] = { ...field, type: event.target.value }; onDraftChange({ fields: next }); }}><option value="string">string</option><option value="number">number</option><option value="boolean">boolean</option><option value="date">date</option><option value="email">email</option><option value="phone">phone</option><option value="cpf">cpf</option><option value="cnpj">cnpj</option></select><input value={toText(field.description)} onChange={(event) => { const next = [...(((draft.fields as any[]) || []))]; next[index] = { ...field, description: event.target.value }; onDraftChange({ fields: next }); }} placeholder="Descrição" /><button type="button" onClick={() => onDraftChange({ fields: (((draft.fields as any[]) || [])).filter((_, i) => i !== index) })}>Remover</button></div>)}<button type="button" className="flow-editor-secondary-btn" onClick={() => onDraftChange({ fields: [...(((draft.fields as any[]) || [])), { name: '', type: 'string', description: '' }] })}>+ Adicionar campo</button></div>
            <label className="flow-editor-radio"><input type="checkbox" checked={draft.include_conversation_history !== false} onChange={(event) => onDraftChange({ include_conversation_history: event.target.checked })} /> Incluir histórico</label>
            <label className="flow-editor-field">Output variable<input value={toText(draft.output_variable || 'ai.extraction')} onChange={(event) => onDraftChange({ output_variable: event.target.value })} /></label>
            <label className="flow-editor-radio"><input type="checkbox" checked={draft.send_debug_message === true} onChange={(event) => onDraftChange({ send_debug_message: event.target.checked })} /> Enviar debug message</label>
          </>
        )}


        {kind === 'ai_summary' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> IA Resumo <span>IA</span><small>Usa as configurações de IA do workspace. Não insira API key no node.</small></div>
            <fieldset className="flow-editor-field">
              <legend>Fonte do resumo</legend>
              <label className="flow-editor-radio"><input type="radio" name={`ai-summary-source-${node.id}`} checked={(draft.summary_source || 'conversation_history') === 'conversation_history'} onChange={() => onDraftChange({ summary_source: 'conversation_history' })} /> Histórico da conversa</label>
              <label className="flow-editor-radio"><input type="radio" name={`ai-summary-source-${node.id}`} checked={draft.summary_source === 'custom_text'} onChange={() => onDraftChange({ summary_source: 'custom_text' })} /> Texto customizado</label>
            </fieldset>
            {draft.summary_source === 'custom_text' ? <label className="flow-editor-field">Texto customizado / input template<textarea value={toText(draft.input_template || '{{last_message}}')} onChange={(event) => onDraftChange({ input_template: event.target.value })} placeholder="{{last_message}}" /></label> : null}
            <label className="flow-editor-field">Instrução adicional<textarea value={toText(draft.instruction)} onChange={(event) => onDraftChange({ instruction: event.target.value })} placeholder="Ex.: destaque risco de churn e próximos passos." /></label>
            <label className="flow-editor-field">Formato<select value={toText(draft.summary_format || 'handoff')} onChange={(event) => onDraftChange({ summary_format: event.target.value })}><option value="handoff">Handoff</option><option value="short">Curto</option><option value="detailed">Detalhado</option><option value="bullet_points">Tópicos</option></select></label>
            <div className="flow-editor-row"><label className="flow-editor-field">Máximo de mensagens<input type="number" min="1" max="100" value={toText(draft.max_history_messages || 30)} onChange={(event) => onDraftChange({ max_history_messages: Number(event.target.value || 30) })} disabled={draft.summary_source === 'custom_text'} /></label><label className="flow-editor-field">Máximo de caracteres<input type="number" min="500" max="20000" value={toText(draft.max_history_chars || 8000)} onChange={(event) => onDraftChange({ max_history_chars: Number(event.target.value || 8000) })} disabled={draft.summary_source === 'custom_text'} /></label></div>
            <label className="flow-editor-field">Variável de saída<input value={toText(draft.output_variable || 'ai.summary')} onChange={(event) => onDraftChange({ output_variable: event.target.value })} /></label>
            <label className="flow-editor-radio"><input type="checkbox" checked={draft.send_message === true} onChange={(event) => onDraftChange({ send_message: event.target.checked })} /> Enviar resumo como mensagem</label>
            <label className="flow-editor-radio"><input type="checkbox" checked={draft.continue_on_error !== false} onChange={(event) => onDraftChange({ continue_on_error: event.target.checked })} /> Continuar em caso de erro</label>
            <details className="flow-editor-info-card"><summary>Avançado: modelo, temperatura e tokens</summary><label className="flow-editor-field">Modelo (opcional)<input value={toText(draft.model_override)} onChange={(event) => onDraftChange({ model_override: event.target.value })} placeholder="Ex.: gpt-4o-mini" /></label><div className="flow-editor-row"><label className="flow-editor-field">Temperatura<input type="number" min="0" max="1" step="0.1" value={toText(draft.temperature ?? 0.2)} onChange={(event) => onDraftChange({ temperature: Number(event.target.value || 0.2) })} /></label><label className="flow-editor-field">Máx tokens<input type="number" min="1" max="8000" value={toText(draft.max_tokens || 800)} onChange={(event) => onDraftChange({ max_tokens: Number(event.target.value || 800) })} /></label></div></details>
          </>
        )}

        {kind === 'ai_rag' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> IA com RAG <span>Base de conhecimento</span></div>
            <label className="flow-editor-field">
              Instrução do assistente
              <textarea value={toText(draft.instruction)} onChange={(event) => onDraftChange({ instruction: event.target.value })} placeholder="Responda como atendente da prefeitura." />
            </label>
            <label className="flow-editor-field">
              Pergunta
              <input value={toText(draft.question || '{{last_message}}')} onChange={(event) => onDraftChange({ question: event.target.value })} placeholder="{{last_message}}" />
            </label>
            <label className="flow-editor-radio">
              <input type="checkbox" checked={draft.use_workspace_ai_settings !== false} onChange={(event) => onDraftChange({ use_workspace_ai_settings: event.target.checked })} />
              Usar configuração padrão do workspace
            </label>
            <label className="flow-editor-field">
              Sobrescrever modelo (opcional)
              <input value={toText(draft.model_override)} onChange={(event) => onDraftChange({ model_override: event.target.value })} placeholder="Ex.: gpt-4o-mini" disabled={draft.use_workspace_ai_settings !== false} />
              <small>Não insira API key neste node. Use Configurações de IA do workspace.</small>
            </label>
            <div className="flow-editor-row">
              <label className="flow-editor-field">
                Top K
                <input type="number" min="1" max="10" value={toText(draft.top_k || 5)} onChange={(event) => onDraftChange({ top_k: Number(event.target.value || 5) })} />
              </label>
              <label className="flow-editor-field">
                Temperatura
                <input type="number" min="0" max="1" step="0.1" value={toText(draft.temperature ?? 0.2)} onChange={(event) => onDraftChange({ temperature: Number(event.target.value || 0.2), use_workspace_ai_settings: false })} />
              </label>
              <label className="flow-editor-field">
                Máx. tokens
                <input type="number" min="1" max="8000" value={toText(draft.max_tokens || 1200)} onChange={(event) => onDraftChange({ max_tokens: Number(event.target.value || 1200), use_workspace_ai_settings: false })} />
              </label>
            </div>
            <label className="flow-editor-radio">
              <input type="checkbox" checked={draft.knowledge_only !== false} onChange={(event) => onDraftChange({ knowledge_only: event.target.checked })} />
              Responder somente com base de conhecimento
            </label>
            <label className="flow-editor-radio">
              <input type="checkbox" checked={draft.memory_enabled !== false} onChange={(event) => onDraftChange({ memory_enabled: event.target.checked })} />
              Usar memória da conversa
            </label>
            <div className="flow-editor-row">
              <label className="flow-editor-field">
                Nº máximo de mensagens
                <input type="number" min="1" max="30" value={toText(draft.memory_max_messages || 10)} onChange={(event) => onDraftChange({ memory_max_messages: Number(event.target.value || 10) })} disabled={draft.memory_enabled === false} />
              </label>
              <label className="flow-editor-field">
                Limite de caracteres
                <input type="number" min="500" max="12000" value={toText(draft.memory_max_chars || 4000)} onChange={(event) => onDraftChange({ memory_max_chars: Number(event.target.value || 4000) })} disabled={draft.memory_enabled === false} />
              </label>
            </div>
            <label className="flow-editor-field">
              Mensagem fallback
              <textarea value={toText(draft.fallback_message)} onChange={(event) => onDraftChange({ fallback_message: event.target.value })} placeholder="Não encontrei essa informação com segurança na base disponível. Quer que eu encaminhe para um atendente?" />
            </label>
            <fieldset className="flow-editor-field flow-editor-after-answer">
              <legend>Depois de responder</legend>
              <label className="flow-editor-choice-card">
                <input type="radio" name={`ai-rag-after-answer-${node.id}`} checked={(draft.after_answer_behavior || 'end_flow') === 'end_flow'} onChange={() => onDraftChange({ after_answer_behavior: 'end_flow', is_terminal: false, endFlow: false })} />
                <span className="flow-editor-choice-icon" aria-hidden="true">✓</span>
                <span>
                  <strong>Encerrar conversa</strong>
                  <small>A sessão termina após a resposta da IA.</small>
                </span>
              </label>
              <label className="flow-editor-choice-card">
                <input type="radio" name={`ai-rag-after-answer-${node.id}`} checked={draft.after_answer_behavior === 'continue_to_next'} onChange={() => onDraftChange({ after_answer_behavior: 'continue_to_next', is_terminal: false, endFlow: false })} />
                <span className="flow-editor-choice-icon" aria-hidden="true">↗</span>
                <span>
                  <strong>Continuar para outro bloco</strong>
                  <small>O fluxo segue pela conexão de saída.</small>
                </span>
              </label>
              <label className="flow-editor-choice-card">
                <input type="radio" name={`ai-rag-after-answer-${node.id}`} checked={draft.after_answer_behavior === 'wait_same_node'} onChange={() => onDraftChange({ after_answer_behavior: 'wait_same_node', is_terminal: false, endFlow: false })} />
                <span className="flow-editor-choice-icon" aria-hidden="true">↻</span>
                <span>
                  <strong>Manter conversa neste bloco</strong>
                  <small>Ideal para atendimento contínuo. Cada nova mensagem retorna para este mesmo node.</small>
                </span>
              </label>
            </fieldset>
          </>
        )}

        {kind === 'ai_response' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> IA Resposta <span>IA</span></div>
            <label className="flow-editor-field">
              Instrução do assistente
              <textarea value={toText(draft.instruction)} onChange={(event) => onDraftChange({ instruction: event.target.value })} placeholder="Responda como atendente." />
            </label>
            <label className="flow-editor-field">
              Pergunta
              <input value={toText(draft.question || '{{last_message}}')} onChange={(event) => onDraftChange({ question: event.target.value })} placeholder="{{last_message}}" />
            </label>
            <label className="flow-editor-radio">
              <input type="checkbox" checked={draft.memory_enabled !== false} onChange={(event) => onDraftChange({ memory_enabled: event.target.checked })} />
              Usar memória da conversa
            </label>
            <div className="flow-editor-row">
              <label className="flow-editor-field">
                Máximo de mensagens
                <input type="number" min="1" max="30" value={toText(draft.memory_max_messages || 10)} onChange={(event) => onDraftChange({ memory_max_messages: Number(event.target.value || 10) })} disabled={draft.memory_enabled === false} />
              </label>
              <label className="flow-editor-field">
                Máximo de caracteres
                <input type="number" min="500" max="12000" value={toText(draft.memory_max_chars || 4000)} onChange={(event) => onDraftChange({ memory_max_chars: Number(event.target.value || 4000) })} disabled={draft.memory_enabled === false} />
              </label>
            </div>
            <label className="flow-editor-field">
              Sobrescrever modelo (opcional)
              <input value={toText(draft.model_override)} onChange={(event) => onDraftChange({ model_override: event.target.value })} placeholder="Ex.: gpt-4o-mini" />
              <small>Não insira API key neste node. A IA sempre usa as configurações do workspace.</small>
            </label>
            <div className="flow-editor-row">
              <label className="flow-editor-field">
                Temperatura
                <input type="number" min="0" max="1" step="0.1" value={toText(draft.temperature ?? 0.2)} onChange={(event) => onDraftChange({ temperature: Number(event.target.value || 0.2) })} />
              </label>
              <label className="flow-editor-field">
                Máx tokens
                <input type="number" min="1" max="8000" value={toText(draft.max_tokens || 1200)} onChange={(event) => onDraftChange({ max_tokens: Number(event.target.value || 1200) })} />
              </label>
            </div>
            <fieldset className="flow-editor-field flow-editor-after-answer">
              <legend>Depois de responder</legend>
              <label className="flow-editor-choice-card">
                <input type="radio" name={`ai-response-after-answer-${node.id}`} checked={(draft.after_answer_behavior || 'end_flow') === 'end_flow'} onChange={() => onDraftChange({ after_answer_behavior: 'end_flow', is_terminal: false, endFlow: false })} />
                <span className="flow-editor-choice-icon" aria-hidden="true">✓</span>
                <span><strong>Encerrar fluxo</strong><small>A sessão termina após a resposta da IA.</small></span>
              </label>
              <label className="flow-editor-choice-card">
                <input type="radio" name={`ai-response-after-answer-${node.id}`} checked={draft.after_answer_behavior === 'continue_to_next'} onChange={() => onDraftChange({ after_answer_behavior: 'continue_to_next', is_terminal: false, endFlow: false })} />
                <span className="flow-editor-choice-icon" aria-hidden="true">↗</span>
                <span><strong>Continuar para próximo node</strong><small>O fluxo segue pela conexão de saída.</small></span>
              </label>
              <label className="flow-editor-choice-card">
                <input type="radio" name={`ai-response-after-answer-${node.id}`} checked={draft.after_answer_behavior === 'wait_same_node'} onChange={() => onDraftChange({ after_answer_behavior: 'wait_same_node', is_terminal: false, endFlow: false })} />
                <span className="flow-editor-choice-icon" aria-hidden="true">↻</span>
                <span><strong>Aguardar nova mensagem neste node</strong><small>Cada nova mensagem retorna para este mesmo node.</small></span>
              </label>
            </fieldset>
          </>
        )}


        {kind === 'ai_agent' && (
          <>
            <div className="flow-editor-agent-hero"><div><strong>🤖 IA Agente</strong><small>Editor premium compatível com o payload atual.</small></div><span className={`flow-editor-complexity flow-editor-complexity-${complexity.tone}`}>{complexity.label}</span></div>
            <div className="flow-editor-agent-metrics"><span>🛠 Ferramentas: {allowedTools.length}</span><span>🔀 Nodes: {nodeTools.length}</span><span>📂 Subflows: {subflowTools.length}</span><span>🌐 Webhooks: {webhooks.length}</span><span>🔌 MCP: {selectedMcpTools.length}</span><span>🧠 Memória: {draft.use_memory !== false ? 'Ativa' : 'Inativa'}</span><span>⚡ Modelo: {modelUsesGlobal ? 'Global' : modelLabel}</span></div>
            <div className="flow-editor-tabs"><a href="#agent-general">Geral</a><a href="#agent-smart-tools">Ferramentas Inteligentes</a><a href="#agent-tools">Ferramentas</a><a href="#agent-memory">Memória</a><a href="#agent-subflows">Subflows</a><a href="#agent-advanced">Avançado</a></div>

            <section id="agent-smart-tools" className="flow-editor-tab-section flow-editor-smart-tools"><div className="flow-editor-smart-heading"><div><h4>Ferramentas Inteligentes</h4><p>Visão consolidada derivada das configurações existentes do agente, sem criar payload paralelo.</p></div><button type="button" className="flow-editor-secondary-btn" onClick={() => setAgentQuickAddOpen((current) => !current)}>+ Adicionar</button></div><div className="flow-editor-smart-toolbar"><input value={agentSearch} onChange={(event) => setAgentSearch(event.target.value)} placeholder="Pesquisar ferramenta..." /><button type="button" className="flow-editor-secondary-btn" onClick={() => setAgentAdvancedView((current) => !current)}>{agentAdvancedView ? 'Ocultar detalhes técnicos' : 'Mostrar detalhes técnicos'}</button></div>{agentQuickAddOpen ? <div className="flow-editor-quick-add"><button type="button" onClick={() => { setAgentQuickAddOpen(false); document.getElementById('agent-tools')?.scrollIntoView({ behavior: 'smooth' }); }}>Ferramenta</button><button type="button" onClick={() => { addNodeTool(); setAgentQuickAddOpen(false); }}>Node</button><button type="button" onClick={() => { addSubflowTool(); setAgentQuickAddOpen(false); }}>Subflow</button><button type="button" onClick={() => { setAgentQuickAddOpen(false); document.getElementById('agent-mcp-tools')?.scrollIntoView({ behavior: 'smooth' }); }}>MCP</button><button type="button" onClick={() => { setAgentQuickAddOpen(false); document.getElementById('agent-advanced')?.scrollIntoView({ behavior: 'smooth' }); }}>Webhook</button></div> : null}<div className="flow-editor-smart-groups"><div className="flow-editor-smart-group"><h5>💬 Ações</h5>{filteredAgentTools.length ? filteredAgentTools.map((tool) => <article key={tool.id} className="flow-editor-smart-card" title="Permite ao agente executar esta ação." onClick={() => setAgentDrawerItem({ title: tool.name, icon: tool.icon, description: tool.description, config: { allowed_tool: tool.id, enabled: true }, limits: `Max steps: ${Number(draft.max_steps || 3)}` })}><span>{tool.icon}</span><div><strong>{tool.name}</strong><small>{tool.description}</small>{agentAdvancedView ? <code>{tool.id}</code> : null}</div></article>) : <small className="flow-editor-muted">Nenhuma ação ativa encontrada.</small>}</div><div className="flow-editor-smart-group"><h5>🔀 Nodes do Fluxo</h5>{filteredNodeTools.length ? filteredNodeTools.map((tool, index) => <article key={`${toText(tool.tool_id)}-${index}`} className="flow-editor-smart-card" title="Permite ao agente executar este node do fluxo." onClick={() => setAgentDrawerItem({ title: toText(tool.label) || 'Ferramenta sem nome', icon: '🧠', description: toText(tool.description) || 'Sem descrição.', config: tool, variables: `Node: ${toText(tool.node_id)}`, limits: `Limite: ${Number(draft.max_node_tool_calls || 3)} chamadas` })}><span>🧠</span><div><strong>{toText(tool.label) || 'Ferramenta sem nome'}</strong><small>{toText(tool.description) || 'Sem descrição.'}</small>{agentAdvancedView ? <code>{toText(tool.tool_id) || 'sem_tool_id'}</code> : null}</div><button type="button" onClick={(event) => { event.stopPropagation(); document.getElementById('agent-tools')?.scrollIntoView({ behavior: 'smooth' }); }}>Editar</button><button type="button" onClick={(event) => { event.stopPropagation(); onDraftChange({ node_tools: nodeTools.filter((item) => item !== tool) }); }}>Remover</button></article>) : <small className="flow-editor-muted">Nenhum node configurado como ferramenta.</small>}</div><div className="flow-editor-smart-group"><h5>📂 Subflows</h5>{filteredSubflowTools.length ? filteredSubflowTools.map((tool, index) => <article key={`${toText(tool.tool_id)}-${index}`} className="flow-editor-smart-card" title="Permite ao agente acionar este subflow." onClick={() => setAgentDrawerItem({ title: toText(tool.label) || 'Subflow sem nome', icon: '📂', description: toText(tool.description) || 'Sem descrição.', config: tool, variables: `${toText(tool.input_variable) || 'input_variable não definido'} → ${toText(tool.output_variable) || 'output_variable não definido'}`, limits: `Timeout: ${Number(tool.timeout_seconds || 20)}s · Limite: ${Number(draft.max_subflow_calls || 2)}` })}><span>📂</span><div><strong>{toText(tool.label) || 'Subflow sem nome'}</strong><small>{toText(tool.description) || 'Sem descrição.'}</small><small>Timeout: {Number(tool.timeout_seconds || 20)}s · Limite: {Number(draft.max_subflow_calls || 2)}</small>{agentAdvancedView ? <code>{toText(tool.tool_id) || 'sem_tool_id'}</code> : null}</div><button type="button" onClick={(event) => { event.stopPropagation(); document.getElementById('agent-subflows')?.scrollIntoView({ behavior: 'smooth' }); }}>Editar</button><button type="button" onClick={(event) => { event.stopPropagation(); onDraftChange({ subflow_tools: subflowTools.filter((item) => item !== tool) }); }}>Remover</button></article>) : <small className="flow-editor-muted">Nenhum subflow configurado.</small>}</div><div className="flow-editor-smart-group"><h5>🔌 MCP</h5>{filteredMcpTools.length ? filteredMcpTools.map((tool) => <article key={tool.id} className="flow-editor-smart-card" title="Permite ao agente executar esta ferramenta MCP." onClick={() => setAgentDrawerItem({ title: `[MCP] ${toText(tool.display_name || tool.tool_name)}`, icon: '🔌', description: toText(tool.description) || 'Sem descrição.', config: { tool_id: tool.id, origin: tool.server_name, input_schema: tool.input_schema || {} }, limits: `Limite: ${Number(draft.max_mcp_calls || 3)} chamadas` })}><span>🔌</span><div><strong>[MCP] {toText(tool.display_name || tool.tool_name)}</strong><small>{toText(tool.description) || 'Sem descrição.'}</small><small>Origem: {toText(tool.server_name) || 'Integração MCP'}</small>{agentAdvancedView ? <code>{tool.id}</code> : null}</div><button type="button" onClick={(event) => { event.stopPropagation(); removeMcpTool(tool.id); }}>Remover</button></article>) : <small className="flow-editor-muted">Nenhuma ferramenta MCP selecionada.</small>}</div>{agentAdvancedView ? <div className="flow-editor-smart-group"><h5>🌐 Webhooks</h5>{filteredWebhooks.length ? filteredWebhooks.map((webhook, index) => <article key={`${toText(webhook.webhook_id)}-${index}`} className="flow-editor-smart-card" title="Permite ao agente chamar este webhook autorizado." onClick={() => setAgentDrawerItem({ title: toText(webhook.name || webhook.label || webhook.webhook_id) || 'Webhook sem nome', icon: '🌐', description: toText(webhook.description) || 'Sem descrição.', config: webhook })}><span>🌐</span><div><strong>{toText(webhook.name || webhook.label || webhook.webhook_id) || 'Webhook sem nome'}</strong><small>{toText(webhook.description) || 'Sem descrição.'}</small><code>{toText(webhook.webhook_id) || 'sem_webhook_id'}</code></div></article>) : <small className="flow-editor-muted">Nenhum webhook autorizado no JSON atual.</small>}</div> : null}</div>{agentDrawerItem ? <aside className="flow-editor-smart-drawer"><button type="button" onClick={() => setAgentDrawerItem(null)}>×</button><h4>{agentDrawerItem.icon} {agentDrawerItem.title}</h4><p>{agentDrawerItem.description}</p><strong>Configuração</strong><pre>{JSON.stringify(agentDrawerItem.config || {}, null, 2)}</pre><strong>Variáveis</strong><small>{agentDrawerItem.variables || 'Sem variáveis específicas.'}</small><strong>Limites</strong><small>{agentDrawerItem.limits || 'Sem limites específicos.'}</small></aside> : null}</section>
            <section id="agent-general" className="flow-editor-tab-section"><h4>Geral</h4><p>Configure identidade, prompt, modelo e comportamento do agente.</p>
              <label className="flow-editor-field">Nome do agente<input value={toText(draft.agent_name)} onChange={(event) => onDraftChange({ agent_name: event.target.value })} placeholder="Assistente comercial" /><small>Campo visual para facilitar manutenção do fluxo.</small></label>
              <label className="flow-editor-field">Descrição opcional<input value={toText(draft.description)} onChange={(event) => onDraftChange({ description: event.target.value })} /><small>Explique o objetivo deste agente.</small></label>
              <label className="flow-editor-field">Instrução do agente<textarea value={toText(draft.instruction || 'Você é um agente de atendimento. Use apenas as ferramentas permitidas.')} onChange={(event) => onDraftChange({ instruction: event.target.value })} /><small>Defina tom, limites e quando usar ferramentas.</small></label>
              <label className="flow-editor-field">Input template<input value={toText(draft.input_template || '{{last_message}}')} onChange={(event) => onDraftChange({ input_template: event.target.value })} placeholder="{{last_message}}" /><small>Entrada enviada para a IA com suporte a variáveis.</small></label>
              <fieldset className="flow-editor-field flow-editor-after-answer"><legend>Modelo IA</legend><label className="flow-editor-choice-card"><input type="radio" name={`ai-agent-model-${node.id}`} checked={modelUsesGlobal} onChange={() => onDraftChange({ model_override: '' })} /><span className="flow-editor-choice-icon">⚡</span><span><strong>Usar configuração global</strong><small>Usa o modelo do workspace.</small></span></label><label className="flow-editor-choice-card"><input type="radio" name={`ai-agent-model-${node.id}`} checked={!modelUsesGlobal} onChange={() => onDraftChange({ model_override: toText(draft.model_override) || 'gpt-4o-mini' })} /><span className="flow-editor-choice-icon">✎</span><span><strong>Sobrescrever neste node</strong><small>Habilita modelo, temperatura e tokens locais.</small></span></label></fieldset>
              {!modelUsesGlobal ? <div className="flow-editor-row"><label className="flow-editor-field">Modelo IA<input value={toText(draft.model_override)} onChange={(event) => onDraftChange({ model_override: event.target.value })} /><small>Não insira API key neste node.</small></label><label className="flow-editor-field">Temperatura<input type="number" min="0" max="1" step="0.1" value={toText(draft.temperature ?? 0.2)} onChange={(event) => onDraftChange({ temperature: Number(event.target.value || 0.2) })} /><small>Controla criatividade.</small></label><label className="flow-editor-field">Máx Tokens<input type="number" min="1" max="8000" value={toText(draft.max_tokens || 1200)} onChange={(event) => onDraftChange({ max_tokens: Number(event.target.value || 1200) })} /><small>Limite da resposta.</small></label></div> : null}
              <fieldset className="flow-editor-field flow-editor-after-answer"><legend>Comportamento após responder</legend>{[['end_flow','✓','Encerrar atendimento'],['continue_to_next','↗','Continuar fluxo'],['wait_same_node','↻','Permanecer aguardando novas mensagens']].map(([value, icon, label]) => <label key={value} className="flow-editor-choice-card"><input type="radio" name={`ai-agent-after-${node.id}`} checked={(draft.after_agent_behavior || draft.after_answer_behavior || 'wait_same_node') === value} onChange={() => onDraftChange({ after_agent_behavior: value, after_answer_behavior: value })} /><span className="flow-editor-choice-icon">{icon}</span><span><strong>{label}</strong><small>Salva internamente como {value}.</small></span></label>)}</fieldset>
            </section>
            <section id="agent-tools" className="flow-editor-tab-section"><h4>Ferramentas</h4><p>Ferramentas definem quais ações a IA poderá executar.</p><div className="flow-editor-tool-grid">{agentToolCatalog.map((tool) => <label key={tool.id} className="flow-editor-tool-card"><span className="flow-editor-tool-icon">{tool.icon}</span><strong>{tool.name}</strong><small>{tool.description}</small><input type="checkbox" checked={allowedTools.includes(tool.id)} onChange={(event) => onDraftChange({ allowed_tools: event.target.checked ? Array.from(new Set([...allowedTools, tool.id])) : allowedTools.filter((item) => item !== tool.id) })} /><em>{allowedTools.includes(tool.id) ? 'Ativado' : 'Desativado'}</em></label>)}</div><div className="flow-editor-subflow-header"><label className="flow-editor-radio"><input type="checkbox" checked={draft.allow_node_tools === true} onChange={(event) => onDraftChange({ allow_node_tools: event.target.checked })} />Ativar ferramentas do fluxo</label><button type="button" className="flow-editor-secondary-btn" onClick={addNodeTool} disabled={nodeToolOptions.length === 0}>+ Adicionar ferramenta</button></div><label className="flow-editor-field">Limite de chamadas<input type="number" min="1" max="5" value={toText(draft.max_node_tool_calls || 3)} onChange={(event) => onDraftChange({ max_node_tool_calls: Math.min(5, Math.max(1, Number(event.target.value || 3))) })} /><small>Apenas IA Resposta, IA Conhecimento, IA Classificação, IA Extração, IA Resumo, Mensagem e Ação.</small></label><div className="flow-editor-subflow-list">{nodeTools.map((tool, index) => <article key={`${toText(tool.tool_id)}-${index}`} className="flow-editor-subflow-card"><div className="flow-editor-subflow-card-title"><strong>🧩 {toText(tool.label) || 'Ferramenta sem nome'}</strong><button type="button" onClick={() => onDraftChange({ node_tools: nodeTools.filter((item) => item !== tool) })}>Remover</button></div><label className="flow-editor-field">Node<select value={toText(tool.node_id)} onChange={(event) => { const selected = nodeToolOptions.find((item) => item.id === event.target.value); const label = selected ? getBuilderNodeTitle(selected) : toText(tool.label); updateNodeTool(index, { node_id: event.target.value, label, tool_id: slugifyToolId(label), description: toText(tool.description) || `Executa o bloco ${label}.` }); }}>{nodeToolOptions.map((item) => <option key={item.id} value={item.id}>{getBuilderNodeTitle(item)}</option>)}</select></label><div className="flow-editor-row"><label className="flow-editor-field">Label<input value={toText(tool.label)} onChange={(event) => updateNodeTool(index, { label: event.target.value })} /></label><label className="flow-editor-field">tool_id<input value={toText(tool.tool_id)} onChange={(event) => updateNodeTool(index, { tool_id: event.target.value.replace(/[^A-Za-z0-9_]/g, '') })} /></label></div><label className="flow-editor-field">Descrição<input value={toText(tool.description)} onChange={(event) => updateNodeTool(index, { description: event.target.value })} /></label></article>)}</div>{nodeToolErrors.length > 0 ? <div className="flow-editor-validation-list">{nodeToolErrors.map((error) => <small key={error}>⚠️ {error}</small>)}</div> : null}<details className="flow-editor-advanced-json"><summary>Editar JSON avançado</summary><textarea value={JSON.stringify(draft.node_tools || [], null, 2)} onChange={(event) => { try { onDraftChange({ node_tools: JSON.parse(event.target.value) }); } catch { onDraftChange({ node_tools_json_error: true }); } }} /></details></section>
            <section id="agent-mcp-tools" className="flow-editor-tab-section"><h4>Ferramentas MCP e integrações</h4><p>Ferramentas MCP continuam separadas das integrações reais conectadas, todas disponíveis ao ToolRegistry como <code>chamar_mcp</code>.</p><div className="flow-editor-subflow-header"><label className="flow-editor-radio"><input type="checkbox" checked={draft.allow_mcp_tools === true} onChange={(event) => onDraftChange({ allow_mcp_tools: event.target.checked, ...(event.target.checked ? { allowed_tools: Array.from(new Set([...allowedTools, 'chamar_mcp'])) } : {}) })} />Ativar ferramentas MCP/integrações</label><label className="flow-editor-field">Adicionar ferramenta<select value="" onChange={(event) => { addMcpTool(event.target.value); event.currentTarget.value = ''; }}><option value="">+ Adicionar ferramenta</option>{activeMcpTools.filter((tool) => !mcpToolIds.includes(tool.id)).map((tool) => <option key={tool.id} value={tool.id}>{tool.metadata?.provider === 'google_calendar' ? toText(tool.display_name || tool.tool_name) : `[MCP] ${toText(tool.display_name || tool.tool_name)}`} — {toText(tool.server_name) || 'Integração MCP'}</option>)}</select></label></div><label className="flow-editor-field">Limite de chamadas MCP<input type="number" min="0" max="3" value={toText(draft.max_mcp_calls || 3)} onChange={(event) => onDraftChange({ max_mcp_calls: Math.min(3, Math.max(0, Number(event.target.value || 3))) })} /></label><div className="flow-editor-subflow-list">{selectedMcpTools.map((tool) => <article key={tool.id} className="flow-editor-subflow-card"><div className="flow-editor-subflow-card-title"><strong>🔌 {tool.metadata?.provider === 'google_calendar' ? toText(tool.display_name || tool.tool_name) : `[MCP] ${toText(tool.display_name || tool.tool_name)}`}</strong><button type="button" onClick={() => removeMcpTool(tool.id)}>Remover</button></div><small>{toText(tool.description) || 'Sem descrição.'}</small><small>Integração de origem: {toText(tool.server_name) || 'Integração MCP'}</small><code>{tool.id}</code></article>)}</div>{activeMcpTools.length === 0 ? <small className="flow-editor-muted">Nenhuma ferramenta MCP ativa encontrada neste tenant.</small> : null}</section><section id="agent-memory" className="flow-editor-tab-section"><h4>Memória</h4><p>Memória permite manter contexto entre mensagens.</p><label className="flow-editor-radio"><input type="checkbox" checked={draft.use_memory !== false} onChange={(event) => onDraftChange({ use_memory: event.target.checked })} />Usar memória da conversa</label><label className="flow-editor-radio flow-editor-disabled"><input type="checkbox" disabled />Usar memória de longo prazo</label><label className="flow-editor-radio flow-editor-disabled"><input type="checkbox" disabled />Permitir atualização automática da memória</label></section>
            <section id="agent-subflows" className="flow-editor-tab-section"><h4>Subflows</h4><p>Subflows permitem reutilizar fluxos completos.</p><div className="flow-editor-subflow-header"><label className="flow-editor-radio"><input type="checkbox" checked={draft.allow_subflow_tools === true} onChange={(event) => onDraftChange({ allow_subflow_tools: event.target.checked })} />Ativar subflows como ferramentas</label><button type="button" className="flow-editor-secondary-btn" onClick={addSubflowTool}>+ Adicionar Subflow</button></div><label className="flow-editor-field">Limite de chamadas<input type="number" min="1" max="3" value={toText(draft.max_subflow_calls || 2)} onChange={(event) => onDraftChange({ max_subflow_calls: Math.min(3, Math.max(1, Number(event.target.value || 2))) })} /></label><div className="flow-editor-subflow-list">{subflowTools.map((tool, index) => { const toolId = toText(tool.tool_id); return <article key={`${toolId || 'subflow'}-${index}`} className="flow-editor-subflow-card"><div className="flow-editor-subflow-card-title"><strong>📅 {toText(tool.label) || 'Subflow sem nome'}</strong><button type="button" onClick={() => onDraftChange({ subflow_tools: subflowTools.filter((item) => item !== tool) })}>Remover</button></div><small>{toText(tool.description).slice(0, 120) || 'Sem descrição'} · Timeout: {Number(tool.timeout_seconds || 20)}s · Ferramenta: {toolId || 'sem_tool_id'}</small><label className="flow-editor-field">Fluxo publicado<select value={toText(tool.flow_id)} onChange={(event) => { const flow = publishedSubflowOptions.find((item) => item.id === event.target.value); updateSubflowTool(index, { flow_id: event.target.value, ...(flow ? { flow_version_id: getPublishedVersionId(flow) } : {}) }); }}><option value="">Selecione um fluxo publicado</option>{publishedSubflowOptions.map((flow) => <option key={flow.id} value={flow.id}>{getFlowDisplayName(flow)}</option>)}</select></label><div className="flow-editor-row"><label className="flow-editor-field">Nome<input maxLength={80} value={toText(tool.label)} onChange={(event) => updateSubflowTool(index, { label: event.target.value.slice(0, 80) })} /></label><label className="flow-editor-field">tool_id<input value={toolId} onChange={(event) => updateSubflowTool(index, { tool_id: event.target.value.replace(/[^A-Za-z0-9_]/g, '') })} /></label></div><label className="flow-editor-field">Descrição<input maxLength={300} value={toText(tool.description)} onChange={(event) => updateSubflowTool(index, { description: event.target.value.slice(0, 300) })} /></label><label className="flow-editor-field">Timeout<input type="number" min="3" max="60" value={toText(tool.timeout_seconds || 20)} onChange={(event) => updateSubflowTool(index, { timeout_seconds: Math.min(60, Math.max(3, Number(event.target.value || 20))) })} /></label></article>; })}</div>{subflowErrors.length > 0 ? <div className="flow-editor-validation-list">{subflowErrors.map((error) => <small key={error}>⚠️ {error}</small>)}</div> : null}<details className="flow-editor-advanced-json"><summary>Editar JSON avançado</summary><textarea value={JSON.stringify(draft.subflow_tools || [], null, 2)} onChange={(event) => { try { onDraftChange({ subflow_tools: JSON.parse(event.target.value) }); } catch { onDraftChange({ subflow_tools_json_error: true }); } }} /></details></section>
            <section id="agent-advanced" className="flow-editor-tab-section"><h4>Avançado</h4><p>Configurações técnicas ficam recolhidas inicialmente.</p><details><summary>Max Steps</summary><label className="flow-editor-field">Max steps<input type="number" min="1" max="5" value={toText(draft.max_steps || 3)} onChange={(event) => onDraftChange({ max_steps: Number(event.target.value || 3) })} /></label></details><details><summary>Fallback</summary><fieldset className="flow-editor-field flow-editor-after-answer"><legend>Quando ocorrer erro</legend><label className="flow-editor-choice-card"><input type="radio" checked readOnly /><span className="flow-editor-choice-icon">💬</span><span><strong>Responder mensagem</strong><small>Persistido como fallback_message.</small></span></label><label className="flow-editor-choice-card flow-editor-disabled"><input type="radio" disabled /><span className="flow-editor-choice-icon">↗</span><span><strong>Continuar fluxo</strong><small>Opção futura.</small></span></label><label className="flow-editor-choice-card flow-editor-disabled"><input type="radio" disabled /><span className="flow-editor-choice-icon">🙋</span><span><strong>Transferir para humano</strong><small>Opção futura.</small></span></label></fieldset><label className="flow-editor-field">Mensagem de fallback<textarea value={toText(draft.fallback_message || 'Não consegui concluir essa ação agora. Quer que eu encaminhe para um atendente?')} onChange={(event) => onDraftChange({ fallback_message: event.target.value })} /></label></details><details><summary>Webhooks</summary><label className="flow-editor-field">Webhooks permitidos (JSON)<textarea value={JSON.stringify(draft.webhooks || [], null, 2)} onChange={(event) => { try { onDraftChange({ webhooks: JSON.parse(event.target.value) }); } catch { onDraftChange({ webhooks_json_error: true }); } }} /><small>A IA escolhe apenas webhook_id. Use apenas URLs https públicas.</small></label></details><details><summary>Timeouts e configurações experimentais</summary><small className="flow-editor-muted">Reservado para opções já presentes ou futuras do payload.</small></details></section>
          </>
        )}

        {kind === 'ai_supervisor' && (() => {
          const agentOptions = allNodes.filter((item) => item.id !== node.id && getBuilderNodeKind(item) === 'ai_agent');
          const selectedAgentIds = Array.isArray(draft.agent_ids) ? draft.agent_ids.map(String) : [];
          const fallbackId = toText(draft.fallback_agent_id);
          const fallbackLabel = agentOptions.find((item) => item.id === fallbackId) ? getBuilderNodeTitle(agentOptions.find((item) => item.id === fallbackId) as Node) : 'Não definido';
          return (
            <>
              <div className="flow-editor-agent-hero"><div><strong>🧠 Supervisor</strong><small>{selectedAgentIds.length} agentes disponíveis</small></div><span className="flow-editor-complexity flow-editor-complexity-low">SUPERVISOR</span></div>
              <div className="flow-editor-agent-metrics"><span>🧠 Supervisor</span><span>{selectedAgentIds.length} agentes disponíveis</span><span>Fallback: {fallbackLabel}</span><span>Modo: Escolher um</span></div>
              <label className="flow-editor-field">Nome<input value={toText(draft.name)} onChange={(event) => onDraftChange({ name: event.target.value })} /></label>
              <label className="flow-editor-field">Descrição<input value={toText(draft.description)} onChange={(event) => onDraftChange({ description: event.target.value })} /></label>
              <label className="flow-editor-field">Prompt do supervisor<textarea value={toText(draft.supervisor_prompt)} onChange={(event) => onDraftChange({ supervisor_prompt: event.target.value })} /></label>
              <label className="flow-editor-field">Input template<input value={toText(draft.input_template || '{{last_message}}')} onChange={(event) => onDraftChange({ input_template: event.target.value })} /></label>
              <label className="flow-editor-field">Máximo de agentes<input type="number" min="1" max="1" value={toText(draft.max_agents || 1)} onChange={() => onDraftChange({ max_agents: 1 })} /><small>Execução multiagente será habilitada em versão futura.</small></label>
              <fieldset className="flow-editor-field flow-editor-after-answer"><legend>Modo</legend><label className="flow-editor-choice-card"><input type="radio" checked readOnly /><span className="flow-editor-choice-icon">●</span><span><strong>Escolher apenas um</strong><small>Executa um IA Agente por solicitação.</small></span></label><label className="flow-editor-choice-card flow-editor-disabled"><input type="radio" disabled /><span className="flow-editor-choice-icon">○</span><span><strong>Permitir múltiplos</strong><small>Desabilitado por enquanto.</small></span></label></fieldset>
              <label className="flow-editor-field">Agente fallback<select value={fallbackId} onChange={(event) => onDraftChange({ fallback_agent_id: event.target.value })}><option value="">Sem fallback</option>{agentOptions.map((item) => <option key={item.id} value={item.id}>{getBuilderNodeTitle(item)}</option>)}</select></label>
              <section className="flow-editor-tab-section"><h4>Agentes disponíveis</h4><div className="flow-editor-subflow-list">{agentOptions.map((item) => { const checked = selectedAgentIds.includes(item.id); return <label key={item.id} className="flow-editor-choice-card"><input type="checkbox" checked={checked} onChange={(event) => onDraftChange({ agent_ids: event.target.checked ? Array.from(new Set([...selectedAgentIds, item.id])) : selectedAgentIds.filter((id) => id !== item.id) })} /><span className="flow-editor-choice-icon">☑</span><span><strong>{getBuilderNodeTitle(item)}</strong><small>ID persistido: {item.id}</small></span></label>; })}</div>{agentOptions.length === 0 ? <small className="flow-editor-error">Crie ao menos um IA Agente no fluxo.</small> : null}</section>
            </>
          );
        })()}

        {kind === 'delay' && (
          <>
            <label className="flow-editor-field">
              Tempo em segundos
              <input type="number" min="1" value={toText(draft.seconds)} onChange={(event) => onDraftChange({ seconds: parseDelaySeconds(event.target.value) ?? 0 })} />
            </label>
            <label className="flow-editor-radio">
              <input
                type="checkbox"
                checked={draft.show_typing === true}
                onChange={(event) => onDraftChange({ show_typing: event.target.checked })}
              />
              Mostrar digitando no WhatsApp
            </label>
            {draft.show_typing === true && (
              <label className="flow-editor-field">
                Tempo do digitando
                <select
                  value={toText(draft.typing_duration_mode || 'delay')}
                  onChange={(event) => onDraftChange({ typing_duration_mode: event.target.value })}
                >
                  <option value="delay">Usar duração do Delay</option>
                  <option value="auto">Automático pela próxima mensagem</option>
                </select>
              </label>
            )}
            <small className="flow-editor-help-text">Exibe o indicador de digitação para o cliente durante a espera.</small>
          </>
        )}

        {kind === 'media' && (() => {
          const rawMediaType = toText(draft.media_type || 'image');
          const mediaType = (['image', 'document', 'audio', 'video'].includes(rawMediaType) ? rawMediaType : 'image') as 'image' | 'document' | 'audio' | 'video';
          const mediaUrl = toText(draft.media_url);
          const urlInvalid = mediaUrl.trim().length > 0 && !mediaUrl.trim().startsWith('https://') && !mediaUrl.includes('{{');
          const sourceMode = toText(draft.media_source || (mediaUrl ? 'external' : 'upload')) === 'external' ? 'external' : 'upload';

          return (
            <>
              <div className="flow-editor-info-card"><strong>Tipo:</strong> Mídia WhatsApp <span>MEDIA</span></div>
              <label className="flow-editor-field">
                Tipo de mídia
                <select
                  value={mediaType}
                  onChange={(event) => onDraftChange({ media_type: event.target.value, ...(event.target.value !== 'document' ? { filename: '' } : {}), ...(event.target.value === 'audio' ? { caption: '' } : {}) })}
                >
                  <option value="image">Imagem</option>
                  <option value="document">Documento/PDF</option>
                  <option value="audio">Áudio</option>
                  <option value="video">Vídeo</option>
                </select>
              </label>
              <fieldset className="flow-editor-field">
                <legend>Origem do arquivo</legend>
                <label className="flow-editor-radio">
                  <input type="radio" name={`media-source-${node.id}`} checked={sourceMode === 'upload'} onChange={() => onDraftChange({ media_source: 'upload' })} />
                  Upload de arquivo
                </label>
                <label className="flow-editor-radio">
                  <input type="radio" name={`media-source-${node.id}`} checked={sourceMode === 'external'} onChange={() => onDraftChange({ media_source: 'external' })} />
                  URL externa
                </label>
              </fieldset>
              {sourceMode === 'upload' ? (
                <label className="flow-editor-field">
                  Arquivo
                  <input
                    type="file"
                    accept={mediaType === 'document' ? 'application/pdf' : mediaType === 'audio' ? '.mp3,.ogg,.opus,.wav,.aac,.m4a,audio/mpeg,audio/mp3,audio/ogg,audio/webm,audio/wav,audio/aac,audio/mp4' : mediaType === 'video' ? '.mp4,.3gp,.mov,video/mp4,video/3gpp,video/quicktime' : 'image/jpeg,image/png,image/webp'}
                    disabled={isUploading}
                    onChange={(event) => onUpload(event.target.files?.[0] || null, mediaType)}
                  />
                  {isUploading ? <small>Enviando arquivo...</small> : null}
                  {uploadError ? <small className="flow-editor-error">{uploadError}</small> : null}
                </label>
              ) : (
                <label className="flow-editor-field">
                  URL do arquivo (HTTPS)
                  <input
                    ref={mediaUrlRef}
                    value={mediaUrl}
                    onChange={(event) => onDraftChange({ media_url: event.target.value })}
                    placeholder={mediaType === 'document' ? 'https://exemplo.com/contrato.pdf' : mediaType === 'audio' ? 'https://exemplo.com/audio.mp3' : mediaType === 'video' ? 'https://exemplo.com/video.mp4' : 'https://exemplo.com/imagem.jpg'}
                  />
                  <VariableChips targetRef={mediaUrlRef} value={mediaUrl} onChange={(next) => onDraftChange({ media_url: next })} />
                  {!mediaUrl.trim() ? <small className="flow-editor-error">URL obrigatória para enviar a mídia.</small> : null}
                  {urlInvalid ? <small className="flow-editor-error">A URL deve começar com https:// ou conter variável</small> : null}
                </label>
              )}
              {mediaUrl && mediaType === 'image' ? (
                <div className="flow-editor-info-card"><img src={mediaUrl} alt="Preview da mídia" style={{ maxWidth: '100%', borderRadius: 12 }} /></div>
              ) : null}
              {mediaUrl && mediaType === 'document' ? (
                <div className="flow-editor-info-card"><strong>📄 PDF</strong><span>{toText(draft.filename) || 'Documento enviado'}</span></div>
              ) : null}
              {mediaUrl && mediaType === 'audio' ? (
                <div className="flow-editor-info-card"><audio controls src={mediaUrl} style={{ width: '100%' }}>Seu navegador não suporta áudio.</audio></div>
              ) : null}
              {mediaUrl && mediaType === 'video' ? (
                <div className="flow-editor-info-card"><video controls src={mediaUrl} style={{ width: '100%', borderRadius: 12 }}>Seu navegador não suporta vídeo.</video></div>
              ) : null}
              {mediaType !== 'audio' && (
                <label className="flow-editor-field">
                  Legenda/caption (opcional)
                  <textarea
                    ref={mediaCaptionRef}
                    value={toText(draft.caption)}
                    onChange={(event) => onDraftChange({ caption: event.target.value })}
                    placeholder={mediaType === 'document' ? 'Segue o PDF' : mediaType === 'video' ? 'Veja o vídeo' : 'Veja a imagem'}
                  />
                  <VariableChips targetRef={mediaCaptionRef} value={toText(draft.caption)} onChange={(next) => onDraftChange({ caption: next })} />
                </label>
              )}
              {mediaType === 'document' && (
                <label className="flow-editor-field">
                  Nome do arquivo (opcional)
                  <input
                    ref={mediaFilenameRef}
                    value={toText(draft.filename)}
                    onChange={(event) => onDraftChange({ filename: event.target.value })}
                    placeholder="contrato.pdf"
                  />
                  <VariableChips targetRef={mediaFilenameRef} value={toText(draft.filename)} onChange={(next) => onDraftChange({ filename: next })} />
                </label>
              )}
            </>
          );
        })()}

        {kind === 'action' && (() => {
          const selectedActionType = isActionType(toText(draft.action_type || draft.action)) ? (toText(draft.action_type || draft.action) as ActionType) : 'create_lead';
          const params = draft.params && typeof draft.params === 'object' ? (draft.params as Record<string, unknown>) : {};
          const updateActionParam = (key: string, value: string) => onDraftChange({ params: { ...params, [key]: value }, [key]: value });

          return (
            <>
              <label className="flow-editor-field">
                Tipo de Ação
                <select
                  value={selectedActionType}
                  onChange={(event) => {
                    const nextActionType = event.target.value;
                    onDraftChange({
                      action_type: nextActionType,
                      action: nextActionType,
                      params: {},
                      ...(nextActionType === 'set_conversation_mode' ? { mode: 'human' } : { mode: undefined }),
                      ...(nextActionType === 'notify_team' ? { notification_priority: 'normal', params: { notification_priority: 'normal' } } : {}),
                      ...(nextActionType === 'create_task' ? { task_priority: 'normal', task_due_minutes: '60', params: { task_priority: 'normal', task_due_minutes: '60' } } : {}),
                    });
                  }}
                >
                  {ACTION_TYPE_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>

              {selectedActionType === 'create_lead' && (
                <label className="flow-editor-field">
                  Nome do lead (opcional)
                  <input value={toText(params.lead_name || draft.lead_name)} onChange={(event) => updateActionParam('lead_name', event.target.value)} placeholder="Usar nome do contato se vazio" />
                </label>
              )}

              {selectedActionType === 'add_tag' && (
                <label className="flow-editor-field">
                  Tag
                  <input value={toText(params.tag || draft.tag)} onChange={(event) => updateActionParam('tag', event.target.value)} placeholder="Ex.: vip" />
                </label>
              )}

              {selectedActionType === 'notify_team' && (
                <>
                  <label className="flow-editor-field">
                    Título (opcional)
                    <input
                      ref={notificationTitleRef}
                      value={toText(params.notification_title || draft.notification_title)}
                      onChange={(event) => updateActionParam('notification_title', event.target.value)}
                      placeholder="Ex.: Financeiro"
                    />
                    <VariableChips targetRef={notificationTitleRef} value={toText(params.notification_title || draft.notification_title)} onChange={(next) => updateActionParam('notification_title', next)} />
                  </label>
                  <label className="flow-editor-field">
                    Mensagem (opcional)
                    <textarea
                      ref={notificationMessageRef}
                      value={toText(params.notification_message || draft.notification_message)}
                      onChange={(event) => updateActionParam('notification_message', event.target.value)}
                      placeholder="Ex.: Cliente aguardando pagamento."
                    />
                    <VariableChips targetRef={notificationMessageRef} value={toText(params.notification_message || draft.notification_message)} onChange={(next) => updateActionParam('notification_message', next)} />
                  </label>
                  <label className="flow-editor-field">
                    Prioridade
                    <select
                      value={isNotificationPriority(toText(params.notification_priority || draft.notification_priority)) ? toText(params.notification_priority || draft.notification_priority) : 'normal'}
                      onChange={(event) => updateActionParam('notification_priority', event.target.value)}
                    >
                      {NOTIFICATION_PRIORITY_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                </>
              )}


              {selectedActionType === 'create_task' && (
                <>
                  <label className="flow-editor-field">
                    Título
                    <input
                      ref={taskTitleRef}
                      value={toText(params.task_title || draft.task_title)}
                      onChange={(event) => updateActionParam('task_title', event.target.value)}
                      placeholder="Ex.: Retornar contato"
                    />
                    <VariableChips targetRef={taskTitleRef} value={toText(params.task_title || draft.task_title)} onChange={(next) => updateActionParam('task_title', next)} />
                  </label>
                  <label className="flow-editor-field">
                    Descrição
                    <textarea
                      ref={taskDescriptionRef}
                      value={toText(params.task_description || draft.task_description)}
                      onChange={(event) => updateActionParam('task_description', event.target.value)}
                      placeholder="Detalhes para o responsável"
                    />
                    <VariableChips targetRef={taskDescriptionRef} value={toText(params.task_description || draft.task_description)} onChange={(next) => updateActionParam('task_description', next)} />
                  </label>
                  <label className="flow-editor-field">
                    Prioridade
                    <select
                      value={isNotificationPriority(toText(params.task_priority || draft.task_priority)) ? toText(params.task_priority || draft.task_priority) : 'normal'}
                      onChange={(event) => updateActionParam('task_priority', event.target.value)}
                    >
                      {NOTIFICATION_PRIORITY_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>{option.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="flow-editor-field">
                    Responsável
                    <input
                      ref={taskAssigneeRef}
                      value={toText(params.task_assignee || draft.task_assignee)}
                      onChange={(event) => updateActionParam('task_assignee', event.target.value)}
                      placeholder="Nome, equipe ou e-mail"
                    />
                    <VariableChips targetRef={taskAssigneeRef} value={toText(params.task_assignee || draft.task_assignee)} onChange={(next) => updateActionParam('task_assignee', next)} />
                  </label>
                  <label className="flow-editor-field">
                    Prazo em minutos
                    <input
                      type="number"
                      min="0"
                      value={toText(params.task_due_minutes || draft.task_due_minutes || '60')}
                      onChange={(event) => updateActionParam('task_due_minutes', event.target.value)}
                      placeholder="60"
                    />
                  </label>
                </>
              )}

              {selectedActionType === 'transfer_human' && (
                <label className="flow-editor-field">
                  Motivo da transferência
                  <input ref={transferReasonRef} value={toText(params.reason || draft.reason)} onChange={(event) => updateActionParam('reason', event.target.value)} placeholder="Ex.: solicitou humano" />
                  <VariableChips targetRef={transferReasonRef} value={toText(params.reason || draft.reason)} onChange={(next) => updateActionParam('reason', next)} />
                </label>
              )}

              {selectedActionType === 'set_conversation_mode' && (
                <label className="flow-editor-field">
                  Modo
                  <select
                    value={isConversationMode(toText(draft.mode || params.mode)) ? toText(draft.mode || params.mode) : 'human'}
                    onChange={(event) => onDraftChange({ mode: event.target.value, params: { ...params, mode: event.target.value } })}
                  >
                    {CONVERSATION_MODE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
              )}
            </>
          );
        })()}

        {!isAiSystem ? (
          <label className="flow-editor-checkbox">
            <input type="checkbox" checked={!!draft.is_terminal} onChange={(event) => onDraftChange({ is_terminal: event.target.checked })} />
            Este é o fim do fluxo
          </label>
        ) : null}
        {uploadError ? <div className="flow-editor-error">{uploadError}</div> : null}
        {isUploading ? <div className="flow-editor-muted">Enviando arquivo...</div> : null}
      </div>
    </aside>
  );
}

type FlowBuilderClientProps = {
  flowId?: string;
};

type FlowSaveStatus = 'idle' | 'saving' | 'success' | 'error';

type PublishedSnapshot = { version_id?: string | null; version?: number | null; nodes?: unknown[]; edges?: unknown[]; nodes_count?: number; edges_count?: number; graph_hash?: string | null };
type RuntimeInspector = { flow_version_id?: string | null; session_id?: string | null; status?: string | null; current_node_id?: string | null; previous_node_id?: string | null; next_node_id?: string | null; nodes?: unknown[]; edges?: unknown[] };

const UNSAVED_CHANGES_MESSAGE = 'Você possui alterações não salvas. Deseja sair mesmo assim?';
const AUTOSAVE_DELAY_MS = 5000;

export default function FlowBuilderClient({ flowId: _initialFlowId }: FlowBuilderClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const flowIdFromUrl = searchParams.get('flow_id') || searchParams.get('flowId') || _initialFlowId || '';
  const [flows, setFlows] = useState<FlowListOption[]>([]);
  const [mcpTools, setMcpTools] = useState<MCPToolOption[]>([]);
  const normalizedFlows = useMemo(
    () =>
      flows.map((flow) => ({
        ...flow,
        is_active: !!flow.is_active,
      })),
    [flows],
  );
  const [selectedFlowId, setSelectedFlowId] = useState<string | null>(flowIdFromUrl || null);
  const [activeFlowId, setActiveFlowId] = useState<string | null>(null);
  const [isFlowSelectOpen, setIsFlowSelectOpen] = useState(false);
  const [isAgentSystemModalOpen, setIsAgentSystemModalOpen] = useState(false);
  const [activeAiSystemNodeId, setActiveAiSystemNodeId] = useState<string | null>(null);
  console.log('FLOW SELECIONADO:', selectedFlowId);
  console.log('FLOW ATIVO:', activeFlowId);
  console.log('FLOWS DISPONÍVEIS:', flows);
  const [editorNodes, setEditorNodes, onNodesChange] = useNodesState<Node>(initialNodes);
  const [editorEdges, setEditorEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
  const nodes = editorNodes;
  const edges = editorEdges;
  const setNodes = setEditorNodes;
  const setEdges = setEditorEdges;
  const [runtimeNodes, setRuntimeNodes] = useState<Node[]>([]);
  const [runtimeEdges, setRuntimeEdges] = useState<Edge[]>([]);
  const [publishedSnapshotNodes, setPublishedSnapshotNodes] = useState<Node[]>([]);
  const [publishedSnapshotEdges, setPublishedSnapshotEdges] = useState<Edge[]>([]);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingFlow, setIsLoadingFlow] = useState(false);
  const [isFlowHydrated, setIsFlowHydrated] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [flowSaveStatus, setFlowSaveStatus] = useState<FlowSaveStatus>('idle');
  const [messages, setMessages] = useState<Array<{ type: 'bot' | 'user'; text: string }>>([]);
  const [currentChoices, setCurrentChoices] = useState<Array<{ id?: string; label?: string; handleId?: string }>>([]);
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const selectedNodeIdRef = useRef<string | null>(null);
  const [nodeEditorDraft, setNodeEditorDraft] = useState<Record<string, unknown>>({});
  const [isMediaUploading, setIsMediaUploading] = useState(false);
  const [mediaUploadError, setMediaUploadError] = useState<string | null>(null);
  const [activeEdgeIds, setActiveEdgeIds] = useState<string[]>([]);
  const [isSimulatorOpen, setIsSimulatorOpen] = useState(false);
  const [isSidebarExpanded, setIsSidebarExpanded] = useState(false);
  const [openNodeGroups, setOpenNodeGroups] = useState<Record<NodePaletteGroup['id'], boolean>>(NODE_GROUPS_DEFAULT_OPEN);
  const [isMobileViewport, setIsMobileViewport] = useState(false);
  const [mobileView, setMobileView] = useState<'list' | 'map'>('list');
  const [isMobileAddOpen, setIsMobileAddOpen] = useState(false);
  const [isMobileValidationOpen, setIsMobileValidationOpen] = useState(false);
  const [mobileConnectSource, setMobileConnectSource] = useState<Node | null>(null);
  const [mobileConnectHandle, setMobileConnectHandle] = useState<string>('');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [userInputText, setUserInputText] = useState('');
  const [isVersionsModalOpen, setIsVersionsModalOpen] = useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [isRestoringVersion, setIsRestoringVersion] = useState(false);
  const [isCreatingFlow, setIsCreatingFlow] = useState(false);
  const [isCreateFlowOpen, setIsCreateFlowOpen] = useState(false);
  const [isRenameFlowOpen, setIsRenameFlowOpen] = useState(false);
  const [renameFlowName, setRenameFlowName] = useState('');
  const [flowVersions, setFlowVersions] = useState<FlowVersionItem[]>([]);
  const [analyticsOverlayEnabled, setAnalyticsOverlayEnabled] = useState(false);
  const [analyticsData, setAnalyticsData] = useState<FlowAnalytics | null>(null);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [flowSource, setFlowSource] = useState<string>('version');
  const [showEmptyFlowWarning, setShowEmptyFlowWarning] = useState(false);
  const [flowValidationError, setFlowValidationError] = useState<string | null>(null);
  const [validationWarnings, setValidationWarnings] = useState<FlowValidationIssue[]>([]);
  const [validationErrors, setValidationErrors] = useState<FlowValidationIssue[]>([]);
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [publishedSnapshot, setPublishedSnapshot] = useState<PublishedSnapshot | null>(null);
  const [runtimeInspector, setRuntimeInspector] = useState<RuntimeInspector | null>(null);
  const [isSnapshotPanelOpen, setIsSnapshotPanelOpen] = useState(false);
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const flowDirty = hasUnsavedChanges;
  const setFlowDirty = setHasUnsavedChanges;
  const skipDirtyCheckRef = useRef(true);
  const [isEditing] = useState(true);
  const simulationStartedRef = useRef(false);
  const createSimulationSessionId = () => ((typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : String(Date.now()));
  const simulationSessionIdRef = useRef<string>(createSimulationSessionId());
  const isLoadingFlowRef = useRef(false);
  const lastLoadedFlowIdRef = useRef<string | null>(null);
  const hasTriedAutoCreateRef = useRef(false);
  const nodesRef = useRef<Node[]>([]);
  const edgesRef = useRef<Edge[]>([]);
  const choiceConnectDebugRef = useRef<ChoiceConnectDebug | null>(null);
  const isSavingRef = useRef(false);
  const lastPersistedFlowSignatureRef = useRef<string | null>(null);
  const lastEditorHadAiSystemRef = useRef(false);
  const saveStatusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playbackIdRef = useRef(0);
  const isMountedRef = useRef(true);

  const flowSelectRef = useRef<HTMLDivElement | null>(null);
  const flowCanvasRef = useRef<HTMLElement | null>(null);
  const renameInputRef = useRef<HTMLInputElement | null>(null);
  const renameTriggerRef = useRef<HTMLButtonElement | null>(null);
  const selectedFlow = useMemo(
    () => normalizedFlows.find((flow) => flow.id === selectedFlowId) || null,
    [normalizedFlows, selectedFlowId],
  );
  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) || null,
    [nodes, selectedNodeId],
  );
  useEffect(() => {
    if (!selectedNode) return;
    setNodeEditorDraft((prev) => (Object.keys(prev).length === 0 ? { ...(selectedNode.data as Record<string, unknown>) } : prev));
  }, [selectedNode]);

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId]);

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1023px)');
    const update = () => setIsMobileViewport(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    const view = searchParams.get('view');
    if (view === 'map' || view === 'list') setMobileView(view);
    const nodeId = searchParams.get('node');
    if (nodeId && nodesRef.current.length) {
      const node = nodesRef.current.find((item) => item.id === nodeId);
      if (node) openNodeEditor(node);
    }
  // Selection hydration intentionally follows URL changes only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const getFlowBadge = useCallback((flow: { is_active?: boolean }) => (
    flow.is_active
      ? { label: 'Ativo', style: { background: '#DCFCE7', color: '#166534' } }
      : { label: 'Rascunho', style: { background: '#F3F4F6', color: '#6B7280' } }
  ), []);

  const toast = useMemo(() => ({
    success: (message: string) => {
      setToastMessage({ message, type: 'success' });
      setTimeout(() => setToastMessage(null), 4000);
    },
    error: (message: string) => {
      setToastMessage({ message, type: 'error' });
      setTimeout(() => setToastMessage(null), 4000);
    },
  }), []);

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

  const clearSaveStatusTimer = useCallback(() => {
    if (saveStatusTimeoutRef.current) {
      clearTimeout(saveStatusTimeoutRef.current);
      saveStatusTimeoutRef.current = null;
    }
  }, []);

  const markFlowDirty = useCallback((reason: string, details?: Record<string, unknown>) => {
    console.info('[NODE DIRTY]', { flow_id: selectedFlowId, reason, ...details });
    setFlowDirty(true);
    setFlowSaveStatus('idle');
  }, [selectedFlowId, setFlowDirty]);

  const confirmUnsavedNavigation = useCallback(() => {
    if (!flowDirty) return true;
    return window.confirm(UNSAVED_CHANGES_MESSAGE);
  }, [flowDirty]);

  const flowStatusIndicator = useMemo(() => {
    if (flowSaveStatus === 'saving') {
      return {
        label: 'Salvando...',
        className: 'flow-save-indicator flow-save-indicator-saving',
        title: 'Salvando alterações do fluxo.',
      };
    }

    if (flowDirty) {
      return {
        label: 'Não salvo',
        className: 'flow-save-indicator flow-save-indicator-dirty',
        title: 'Existem alterações locais ainda não publicadas.\nClique em Ativar para publicar o fluxo.',
      };
    }

    return null;
  }, [flowDirty, flowSaveStatus]);

  const saveButtonLabel = useMemo(() => {
    if (flowSaveStatus === 'saving') return 'Salvando...';
    if (flowSaveStatus === 'success') return 'Salvo';
    if (flowSaveStatus === 'error') return 'Erro ao salvar';
    return 'Salvar';
  }, [flowSaveStatus]);

  useEffect(() => () => {
    isMountedRef.current = false;
    clearSaveStatusTimer();
  }, [clearSaveStatusTimer]);

  useEffect(() => {
    console.log('[BUILDER FLOW_ID_FROM_URL]', flowIdFromUrl || null);
  }, [flowIdFromUrl]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    if (!selectedFlowId) {
      window.localStorage.removeItem('flow_builder_flow_id');
      return;
    }
    window.localStorage.setItem('flow_builder_flow_id', selectedFlowId);
  }, [selectedFlowId]);

  useEffect(() => {
    const sanitizedGraph = sanitizeAiSystemCanvasGraph(nodes, edges);
    if (sanitizedGraph.removedIds.size === 0) return;
    console.info('AI_SYSTEM_INTERNAL_NODES_REMOVED_FROM_CANVAS', {
      removed_canvas_nodes: Array.from(sanitizedGraph.removedIds),
    });
    setNodes(sanitizedGraph.nodes as Node[]);
    setEdges(sanitizedGraph.edges as Edge[]);
  }, [edges, nodes, setEdges, setNodes]);

  useEffect(() => {
    nodesRef.current = nodes;
    logFlowEditorSetGraph('react_flow_editor_nodes_state', nodes, edgesRef.current, selectedFlowId);
  }, [nodes, selectedFlowId]);
  useEffect(() => {
    edgesRef.current = edges;
    logFlowEditorSetGraph('react_flow_editor_edges_state', nodesRef.current, edges, selectedFlowId);
  }, [edges, selectedFlowId]);

  useEffect(() => {
    if (!isFlowHydrated) return;

    const savedSignature = lastPersistedFlowSignatureRef.current;
    const currentSignature = getFlowGraphSignature(serializeFlowGraph(nodes, edges));
    const dirty = !!savedSignature && currentSignature !== savedSignature;
    console.info('[DIRTY CHECK]', {
      flow_id: selectedFlowId,
      saved_signature: savedSignature,
      current_signature: currentSignature,
      dirty,
    });

    if (skipDirtyCheckRef.current) {
      skipDirtyCheckRef.current = false;
      setFlowDirty(dirty);
      if (dirty) setFlowSaveStatus('idle');
      return;
    }

    setFlowDirty(dirty);
    if (dirty) {
      console.info('[NODE DIRTY]', {
        flow_id: selectedFlowId,
        reason: 'graph_changed',
        nodes_count: nodes.length,
        edges_count: edges.length,
      });
      setFlowSaveStatus('idle');
    }
  }, [edges, isFlowHydrated, nodes, selectedFlowId, setFlowDirty]);

  const handleNodesChange = useCallback((changes: NodeChange[]) => {
    const removedNodeIds = changes.filter((change) => change.type === 'remove').map((change) => change.id);
    if (removedNodeIds.length > 0) {
      console.info('[FLOW NODE REMOVE]', {
        flow_id: selectedFlowId,
        removed_node_ids: removedNodeIds,
        state_nodes_before: nodesRef.current.map((node) => node.id),
      });
      markFlowDirty('node_removed', { removed_node_ids: removedNodeIds });
    }
    onNodesChange(changes);
  }, [markFlowDirty, onNodesChange, selectedFlowId]);

  const handleEdgesChange = useCallback((changes: EdgeChange[]) => {
    const removedEdgeIds = changes.filter((change) => change.type === 'remove').map((change) => change.id);
    if (removedEdgeIds.length > 0) {
      console.info('[FLOW EDGE REMOVE]', {
        flow_id: selectedFlowId,
        removed_edge_ids: removedEdgeIds,
        state_edges_before: edgesRef.current.map((edge) => edge.id),
      });
      markFlowDirty('edge_removed', { removed_edge_ids: removedEdgeIds });
    }
    onEdgesChange(changes);
  }, [markFlowDirty, onEdgesChange, selectedFlowId]);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!flowDirty) return;
      event.preventDefault();
      event.returnValue = UNSAVED_CHANGES_MESSAGE;
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [flowDirty]);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const handlePopState = () => {
      if (!flowDirty) return;
      if (window.confirm(UNSAVED_CHANGES_MESSAGE)) return;
      window.history.pushState(null, '', window.location.href);
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [flowDirty]);

  useEffect(() => {
    if (typeof document === 'undefined') return;

    const handleDocumentClick = (event: MouseEvent) => {
      if (!flowDirty) return;
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest('a[href]');
      if (!(anchor instanceof HTMLAnchorElement)) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      if (window.confirm(UNSAVED_CHANGES_MESSAGE)) return;

      event.preventDefault();
      event.stopPropagation();
    };

    document.addEventListener('click', handleDocumentClick, true);
    return () => document.removeEventListener('click', handleDocumentClick, true);
  }, [flowDirty]);

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
        const [data, mcpServersData, mcpToolsData] = await Promise.all([
          listFlows() as Promise<FlowListOption[]>,
          apiFetch('/api/mcp/servers').then((response) => parseApiResponse<MCPServerOption[]>(response)).catch(() => []),
          apiFetch('/api/mcp/tools').then((response) => parseApiResponse<MCPToolOption[]>(response)).catch(() => []),
        ]);
        const safeFlows = Array.isArray(data) ? data : [];
        const serverNames = new Map((Array.isArray(mcpServersData) ? mcpServersData : []).map((server) => [server.id, server.name || 'Integração MCP']));
        const safeMcpTools = filterGoogleSheetsTools((Array.isArray(mcpToolsData) ? mcpToolsData : []).map((tool) => ({ ...tool, server_name: tool.server_name || serverNames.get(String(tool.server_id || '')) || 'Integração MCP' })));
        if (!active) return;
        setFlows(safeFlows);
        setMcpTools(safeMcpTools);
        const safeMcpToolIds = new Set(safeMcpTools.map((tool) => tool.id));
        setNodes((currentNodes) => currentNodes.map((currentNode) => {
          const data = (currentNode.data || {}) as Record<string, unknown>;
          const currentIds = Array.isArray(data.mcp_tool_ids) ? data.mcp_tool_ids.map(String) : [];
          const nextIds = currentIds.filter((toolId) => safeMcpToolIds.has(toolId));
          return nextIds.length === currentIds.length ? currentNode : ({ ...currentNode, data: { ...data, mcp_tool_ids: nextIds, allow_mcp_tools: nextIds.length > 0 } } as unknown as typeof currentNode);
        }));

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

  const handleCreateFlow = useCallback(() => {
    setIsCreateFlowOpen(true);
  }, []);

  const handleFlowCreated = useCallback((flowId: string, flowName?: string | null) => {
    console.info('[FLOW CREATED CALLBACK]', { flow_id: flowId, flow_name: flowName });
    setSelectedFlowId(flowId);
  }, []);

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

  const openAiSystemModal = useCallback((nodeId: string) => {
    const node = nodes.find((item) => item.id === nodeId);
    const data = (node?.data || {}) as Record<string, unknown>;
    console.info('AI_SYSTEM_MODAL_OPENED', { system_id: data.system_id || nodeId, system_type: data.system_type || 'custom' });
    setActiveAiSystemNodeId(nodeId);
  }, [nodes]);

  const openNodeEditor = useCallback((node: Node, source: 'doubleClick' = 'doubleClick') => {
    const canvasWidthBefore = flowCanvasRef.current?.getBoundingClientRect().width ?? 0;
    console.info('[NODE DOUBLE CLICK]', { node_id: node.id, node_type: node.type, source });
    console.info('[FLOW CANVAS WIDTH BEFORE]', canvasWidthBefore);

    if (selectedNodeIdRef.current === node.id) {
      console.info('[NODE PANEL OPEN]', { node_id: node.id, node_type: node.type, source, skipped: 'already-open' });
      console.info('[DRAWER MODE ACTIVE]', { node_id: node.id, width: 420 });
      requestAnimationFrame(() => {
        console.info('[FLOW CANVAS WIDTH AFTER]', flowCanvasRef.current?.getBoundingClientRect().width ?? 0);
      });
      return;
    }

    selectedNodeIdRef.current = node.id;
    console.info('[NODE PANEL OPEN]', { node_id: node.id, node_type: node.type, source });
    setSelectedNodeId(node.id);
    setNodeEditorDraft({ ...((node.data || {}) as Record<string, unknown>) });
    setMediaUploadError(null);
  }, []);

  const closeNodeEditor = useCallback(() => {
    selectedNodeIdRef.current = null;
    setSelectedNodeId(null);
    setNodeEditorDraft({});
    setMediaUploadError(null);
  }, []);

  useEffect(() => {
    if (!selectedNodeId) return;

    console.info('[DRAWER MODE ACTIVE]', { node_id: selectedNodeId, width: 420 });
    requestAnimationFrame(() => {
      console.info('[FLOW CANVAS WIDTH AFTER]', flowCanvasRef.current?.getBoundingClientRect().width ?? 0);
    });
  }, [selectedNodeId]);

  const handleNodeEditorDraftChange = useCallback((patch: Record<string, unknown>) => {
    const nodeId = selectedNodeIdRef.current;
    console.info('[NODE CHANGED]', { node_id: nodeId, patch_keys: Object.keys(patch) });
    setNodeEditorDraft((prev) => ({ ...prev, ...patch }));
    if (nodeId) {
      updateNodeData(nodeId, patch);
      markFlowDirty('node_changed', { node_id: nodeId, patch_keys: Object.keys(patch) });
    }
  }, [markFlowDirty, updateNodeData]);

  const handleReactFlowNodeDoubleClick = useCallback((_: unknown, node: Node) => {
    openNodeEditor(node, 'doubleClick');
  }, [openNodeEditor]);

  const uploadEditorMedia = useCallback(async (file: File | null, mediaType: 'image' | 'document' | 'audio' | 'video') => {
    if (!file) return;
    setMediaUploadError(null);
    setIsMediaUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await apiFetch('/api/media/upload', { method: 'POST', body: formData });
      const result = await parseApiResponse<{ url: string; filename?: string; mime_type?: string; size?: number }>(response);
      const uploadedUrl = String(result.url || '').trim();
      if (!uploadedUrl.startsWith('https://')) {
        throw new Error(INVALID_UPLOAD_PUBLIC_URL_MESSAGE);
      }
      const resolvedMediaType = result.mime_type === 'application/pdf' ? 'document' : result.mime_type?.startsWith('audio/') ? 'audio' : result.mime_type?.startsWith('video/') ? 'video' : mediaType;
      const patch = {
        media_type: resolvedMediaType,
        media_url: uploadedUrl,
        filename: resolvedMediaType === 'document' ? (result.filename || nodeEditorDraft.filename) : '',
        caption: resolvedMediaType === 'audio' ? '' : nodeEditorDraft.caption,
      };
      setNodeEditorDraft((prev) => ({
        ...prev,
        ...patch,
      }));
      const nodeId = selectedNodeIdRef.current;
      if (nodeId) {
        console.info('[NODE CHANGED]', { node_id: nodeId, patch_keys: Object.keys(patch), media_type: mediaType });
        updateNodeData(nodeId, patch);
        markFlowDirty('media_uploaded', { node_id: nodeId, media_type: mediaType, url: uploadedUrl });
      }
    } catch (error) {
      setMediaUploadError(error instanceof Error ? error.message : 'Não foi possível enviar o arquivo. Verifique o tipo, tamanho e tente novamente.');
    } finally {
      setIsMediaUploading(false);
    }
  }, [markFlowDirty, nodeEditorDraft.filename, updateNodeData]);

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
          ...(node.type === 'delay' && node.seconds !== undefined ? { seconds: node.seconds } : {}),
          isStart: node.data?.isStart ?? false,
          buttons: node.type === 'choice' ? normalizeChoiceButtons(node.id, node.data?.buttons) : node.data?.buttons,
          label: node.data?.label || node.data?.content || `Node ${node.id}`,
          onChange: updateNodeData,
          onToggleStart: toggleStartNode,
          onOpenSystem: openAiSystemModal,
        hasValidationError: node.id === highlightedNodeId,
        },
      };
    },
    [openAiSystemModal, toggleStartNode, updateNodeData],
  );

  const applyLayoutAndSetFlow = useCallback((nextNodes: Node[], nextEdges: Edge[]) => {
    if (nextNodes.length === 0) {
      setNodes(nextNodes);
      setEdges(nextEdges);
      return { nodes: nextNodes, edges: nextEdges };
    }

    const orderedEdges = orderChoiceChildrenEdges(nextNodes, nextEdges);
    const { nodes: layoutedNodes, edges: layoutedEdges } = getLayoutedElements(nextNodes, orderedEdges);
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
    requestAnimationFrame(() => { rfInstance?.fitView(); });
    return { nodes: layoutedNodes, edges: layoutedEdges };
  }, [rfInstance, setEdges, setNodes]);

  const loadFlow = useCallback(async (flowId: string | null) => {
    try {
      if (!flowId) {
        setNodes([]);
        setEdges([]);
        setIsFlowHydrated(true);
        setIsLoadingFlow(false);
        setShowEmptyFlowWarning(false);
        setFlowSource('none');
        setFlowDirty(false);
        setFlowSaveStatus('idle');
        setOperationError('Nenhum fluxo selecionado para carregar.');
        return;
      }

      console.info('[BUILDER HYDRATION START]', { flow_id: flowId });
      isLoadingFlowRef.current = true;
      skipDirtyCheckRef.current = true;
      setFlowDirty(false);
      setFlowSaveStatus('idle');
      setIsLoading(true);
      setIsLoadingFlow(true);
      setIsFlowHydrated(false);
      setOperationError(null);
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
        throw new Error('Payload vazio ao carregar flow.');
        return;
      }
      const payload = data as {
        id?: string;
        source?: string;
        version_id?: string | null;
        current_version_id?: string | null;
        published_version_id?: string | null;
        current_version?: { nodes?: unknown[] | null } | null;
        raw_nodes?: unknown[] | null;
        editor_graph?: { nodes?: unknown[] | null; edges?: unknown[] | null } | null;
        runtime_graph?: { nodes?: unknown[] | null; edges?: unknown[] | null } | null;
        published_snapshot_graph?: { nodes?: unknown[] | null; edges?: unknown[] | null } | null;
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
      const resolvedSource = payload?.source || 'editor';
      const hydrationSource: FlowHydrationSource = shouldBlockEditorHydrationSource(resolvedSource)
        ? (resolvedSource as FlowHydrationSource)
        : 'editor';
      setFlowSource(resolvedSource);
      setShowEmptyFlowWarning(!safeNodes || safeNodes.length === 0);
      console.info('[BUILDER LOAD]', {
        flow_id: flowId,
        version_id: payload?.current_version_id || payload?.published_version_id || payload?.version_id || null,
        nodes_count: safeNodes.length,
        edges_count: safeEdges.length,
      });
      console.info('[BUILDER SOURCE]', {
        source: resolvedSource,
        nodes_count: safeNodes.length,
        edges_count: safeEdges.length,
        version_id: payload?.current_version_id || payload?.published_version_id || payload?.version_id || null,
      });

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

      logFlowEditorHydrationSource(hydrationSource, formattedNodes, formattedEdges, flowId);
      if (shouldBlockEditorHydrationSource(hydrationSource)) {
        logBlockedRuntimeGraphEditorHydration(hydrationSource, formattedNodes, formattedEdges, flowId);
        toast.error('Snapshot de runtime bloqueado. Mantendo grafo visual original.');
        setOperationError('O Builder bloqueou a hidratação do canvas a partir de um grafo runtime/publicado. Mantendo o grafo visual original.');
        return;
      }

      const sanitizedLoadedGraph = sanitizeAiSystemCanvasGraph(formattedNodes, formattedEdges);
      if (sanitizedLoadedGraph.removedIds.size > 0) {
        console.info('FLOW_EDITOR_RUNTIME_NODES_FILTERED', {
          source: 'editor_graph_sanitizer',
          flow_id: flowId,
          ...getFlowHydrationStats(formattedNodes, formattedEdges),
          removed_canvas_nodes: Array.from(sanitizedLoadedGraph.removedIds),
        });
      }
      const nodesToRender = sanitizedLoadedGraph.nodes as Node[];
      let edgesToRender = sanitizedLoadedGraph.edges as Edge[];
      if (nodesToRender.length === 0) {
        console.info('[BUILDER EMPTY FLOW]', { flow_id: flowId, nodes_count: 0, edges_count: edgesToRender.length });
        logFlowEditorHydrationSource('editor', [], [], flowId);
        setNodes([]);
        setEdges([]);
        setOperationError(null);
        setFlowValidationError(null);
        setValidationWarnings([]);
        setValidationErrors([]);
        lastPersistedFlowSignatureRef.current = getFlowGraphSignature(serializeFlowGraph([], []));
        lastEditorHadAiSystemRef.current = false;
        return;
      }

      const hasStoredPositions = nodesToRender.some((n) => n.position && (n.position.x !== 0 || n.position.y !== 0));
      if (hasStoredPositions) {
        const orderedEdges = orderChoiceChildrenEdges(nodesToRender, edgesToRender);
        logFlowEditorSetGraph('editor_graph', nodesToRender, orderedEdges, flowId);
        setNodes(nodesToRender);
        setEdges(orderedEdges);
        lastPersistedFlowSignatureRef.current = getFlowGraphSignature(serializeFlowGraph(nodesToRender, orderedEdges));
        lastEditorHadAiSystemRef.current = nodesToRender.some((node) => node.type === 'ai_system');
        requestAnimationFrame(() => { rfInstance?.fitView(); });
      } else {
        const layoutedFlow = applyLayoutAndSetFlow(nodesToRender, edgesToRender);
        lastPersistedFlowSignatureRef.current = getFlowGraphSignature(serializeFlowGraph(layoutedFlow.nodes, layoutedFlow.edges));
        lastEditorHadAiSystemRef.current = layoutedFlow.nodes.some((node) => node.type === 'ai_system');
      }
    } catch (err) {
      console.error('Erro ao carregar flow', err);
      setSelectedFlowId(null);
      setNodes([]);
      setEdges([]);
      setFlowSource('error');
      setShowEmptyFlowWarning(false);
      setOperationError(err instanceof Error ? err.message : 'Falha ao carregar fluxo no Builder.');
    } finally {
      isLoadingFlowRef.current = false;
      console.info('[BUILDER HYDRATION COMPLETE]');
      console.info('nodes_count=', nodesRef.current.length);
      console.info('edges_count=', edgesRef.current.length);
      setIsFlowHydrated(true);
      setIsLoadingFlow(false);
      setIsLoading(false);
    }
  }, [applyLayoutAndSetFlow, buildFlowEdge, buildFlowNode, rfInstance, setEdges, setNodes, toast]);

  const shouldRenderEmptyState = !isLoadingFlow && isFlowHydrated && nodes.length === 0;

  useEffect(() => {
    if (shouldRenderEmptyState) {
      console.info('[EMPTY STATE RENDERED]');
      console.info('nodes_count=', nodes.length);
      console.info('edges_count=', edges.length);
    }
  }, [edges.length, nodes.length, shouldRenderEmptyState]);

  useEffect(() => {
    if (normalizedFlows.length === 0) return;

    const firstFlowId = normalizedFlows[0]?.id || null;
    const currentActiveFlow = normalizedFlows.find((flow) => flow.is_active);
    const resolvedActiveFlowId = currentActiveFlow?.id || null;
    const initialFlowId = flowIdFromUrl || resolvedActiveFlowId || firstFlowId;

    if (flowIdFromUrl && normalizedFlows.some((flow) => flow.id === flowIdFromUrl)) {
      console.log('[BUILDER SELECTED_FLOW_ID]', flowIdFromUrl);
      setSelectedFlowId((prev) => (prev === flowIdFromUrl ? prev : flowIdFromUrl));
      if (lastLoadedFlowIdRef.current !== flowIdFromUrl) {
        console.log('[BUILDER LOAD FLOW]', flowIdFromUrl);
        void loadFlow(flowIdFromUrl);
      }
      return;
    }

    if (!flowIdFromUrl && initialFlowId) {
      console.log('[BUILDER USING ACTIVE FALLBACK]', initialFlowId);
      console.log('[BUILDER SELECTED_FLOW_ID]', initialFlowId);
      setSelectedFlowId((prev) => (prev === initialFlowId ? prev : initialFlowId));
      if (lastLoadedFlowIdRef.current !== initialFlowId) {
        console.log('[BUILDER LOAD FLOW]', initialFlowId);
        void loadFlow(initialFlowId);
      }
      return;
    }

    if (selectedFlowId && !normalizedFlows.find((flow) => flow.id === selectedFlowId)) {
      setSelectedFlowId(null);
    }
  }, [flowIdFromUrl, loadFlow, normalizedFlows, selectedFlowId]);

  useEffect(() => {
    if (!flows || flows.length === 0) {
      setSelectedFlowId(null);
      lastLoadedFlowIdRef.current = null;
      setNodes([]);
      setEdges([]);
    }
  }, [flows, setEdges, setNodes]);

  const handleSelectFlow = useCallback(async (flowId: string) => {
    if (flowId !== selectedFlowId && !confirmUnsavedNavigation()) return;
    console.log('[BUILDER SELECTED_FLOW_ID]', flowId);
    setSelectedFlowId(flowId);
    setIsFlowSelectOpen(false);
    router.replace(`/dashboard/flow-builder?flow_id=${flowId}`);
    console.log('[BUILDER LOAD FLOW]', flowId);
    await loadFlow(flowId);
  }, [confirmUnsavedNavigation, loadFlow, router, selectedFlowId]);

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

  const wait = useCallback((ms: number) => new Promise<void>((resolve) => {
    setTimeout(resolve, ms);
  }), []);

  const randomBetween = useCallback((min: number, max: number) => Math.floor(Math.random() * (max - min + 1)) + min, []);

  const playBotResponses = useCallback(async (
    events: Array<{ type?: string; text?: string; seconds?: number }>,
    playbackId: number,
  ) => {
    try {
      for (const event of events) {
        if (playbackIdRef.current !== playbackId || !isMountedRef.current) return;

        if (event?.type === 'delay') {
          const seconds = Number(event.seconds) || 0;
          if (seconds > 0) {
            await wait(seconds * 1000);
            if (playbackIdRef.current !== playbackId || !isMountedRef.current) return;
          }
          continue;
        }

        if (event?.type === 'message' || event?.type === 'send_message') {
          const text = String(event.text || '').trim();
          if (text) {
            if (!isMountedRef.current) return;
            setIsTyping(true);
            await wait(randomBetween(600, 1200));
            if (playbackIdRef.current !== playbackId || !isMountedRef.current) return;
            setIsTyping(false);
            setMessages((prev) => [...prev, { type: 'bot', text }]);
          }
        }
      }
    } finally {
      if (isMountedRef.current && playbackIdRef.current === playbackId) {
        setIsTyping(false);
      }
    }
  }, [randomBetween, wait]);

  const runFlowStep = useCallback(async (userMessage: string) => {
    if (!selectedFlowId || isProcessing) return;

    const playbackId = playbackIdRef.current + 1;
    playbackIdRef.current = playbackId;
    setMessages((prev) => [...prev, { type: 'user', text: userMessage }]);
    const hasAiSystem = nodesRef.current.some((node) => node.type === 'ai_system');
    if (hasAiSystem) console.info('AI_SYSTEM_RUNTIME_STARTED', { flow_id: selectedFlowId, session_id: simulationSessionIdRef.current });
    setIsProcessing(true);

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
        setMessages((prev) => [...prev, { type: 'bot', text: `${statusBadge} ${friendlyMessage}` }]);
        return;
      }

      const data = await parseApiResponse<any>(response);
      const events = Array.isArray(data?.events) ? data.events : [];
      const backendMessages = Array.isArray(data?.messages)
        ? data.messages.map((item: unknown) => (typeof item === 'string' ? item.trim() : '')).filter(Boolean)
        : [];
      const fallbackReply = typeof data?.reply === 'string' ? data.reply : '';
      const fallbackEvents = backendMessages.length > 0
        ? backendMessages.map((text: string) => ({ type: 'send_message', text }))
        : (fallbackReply ? [{ type: 'send_message', text: fallbackReply }] : [{ type: 'send_message', text: 'Simulação concluída sem resposta textual.' }]);
      await playBotResponses(events.length > 0 ? events : fallbackEvents, playbackId);
      if (playbackIdRef.current !== playbackId || !isMountedRef.current) return;
      setCurrentNodeId(data.next_node_id || null);
      setCurrentChoices([]);
      const active = flow.edges
        .filter((e) => e.source === data.current_node_id && data.selected_edge !== null && (e.sourceHandle === data.selected_edge || (e.data as any)?.sourceHandle === data.selected_edge))
        .map((e) => e.id)
        .filter(Boolean) as string[];
      setActiveEdgeIds(active);
    } catch (error) {
      console.error('[SIMULATOR ERROR] failed to fetch', error);
      if (isMountedRef.current && playbackIdRef.current === playbackId) {
        setMessages((prev) => [...prev, { type: 'bot', text: 'Não foi possível iniciar o simulador' }]);
      }
    } finally {
      if (nodesRef.current.some((node) => node.type === 'ai_system')) console.info('AI_SYSTEM_RUNTIME_FINISHED', { flow_id: selectedFlowId, session_id: simulationSessionIdRef.current });
      if (isMountedRef.current && playbackIdRef.current === playbackId) {
        setIsProcessing(false);
      }
    }
  }, [flow.edges, isProcessing, playBotResponses, selectedFlowId]);

  const handleChoiceClick = useCallback((handleId: string, label: string) => {
    void runFlowStep(label);
  }, [runFlowStep]);

  const handleUserTextInput = useCallback((text: string) => {
    void runFlowStep(text);
  }, [runFlowStep]);

  const getChoiceHandleDebug = useCallback((nodeId?: string | null, handleId?: string | null, handleType?: string | null) => {
    const node = nodesRef.current.find((item) => item.id === nodeId);
    if (!node || node.type !== 'choice') return null;

    const buttons = Array.isArray((node.data as { buttons?: unknown }).buttons)
      ? ((node.data as { buttons?: Array<{ id?: string; label?: string; value?: string; handleId?: string }> }).buttons || [])
      : [];
    const option = buttons.find((button) => button.handleId === handleId);

    return {
      nodeId: node.id,
      handleId: handleId || null,
      handleType: handleType || null,
      id: handleId || null,
      type: handleType || null,
      isConnectable: node.connectable ?? true,
      optionValue: option?.value || option?.label || option?.id || handleId || undefined,
      option_value: option?.value || option?.label || option?.id || handleId || undefined,
    };
  }, []);

  const onConnectStart = useCallback((_event: unknown, params: { nodeId?: string | null; handleId?: string | null; handleType?: string | null }) => {
    const debug = getChoiceHandleDebug(params.nodeId, params.handleId, params.handleType);
    if (!debug) return;

    choiceConnectDebugRef.current = {
      nodeId: debug.nodeId,
      handleId: debug.handleId,
      handleType: debug.handleType,
      optionValue: debug.optionValue,
      isConnectable: debug.isConnectable,
      completed: false,
    };
    console.debug('[CHOICE CONNECT START]', debug);
  }, [getChoiceHandleDebug]);

  const onConnectEnd = useCallback(() => {
    const pending = choiceConnectDebugRef.current;
    if (!pending) return;

    console.debug('[CHOICE CONNECT END]', {
      node_id: pending.nodeId,
      id: pending.handleId,
      type: pending.handleType,
      isConnectable: pending.isConnectable,
      option_value: pending.optionValue,
      completed: !!pending.completed,
    });
    choiceConnectDebugRef.current = null;
  }, []);

  const onConnect = useCallback((params: FlowConnection) => {
    const sourceHandle = params.sourceHandle?.toString() || null;
    const source = safeString(params.source);
    const target = safeString(params.target);
    const targetHandle = safeString(params.targetHandle);
    const choiceDebug = getChoiceHandleDebug(source, sourceHandle, 'source');
    if (choiceDebug) {
      choiceConnectDebugRef.current = {
        nodeId: choiceDebug.nodeId,
        handleId: choiceDebug.handleId,
        handleType: choiceDebug.handleType,
        optionValue: choiceDebug.optionValue,
        isConnectable: choiceDebug.isConnectable,
        completed: true,
      };
      console.debug('[CHOICE CONNECT END]', {
        ...choiceDebug,
        target,
        targetHandle,
        completed: true,
      });
    }

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
    markFlowDirty('edge_added', { source, target, source_handle: sourceHandle });
  }, [getChoiceHandleDebug, markFlowDirty, setEdges]);


  const addNode = useCallback(
    (kind: FlowNodeKind) => {
      const preset = NODE_PRESETS[kind];

      // Usa o centro visível atual do viewport do ReactFlow
      // screenToFlowPosition converte coordenadas de tela para coordenadas do flow
      // O canvas ocupa a área entre a sidebar (240px) e o simulador (quando aberto)
      const simWidth = isSimulatorOpen ? 320 : 0;
      const canvasLeft = 240;
      const canvasRight = window.innerWidth - simWidth;
      const canvasCenterScreenX = (canvasLeft + canvasRight) / 2;
      const canvasCenterScreenY = window.innerHeight / 2;

      const flowPosition = rfInstance?.screenToFlowPosition({
        x: canvasCenterScreenX,
        y: canvasCenterScreenY,
      }) || randomPosition();

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
      markFlowDirty('node_added', { node_id: newNode.id, node_type: newNode.type });
      return newNode;
    },
    [markFlowDirty, rfInstance, isSimulatorOpen, setNodes, toggleStartNode, updateNodeData],
  );

  const handleCreateInitialMessage = useCallback(() => {
    const startNode: Node = {
      id: makeNodeId(),
      type: 'message',
      position: { x: 160, y: 120 },
      data: {
        label: 'Mensagem inicial',
        content: 'Olá! Como posso te ajudar?',
        isStart: true,
        onChange: updateNodeData,
        onToggleStart: toggleStartNode,
        hasValidationError: false,
      },
    };

    setNodes([startNode]);
    setEdges([]);
    setShowEmptyFlowWarning(false);
  }, [setEdges, setNodes, toggleStartNode, updateNodeData]);

  const handleUseSimpleTemplate = useCallback(() => {
    const startId = crypto.randomUUID();
    const conditionId = crypto.randomUUID();
    const yesId = crypto.randomUUID();
    const noId = crypto.randomUUID();

    const templateNodes: Node[] = [
      { id: startId, type: 'message', position: { x: 100, y: 200 }, data: { label: 'Mensagem inicial', title: 'Mensagem inicial', content: 'Olá! Como posso te ajudar?', text: 'Olá! Como posso te ajudar?', message: 'Olá! Como posso te ajudar?', isStart: true, onChange: updateNodeData, onToggleStart: toggleStartNode, hasValidationError: false } },
      { id: conditionId, type: 'condition', position: { x: 420, y: 200 }, data: { label: 'Condição', title: 'Condição', condition: 'sim, suporte, ajuda, atendimento, humano', question: 'sim, suporte, ajuda, atendimento, humano', keywords: ['sim', 'suporte', 'ajuda', 'atendimento', 'humano'], text: 'sim, suporte, ajuda, atendimento, humano', helper: 'Separe múltiplas palavras por vírgula. Match se a mensagem contiver qualquer uma.', description: 'Separe múltiplas palavras por vírgula. Match se a mensagem contiver qualquer uma.', positive: ['sim', 'suporte', 'ajuda', 'atendimento', 'humano'], matchType: 'contains', onChange: updateNodeData, onToggleStart: toggleStartNode, hasValidationError: false } },
      { id: yesId, type: 'message', position: { x: 760, y: 100 }, data: { label: 'Resposta A', title: 'Resposta A', content: 'Perfeito! Vou te direcionar para o suporte.', text: 'Perfeito! Vou te direcionar para o suporte.', message: 'Perfeito! Vou te direcionar para o suporte.', is_terminal: true, isEnd: true, isFinal: true, endFlow: true, onChange: updateNodeData, onToggleStart: toggleStartNode, hasValidationError: false } },
      { id: noId, type: 'message', position: { x: 760, y: 320 }, data: { label: 'Resposta B', title: 'Resposta B', content: 'Sem problemas! Posso te mostrar nossos planos.', text: 'Sem problemas! Posso te mostrar nossos planos.', message: 'Sem problemas! Posso te mostrar nossos planos.', is_terminal: true, isEnd: true, isFinal: true, endFlow: true, onChange: updateNodeData, onToggleStart: toggleStartNode, hasValidationError: false } },
    ];

    const templateEdges: Edge[] = [
      { id: crypto.randomUUID(), source: startId, target: conditionId, sourceHandle: 'default', type: 'default', label: '', data: { sourceHandle: 'default' } },
      { id: crypto.randomUUID(), source: conditionId, target: yesId, sourceHandle: 'true', type: 'default', label: 'sim', data: { condition: 'sim', sourceHandle: 'true' } },
      { id: crypto.randomUUID(), source: conditionId, target: noId, sourceHandle: 'false', type: 'default', label: 'não', data: { condition: 'não', sourceHandle: 'false' } },
    ];

    setNodes(templateNodes);
    setEdges(templateEdges);
    setShowEmptyFlowWarning(false);
    toast.success('Template simples aplicado');
    console.log('[TEMPLATE SIMPLE APPLIED]');
    console.log('[TEMPLATE GENERATED UUID IDS]');
    console.log('node_ids=', templateNodes.map((node) => node.id));
    console.log('edge_pairs=', templateEdges.map((edge) => `${edge.source}->${edge.target}`));
    console.log('nodes_count=', templateNodes.length);
    console.log('edges_count=', templateEdges.length);
    setTimeout(() => {
      rfInstance?.fitView({ padding: 0.2, duration: 500 });
    }, 0);
  }, [rfInstance, setEdges, setNodes, toast, toggleStartNode, updateNodeData]);


  const handleInsertAgentSystemTemplate = useCallback((templateId: string) => {
    const template = AGENT_SYSTEM_TEMPLATES.find((item) => item.id === templateId) || AGENT_SYSTEM_TEMPLATES[0];
    const card = AI_SYSTEM_CARDS.find((item) => item.id === templateId);
    const origin = rfInstance?.screenToFlowPosition({ x: 360, y: 180 }) || { x: 120, y: 120 };
    const graph = template && template.nodes.length > 0 ? instantiateAgentSystemTemplate(template, makeNodeId, { x: 0, y: 0 }) : { nodes: [], edges: [] };
    const systemId = makeNodeId();
    const systemName = card?.title.replace(/^[^A-Za-zÀ-ÿ0-9]+\s*/, '') || template?.name || 'Sistema Personalizado';
    const systemNode: Node = {
      id: systemId,
      type: 'ai_system',
      position: origin,
      data: {
        label: systemName,
        name: systemName,
        description: template?.description || card?.subtitle || '',
        system_id: systemId,
        system_type: templateId,
        collapsed: true,
        internal_nodes: graph.nodes.map((node) => ({ ...node, position: node.position || { x: 0, y: 0 } })),
        internal_edges: graph.edges,
        version: template?.version || '1.0.0',
        model_override: '',
        temperature: 0.2,
        memory_enabled: true,
        tools: template?.required_tools?.length ? template.required_tools : ['Google Calendar', 'Google Drive', 'Responder', 'DateResolver', 'Fallback'],
        integrations: template?.required_integrations?.length ? template.required_integrations : ['google_calendar'],
        language: 'pt-BR',
        timezone: 'America/Sao_Paulo',
        logs_enabled: true,
        global_prompt: '',
        isEnd: true,
        end: true,
        terminal: true,
        is_final: true,
        statuses: ['Saudação', 'Agenda', 'Consulta', 'Cancelamento'],
        onChange: updateNodeData,
        onToggleStart: toggleStartNode,
        hasValidationError: false,
      },
    };
    setNodes((current) => [...current, systemNode]);
    setShowEmptyFlowWarning(false);
    setIsAgentSystemModalOpen(false);
    toast.success(`Sistema IA inserido: ${systemName}`);
    console.info('AI_SYSTEM_CREATED', { system_id: systemId, system_type: templateId, internal_nodes: graph.nodes.length, internal_edges: graph.edges.length });
    setTimeout(() => rfInstance?.fitView({ padding: 0.2, duration: 500 }), 0);
  }, [rfInstance, setNodes, toast, toggleStartNode, updateNodeData]);

  const getCurrentSerializedFlow = useCallback(() => {
    const realFlow = rfInstance?.toObject?.();
    const realFlowNodes = Array.isArray(realFlow?.nodes) ? (realFlow.nodes as Node[]) : nodesRef.current;
    const realFlowEdges = Array.isArray(realFlow?.edges) ? (realFlow.edges as Edge[]) : edgesRef.current;
    return serializeFlowGraph(realFlowNodes, realFlowEdges);
  }, [rfInstance]);

  const handleSaveFlow = useCallback(async (requireConfirmOverwrite = false, options?: { autosave?: boolean; showToast?: boolean }) => {
    const isAutosave = !!options?.autosave;
    const shouldShowToast = options?.showToast ?? !isAutosave;

    if (!selectedFlowId) {
      console.error('[FLOW SAVE ERROR]', { reason: 'selectedFlowId não definido' });
      setFlowSaveStatus('error');
      return;
    }

    const rawFlow = getCurrentSerializedFlow();
    const sanitizedSaveGraph = sanitizeEditorSaveGraph(rawFlow.nodes as FlowNodePayload[], rawFlow.edges as FlowEdgePayload[]);
    const safeFlow = { nodes: sanitizedSaveGraph.nodes as FlowNodePayload[], edges: sanitizedSaveGraph.edges as FlowEdgePayload[] };
    const endpoint = `/api/flows/${selectedFlowId}`;

    if (sanitizedSaveGraph.removedIds.size > 0) {
      console.info('FLOW_EDITOR_RUNTIME_NODES_FILTERED', {
        source: 'save_payload_sanitizer',
        flow_id: selectedFlowId,
        ...getFlowHydrationStats(rawFlow.nodes, rawFlow.edges),
        removed_canvas_nodes: Array.from(sanitizedSaveGraph.removedIds),
      });
    }

    const saveContainsAiSystem = safeFlow.nodes.some((node) => node.type === 'ai_system');
    const rawContainsExpandedAiAgents = rawFlow.nodes.some(isAiSystemInternalNode);
    if (lastEditorHadAiSystemRef.current && !saveContainsAiSystem && rawContainsExpandedAiAgents) {
      console.warn('BLOCKED_AI_SYSTEM_REPLACEMENT_BY_RUNTIME_GRAPH', {
        source: 'save_payload_guard',
        flow_id: selectedFlowId,
        ...getFlowHydrationStats(rawFlow.nodes, rawFlow.edges),
        sanitized_node_count: safeFlow.nodes.length,
      });
      setFlowSaveStatus('error');
      return;
    }

    if (flowContainsTemporaryIds(safeFlow.nodes, safeFlow.edges)) {
      setFlowSaveStatus('error');
      toast.error('✗ Falha ao salvar fluxo');
      console.error('[FLOW SAVE ERROR]', { flow_id: selectedFlowId, endpoint, reason: 'temporary_ids' });
      return;
    }

    if (requireConfirmOverwrite && !confirm('Você está sobrescrevendo o fluxo atual. Deseja continuar?')) {
      return;
    }
    setFlowValidationError(null);
    clearSaveStatusTimer();

    console.info(isAutosave ? '[AUTOSAVE START]' : '[FLOW SAVE START]', { flow_id: selectedFlowId, endpoint, method: 'PUT' });
    const aiSystemsToCompile = safeFlow.nodes.filter((node) => node.type === 'ai_system');
    if (aiSystemsToCompile.length > 0) {
      console.info('AI_SYSTEM_COMPILED', {
        flow_id: selectedFlowId,
        systems_count: aiSystemsToCompile.length,
        internal_nodes_count: aiSystemsToCompile.reduce((total, node) => { const data = (node.data || {}) as Record<string, unknown>; return total + (Array.isArray(data.internal_nodes) ? data.internal_nodes.length : 0); }, 0),
      });
    }

    console.info('[FLOW SAVE REQUEST]', {
      flow_id: selectedFlowId,
      nodes_count: safeFlow.nodes.length,
      edges_count: safeFlow.edges.length,
      node_ids: safeFlow.nodes.map((node) => node.id),
    });
    console.info('[FLOW SAVE PAYLOAD]', {
      flow_id: selectedFlowId,
      endpoint,
      method: 'PUT',
      nodes_count: safeFlow.nodes.length,
      edges_count: safeFlow.edges.length,
      payload: safeFlow,
    });

    isSavingRef.current = true;
    setIsSaving(true);
    setFlowSaveStatus('saving');
    try {
      const response = await apiFetch(endpoint, {
        method: 'PUT',
        body: JSON.stringify(safeFlow),
      });
      const data = await parseApiResponse<{ validation?: { warnings?: FlowValidationIssue[]; errors?: FlowValidationIssue[] } }>(response);
      setValidationWarnings(data?.validation?.warnings || []);
      setValidationErrors(data?.validation?.errors || []);
      const savedSignature = getFlowGraphSignature(safeFlow);
      const currentSignature = getFlowGraphSignature(getCurrentSerializedFlow());
      const dirty = currentSignature !== savedSignature;
      console.info('[DIRTY CHECK]', {
        flow_id: selectedFlowId,
        saved_signature: savedSignature,
        current_signature: currentSignature,
        dirty,
      });
      lastPersistedFlowSignatureRef.current = savedSignature;
      lastEditorHadAiSystemRef.current = safeFlow.nodes.some((node) => node.type === 'ai_system');
      setFlowDirty(dirty);
      setFlowSaveStatus('success');
      console.info('[FLOW SAVE SUCCESS]', { flow_id: selectedFlowId, endpoint, method: 'PUT' });
      if (isAutosave) {
        console.info('[AUTOSAVE SUCCESS]', { flow_id: selectedFlowId, endpoint, method: 'PUT' });
      }
      if (shouldShowToast) {
        toast.success('✓ Fluxo salvo com sucesso');
      }
      saveStatusTimeoutRef.current = setTimeout(() => {
        setFlowSaveStatus('idle');
        saveStatusTimeoutRef.current = null;
      }, 3000);
    } catch (error) {
      console.error('[FLOW SAVE ERROR]', { flow_id: selectedFlowId, endpoint, method: 'PUT', error });
      if (isAutosave) {
        console.error('[AUTOSAVE ERROR]', { flow_id: selectedFlowId, endpoint, method: 'PUT', error });
      }
      const message = error instanceof Error && error.message ? error.message : 'Erro ao salvar fluxo.';
      setFlowValidationError(message);
      setFlowSaveStatus('error');
      if (shouldShowToast) {
        toast.error('✗ Falha ao salvar fluxo');
      }
      throw error;
    } finally {
      isSavingRef.current = false;
      setIsSaving(false);
    }
  }, [clearSaveStatusTimer, getCurrentSerializedFlow, selectedFlowId, toast]);


  useEffect(() => {
    if (!flowDirty || !selectedFlowId || isSaving) return;

    const timeoutId = setTimeout(() => {
      void handleSaveFlow(false, { autosave: true, showToast: false }).catch(() => {
        // handleSaveFlow already logs [AUTOSAVE ERROR] and keeps the flow dirty for retry/manual save.
      });
    }, AUTOSAVE_DELAY_MS);

    return () => clearTimeout(timeoutId);
  }, [flowDirty, handleSaveFlow, isSaving, selectedFlowId]);

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

  const loadRuntimeObservability = useCallback(async () => {
    if (!selectedFlowId) return;
    try {
      const [snapshotResponse, inspectorResponse] = await Promise.all([
        apiFetch(`/api/flows/${selectedFlowId}/published-snapshot`),
        apiFetch(`/api/flows/${selectedFlowId}/runtime-inspector`),
      ]);
      if (snapshotResponse.ok) {
        const snapshot = await parseApiResponse<PublishedSnapshot>(snapshotResponse);
        setPublishedSnapshot(snapshot);
        const snapshotNodes = Array.isArray(snapshot?.nodes) ? snapshot.nodes.map((node) => buildFlowNode(node as FlowNodePayload)) : [];
        const snapshotEdges = Array.isArray(snapshot?.edges) ? snapshot.edges.map((edge) => buildFlowEdge(edge as FlowEdgePayload)) : [];
        setPublishedSnapshotNodes(snapshotNodes);
        setPublishedSnapshotEdges(snapshotEdges);
        if (snapshotNodes.length || snapshotEdges.length) {
          logBlockedRuntimeGraphEditorHydration('published_snapshot', snapshotNodes, snapshotEdges, selectedFlowId);
        }
      }
      if (inspectorResponse.ok) {
        const inspector = await parseApiResponse<RuntimeInspector>(inspectorResponse);
        setRuntimeInspector(inspector);
        const inspectorNodes = Array.isArray(inspector?.nodes) ? inspector.nodes.map((node) => buildFlowNode(node as FlowNodePayload)) : [];
        const inspectorEdges = Array.isArray(inspector?.edges) ? inspector.edges.map((edge) => buildFlowEdge(edge as FlowEdgePayload)) : [];
        setRuntimeNodes(inspectorNodes);
        setRuntimeEdges(inspectorEdges);
        if (inspectorNodes.length || inspectorEdges.length) {
          logBlockedRuntimeGraphEditorHydration('runtime-inspector', inspectorNodes, inspectorEdges, selectedFlowId);
        }
      }
    } catch {
      setPublishedSnapshot(null);
      setRuntimeInspector(null);
      setPublishedSnapshotNodes([]);
      setPublishedSnapshotEdges([]);
      setRuntimeNodes([]);
      setRuntimeEdges([]);
    }
  }, [selectedFlowId]);

  useEffect(() => {
    void loadRuntimeObservability();
    if (!selectedFlowId) return undefined;
    const intervalId = window.setInterval(() => {
      void loadRuntimeObservability();
    }, 5000);
    return () => window.clearInterval(intervalId);
  }, [loadRuntimeObservability, selectedFlowId]);

  const handleActivateFlow = useCallback(async () => {
    if (!selectedFlowId) return;
    if (validationErrors.length > 0) return;

    const currentNodes = rfInstance?.getNodes?.() || [];
    const currentEdges = rfInstance?.getEdges?.() || [];
    const invalidMediaNode = currentNodes.find((node) => {
      const data = node.data as Record<string, unknown> | undefined;
      if (node.type !== 'media' && data?.type !== 'media') return false;
      return !String(data?.media_url || '').trim().startsWith('https://');
    });
    if (invalidMediaNode) {
      setValidationErrors([{ code: 'FLOW_V2_MEDIA_URL_INVALID', node_id: invalidMediaNode.id, message: 'Node Mídia exige uma URL pública começando com https:// para publicar.' }]);
      setHighlightedNodeId(invalidMediaNode.id);
      toast.error('Node Mídia exige uma URL pública começando com https:// para publicar.');
      return;
    }
    const invalidCtaNode = currentNodes.find((node) => {
      const data = node.data as Record<string, unknown> | undefined;
      if (node.type !== 'cta_url' && node.type !== 'cta_link' && data?.type !== 'cta_url') return false;
      const text = String(data?.content || data?.text || data?.message || '').trim();
      const buttonText = String(data?.button_text || '').trim();
      const url = String(data?.url || '').trim();
      return !text || !buttonText || buttonText.length > 20 || !url.startsWith('https://');
    });
    if (invalidCtaNode) {
      setValidationErrors([{ code: 'FLOW_V2_CTA_URL_INVALID', node_id: invalidCtaNode.id, message: 'Node CTA / Link exige mensagem, botão de até 20 caracteres e URL começando com https://.' }]);
      setHighlightedNodeId(invalidCtaNode.id);
      toast.error('Node CTA / Link exige mensagem, botão de até 20 caracteres e URL https://.');
      return;
    }
    if (flowContainsTemporaryIds(currentNodes, currentEdges)) {
      toast.error('Flow contém IDs temporários inválidos.');
      return;
    }

    try {
      const currentSignature = getFlowGraphSignature(getCurrentSerializedFlow());
      const hasUnpersistedBuilderGraph = flowDirty || currentSignature !== lastPersistedFlowSignatureRef.current;
      if (hasUnpersistedBuilderGraph) {
        console.log('[PUBLISH SAVE BEFORE START]', { flowId: selectedFlowId });
        try {
          await handleSaveFlow();
          console.log('[PUBLISH SAVE BEFORE SUCCESS]', { flowId: selectedFlowId });
        } catch (saveError) {
          console.error('[PUBLISH SAVE BEFORE FAILED]', { flowId: selectedFlowId, error: saveError });
          throw saveError;
        }
      }

      const publishSnapshot = getCurrentSerializedFlow();
      const publishInternalNodesCount = publishSnapshot.nodes.reduce((total, node) => {
        const data = (node.data || {}) as Record<string, unknown>;
        return total + (Array.isArray(data.internal_nodes) ? data.internal_nodes.length : 0);
      }, 0);
      const publishInternalEdgesCount = publishSnapshot.nodes.reduce((total, node) => {
        const data = (node.data || {}) as Record<string, unknown>;
        return total + (Array.isArray(data.internal_edges) ? data.internal_edges.length : 0);
      }, 0);
      const publishRawNodes = rfInstance?.getNodes?.() || [];
      const publishRawEdges = rfInstance?.getEdges?.() || [];
      const publishSanitizationStats = sanitizeAiSystemCanvasGraph(publishRawNodes, publishRawEdges);
      console.log('[PUBLISH REQUEST]', { flowId: selectedFlowId });
      console.info('AI_SYSTEM_PUBLISH_SANITIZATION', {
        flow_id: selectedFlowId,
        total_nodes: publishSnapshot.nodes.length,
        total_edges: publishSnapshot.edges.length,
        total_internal_nodes: publishInternalNodesCount,
        total_internal_edges: publishInternalEdgesCount,
        removed_edges_by_sanitization: publishSanitizationStats.removedEdgesCount,
      });
      console.info('[FLOW PUBLISH NODE IDS]', { flow_id: selectedFlowId, node_ids: publishSnapshot.nodes.map((node) => node.id) });
      const response = await apiFetch(`/api/flows/${selectedFlowId}/publish`, { method: 'POST', body: JSON.stringify({}) });
      if (!response.ok) {
        const body = await response.text();
        console.error('[PUBLISH ERROR BODY]', body);
        let detailedMessage = body;
        try {
          const parsed = JSON.parse(body);
          const detail = parsed?.detail;
          if (detail && typeof detail === 'object') {
            detailedMessage = `${detail.code || 'VALIDATION_ERROR'}: ${detail.error || 'FLOW_INVALID'} edge=${detail.edge_id ?? detail.edge_index ?? 'n/a'} source=${detail.source ?? 'n/a'} sourceHandle=${detail.sourceHandle ?? 'n/a'} target=${detail.target ?? 'n/a'} targetHandle=${detail.targetHandle ?? 'n/a'} reasons=${Array.isArray(detail.reasons) ? detail.reasons.join(',') : 'n/a'}`;
          }
        } catch {
          detailedMessage = body;
        }
        throw new Error(`HTTP ${response.status}: ${detailedMessage}`);
      }
      const publishData = await parseApiResponse(response);
      console.log('[PUBLISH RESPONSE]', { flowId: selectedFlowId, status: response.status, payload: publishData });

      const activateResponse = await apiFetch(`/api/flows/${selectedFlowId}/activate`, { method: 'PUT' });
      await parseApiResponse(activateResponse);

      setActiveFlowId(selectedFlowId);
      setFlows((prev) => prev.map((flow) => ({ ...flow, is_active: flow.id === selectedFlowId, is_published: flow.id === selectedFlowId ? true : flow.is_published })));
      lastPersistedFlowSignatureRef.current = getFlowGraphSignature(getCurrentSerializedFlow());
      setFlowDirty(false);
      setFlowSaveStatus('success');
      await loadRuntimeObservability();
    } catch (error) {
      console.error('[PUBLISH ERROR]', { flowId: selectedFlowId, error });
      const message = error instanceof Error && error.message ? error.message : 'Não foi possível publicar o fluxo.';
      toast.error(`Falha ao publicar: ${message}`);
    }
  }, [flowDirty, getCurrentSerializedFlow, handleSaveFlow, loadFlow, loadRuntimeObservability, rfInstance, selectedFlowId, toast, validationErrors.length]);

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

  const renameFlow = useCallback(async (name: string) => {
    if (!selectedFlowId) return;
    if (!name) return;
    const response = await apiFetch(`/api/flows/${selectedFlowId}/rename`, {
      method: 'PUT',
      body: JSON.stringify({ name }),
    });
    await parseApiResponse(response);

    setFlows((prev) => prev.map((flow) => (flow.id === selectedFlowId ? { ...flow, name } : flow)));
  }, [selectedFlowId]);

  const closeRenameFlowModal = useCallback(() => {
    setIsRenameFlowOpen(false);
    renameTriggerRef.current?.focus();
  }, []);

  const openRenameFlowModal = useCallback(() => {
    if (!selectedFlowId) return;
    setRenameFlowName(selectedFlow?.name || selectedFlowId);
    setIsRenameFlowOpen(true);
  }, [selectedFlow?.name, selectedFlowId]);

  const handleRenameFlowSubmit = useCallback(async () => {
    const nextName = renameFlowName;
    closeRenameFlowModal();
    await renameFlow(nextName);
  }, [closeRenameFlowModal, renameFlow, renameFlowName]);

  useEffect(() => {
    if (!isRenameFlowOpen) return;
    requestAnimationFrame(() => {
      renameInputRef.current?.focus();
      renameInputRef.current?.select();
    });
  }, [isRenameFlowOpen]);

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
      lastPersistedFlowSignatureRef.current = getFlowGraphSignature(serializeFlowGraph(restoredNodes, orderedEdges));
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

  const analyticsByNode = useMemo(() => new Map((analyticsData?.node_metrics ?? []).map((item) => [item.node_id, item])), [analyticsData]);
  const analyticsByEdge = useMemo(() => new Map((analyticsData?.transition_metrics ?? []).map((item) => [`${item.source_node_id}->${item.target_node_id}:${item.source_handle || ''}`, item])), [analyticsData]);

  useEffect(() => {
    if (!analyticsOverlayEnabled || !selectedFlowId) {
      if (!analyticsOverlayEnabled) setAnalyticsData(null);
      return;
    }
    let active = true;
    getFlowAnalytics(selectedFlowId, '7d', 'active')
      .then((payload) => { if (active) setAnalyticsData(payload); })
      .catch(() => { if (active) { setAnalyticsOverlayEnabled(false); setAnalyticsData(null); setToastMessage({ type: 'error', message: 'Não foi possível carregar o heatmap.' }); } });
    return () => { active = false; };
  }, [analyticsOverlayEnabled, selectedFlowId]);

  const decoratedNodes = useMemo(() => {
    const baseNodes = nodes.map((node) => ({
      ...node,
      data: {
        ...node.data,
        running: node.id === currentNodeId,
        onToggleStart: toggleStartNode,
        onOpenSystem: openAiSystemModal,
        hasValidationError: node.id === highlightedNodeId,
        analytics: analyticsOverlayEnabled ? analyticsByNode.get(node.id) ?? null : null,
      },
    }));

    return baseNodes;
  }, [analyticsByNode, analyticsOverlayEnabled, currentNodeId, highlightedNodeId, nodes, openAiSystemModal, toggleStartNode]);

  const safeNodes = useMemo(
    () => (Array.isArray(decoratedNodes) ? decoratedNodes : []).map((node) => ({
      type: node.type || 'default',
      ...node,
    })),
    [decoratedNodes],
  );

  const safeEdges = useMemo(
    () => (Array.isArray(edges) ? edges : []),
    [edges],
  );

  const visibleEdges = safeEdges;

  const decoratedEdges = useMemo(
    () =>
      visibleEdges.map((edge) => ({
        ...edge,
        className: activeEdgeIds.includes(edge.id) ? 'flow-edge flow-edge-active' : 'flow-edge',
        label: analyticsOverlayEnabled ? (() => { const metric = analyticsByEdge.get(`${edge.source}->${edge.target}:${edge.sourceHandle || ''}`) || analyticsByEdge.get(`${edge.source}->${edge.target}:default`) || analyticsByEdge.get(`${edge.source}->${edge.target}:`); return metric ? `${metric.rate_from_source}%` : edge.label; })() : edge.label,
        style: analyticsOverlayEnabled ? { ...(edge.style || {}), strokeWidth: Math.min(6, 1 + Math.log10(((analyticsByEdge.get(`${edge.source}->${edge.target}:${edge.sourceHandle || ''}`) || analyticsByEdge.get(`${edge.source}->${edge.target}:default`) || analyticsByEdge.get(`${edge.source}->${edge.target}:`))?.count || 1)) * 2), opacity: 0.85 } : edge.style,
      })),
    [activeEdgeIds, analyticsByEdge, analyticsOverlayEnabled, visibleEdges],
  );

  const activeAiSystemNode = useMemo(() => nodes.find((node) => node.id === activeAiSystemNodeId) || null, [activeAiSystemNodeId, nodes]);
  const activeAiSystemTemplate = useMemo(() => {
    const data = (activeAiSystemNode?.data || {}) as Record<string, unknown>;
    const templateId = typeof data.system_type === 'string' ? data.system_type : typeof data.agent_system_template_id === 'string' ? data.agent_system_template_id : '';
    return AGENT_SYSTEM_TEMPLATES.find((template) => template.id === templateId);
  }, [activeAiSystemNode]);

  // Fecha o menu de contexto ao clicar fora
  useEffect(() => {
    const handleClick = () => setContextMenu(null);
    document.addEventListener('click', handleClick);
    return () => document.removeEventListener('click', handleClick);
  }, []);

  const mobileSequence = useMemo(() => buildMobileFlowSequence(nodes, edges), [nodes, edges]);
  const selectMobileNode = (node: Node) => {
    openNodeEditor(node);
    const params = new URLSearchParams(searchParams.toString());
    params.set('node', node.id);
    params.set('view', mobileView);
    router.push(`/dashboard/flow-builder?${params.toString()}`);
  };
  const closeMobileNodeEditor = () => {
    closeNodeEditor();
    const params = new URLSearchParams(searchParams.toString());
    params.delete('node');
    router.replace(`/dashboard/flow-builder?${params.toString()}`);
  };
  const setMobileFlowView = (view: 'list' | 'map') => {
    setMobileView(view);
    const params = new URLSearchParams(searchParams.toString());
    params.set('view', view);
    router.replace(`/dashboard/flow-builder?${params.toString()}`);
  };
  if (isLoading) {
    return <FlowBuilderSkeleton />;
  }
  if (isMobileViewport) {
    return (
      <main className="flow-mobile-builder">
        <section className="flow-mobile-summary" aria-label="Resumo do fluxo">
          <div><h1>{selectedFlow?.name || 'Fluxo não selecionado'}</h1><button type="button" aria-label="Abrir validação do fluxo" onClick={() => setIsMobileValidationOpen(true)}><MoreHorizontal size={20} /></button></div>
          <div><span>{getFlowBadge(selectedFlow || {}).label}</span><small>{flowSaveStatus === 'saving' ? 'Salvando…' : flowDirty ? 'Alterações pendentes' : flowSaveStatus === 'error' ? 'Erro ao salvar' : 'Salvo'}</small></div>
          <dl><div><dt>Nodes</dt><dd>{nodes.length}</dd></div><div><dt>Conexões</dt><dd>{edges.length}</dd></div><div><dt>Problemas</dt><dd>{validationErrors.length + validationWarnings.length}</dd></div></dl>
          <div className="flow-mobile-summary__actions"><button type="button" onClick={() => void handleSaveFlow(false, { showToast: true })} disabled={isSaving || !selectedFlowId}><Save size={16}/>{saveButtonLabel}</button><button type="button" onClick={() => setIsSimulatorOpen(true)} disabled={!nodes.length}><Play size={16}/>Testar</button><button type="button" onClick={handleActivateFlow} disabled={!selectedFlowId || validationErrors.length > 0}>Publicar</button></div>
        </section>
        <div className="flow-mobile-tabs" role="tablist"><button type="button" role="tab" aria-selected={mobileView === 'list'} onClick={() => setMobileFlowView('list')}>Lista</button><button type="button" role="tab" aria-selected={mobileView === 'map'} onClick={() => setMobileFlowView('map')}>Mapa</button></div>
        {mobileView === 'map' ? <section className="flow-mobile-map"><GitFork size={24}/><strong>Mapa disponível no editor completo</strong><p>Use a lista para editar o fluxo sem comprimir o canvas.</p><span>{nodes.length} nodes · {edges.length} conexões</span></section> : <section className="flow-mobile-list" aria-label="Sequência lógica dos nodes">
          {mobileSequence.connected.map((item, index) => { const data = item.node.data as Record<string, unknown>; const outputs = edges.filter((edge) => edge.source === item.node.id); return <div role="button" tabIndex={0} key={`${item.node.id}-${index}`} className="flow-mobile-node" style={{ marginLeft: Math.min(item.depth, 3) * 12 }} onClick={() => selectMobileNode(item.node)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectMobileNode(item.node); } }}><span className="flow-mobile-node__type">{getBuilderNodeTitle(item.node)}</span><strong>{String(data.label || data.content || getBuilderNodeTitle(item.node))}</strong><small>{data.isStart ? 'Início · ' : ''}{data.is_terminal ? 'Fim · ' : ''}{item.incomingLabel ? `${item.incomingLabel} → ` : ''}{outputs.length ? `${outputs.length} saída${outputs.length > 1 ? 's' : ''}` : 'Sem saída'}</small>{item.isCycle && <em><AlertTriangle size={14}/> Ciclo detectado</em>}<ChevronRight size={18}/><span role="button" tabIndex={0} className="flow-mobile-node__connect" aria-label={`Definir próximo node para ${getBuilderNodeTitle(item.node)}`} onClick={(event) => { event.stopPropagation(); setMobileConnectSource(item.node); setMobileConnectHandle(''); }} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setMobileConnectSource(item.node); setMobileConnectHandle(''); } }}>Conectar</span></div>; })}
          {mobileSequence.disconnected.length > 0 && <><h2>Não conectados</h2>{mobileSequence.disconnected.map((node) => <button type="button" key={node.id} className="flow-mobile-node flow-mobile-node--orphan" onClick={() => selectMobileNode(node)}><span className="flow-mobile-node__type">{getBuilderNodeTitle(node)}</span><strong>{String((node.data as Record<string, unknown>).label || (node.data as Record<string, unknown>).content || getBuilderNodeTitle(node))}</strong><small>Node desconectado</small><ChevronRight size={18}/></button>)}</>}
        </section>}
        <button type="button" className="flow-mobile-add" onClick={() => setIsMobileAddOpen(true)}><Plus size={20}/>Adicionar node</button>
        <MobileBottomSheet open={isMobileAddOpen} onClose={() => setIsMobileAddOpen(false)} title="Adicionar node">{NODE_GROUPS.map((group) => <section className="flow-mobile-palette" key={group.id}><h2>{group.title}</h2>{group.nodes.map(({ kind, label, icon: Icon }) => <button type="button" key={kind} onClick={() => { const node = addNode(kind); setIsMobileAddOpen(false); if (node) selectMobileNode(node); }}><Icon size={18}/>{label}</button>)}</section>)}</MobileBottomSheet>
        <MobileBottomSheet open={Boolean(mobileConnectSource)} onClose={() => setMobileConnectSource(null)} title="Definir próximo node">{mobileConnectSource && <div className="flow-mobile-connect"><p>Escolha o destino para <strong>{getBuilderNodeTitle(mobileConnectSource)}</strong>. As conexões existentes desse node serão preservadas.</p>{(() => { const data = mobileConnectSource.data as Record<string, unknown>; const handles = mobileConnectSource.type === 'condition' ? [{ id: 'true', label: 'Sim' }, { id: 'false', label: 'Não' }] : mobileConnectSource.type === 'choice' ? (Array.isArray(data.buttons) ? data.buttons : []).map((item: Record<string, unknown>, index: number) => ({ id: String(item.handleId || item.id || `option_${index + 1}`), label: String(item.label || item.value || `Opção ${index + 1}`) })) : []; return handles.length ? <label>Saída<select value={mobileConnectHandle} onChange={(event) => setMobileConnectHandle(event.target.value)}>{handles.map((handle) => <option key={handle.id} value={handle.id}>{handle.label}</option>)}</select></label> : null; })()}{nodes.filter((node) => node.id !== mobileConnectSource.id).map((target) => <button type="button" key={target.id} onClick={() => { onConnect({ source: mobileConnectSource.id, target: target.id, sourceHandle: mobileConnectHandle || null, targetHandle: null }); setMobileConnectSource(null); }}><span>{getBuilderNodeTitle(target)}</span><strong>{String((target.data as Record<string, unknown>).label || getBuilderNodeTitle(target))}</strong></button>)}</div>}</MobileBottomSheet>
        <MobileBottomSheet open={isMobileValidationOpen} onClose={() => setIsMobileValidationOpen(false)} title="Validação do fluxo"><p className="flow-mobile-validation-count">{validationErrors.length} erros · {validationWarnings.length} avisos</p>{[...validationErrors, ...validationWarnings].map((issue, index) => <button type="button" className="flow-mobile-validation-item" key={`${issue.code}-${index}`} onClick={() => { const node = nodes.find((item) => item.id === issue.node_id); if (node) selectMobileNode(node); setIsMobileValidationOpen(false); }}><AlertTriangle size={16}/><span>{issue.message}</span></button>)}</MobileBottomSheet>
        <MobileBottomSheet open={Boolean(selectedNode)} onClose={closeMobileNodeEditor} title={selectedNode ? getBuilderNodeTitle(selectedNode) : 'Editar node'} fullScreen closeOnBackdrop={!isMediaUploading}><div className="flow-mobile-editor">{selectedNode && <FlowNodeEditorPanel node={selectedNode} draft={nodeEditorDraft} onDraftChange={handleNodeEditorDraftChange} onClose={closeMobileNodeEditor} onUpload={(file, mediaType) => { void uploadEditorMedia(file, mediaType); }} isUploading={isMediaUploading} uploadError={mediaUploadError} flows={normalizedFlows} currentFlowId={selectedFlowId} allNodes={nodes} mcpTools={mcpTools} />}</div></MobileBottomSheet>
      </main>
    );
  }
  return (
    <div className="flow-builder-page" style={{ width: '100%', height: '100vh', display: 'flex' }}>
      <nav
        className={`dash-sidebar flow-builder-sidebar ${isSidebarExpanded ? 'is-expanded' : ''}`}
        onMouseEnter={() => setIsSidebarExpanded(true)}
        onMouseLeave={() => setIsSidebarExpanded(false)}
        style={{
          zIndex: 20,
          width: isSidebarExpanded ? 200 : 56,
          minWidth: isSidebarExpanded ? 200 : 56,
          maxWidth: isSidebarExpanded ? 200 : 56,
          flexShrink: 0,
        }}
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

        <div className="flow-node-palette" aria-label="Paleta de nodes do Flow Builder">
          {ENABLE_AGENT_SYSTEM_TEMPLATES ? (
            <button
              type="button"
              className="dash-nav-item flow-node-palette-item"
              onClick={() => setIsAgentSystemModalOpen(true)}
              title="Inserir sistema profissional de agentes pré-montado"
              data-tooltip="Templates modulares com IA Dispatcher, agentes especializados e fallback seguro."
            >
              <span className="flow-node-palette-item-icon" aria-hidden="true">
                <CalendarDays size={17} strokeWidth={1.9} className="text-current" />
              </span>
              <span className="dash-nav-label">🤖 AI Systems</span>
            </button>
          ) : null}
          {NODE_GROUPS.map((group) => {
            const GroupIcon = group.icon;
            const isOpen = openNodeGroups[group.id];

            return (
              <div key={group.id} className={`flow-node-group ${isOpen ? 'is-open' : ''}`}>
                <button
                  type="button"
                  className="flow-node-group-toggle"
                  onClick={() => setOpenNodeGroups((current) => ({ ...current, [group.id]: !current[group.id] }))}
                  title={group.title}
                  aria-expanded={isOpen}
                >
                  <GroupIcon size={16} strokeWidth={1.9} className="flow-node-group-icon" />
                  <span className="flow-node-group-title">{group.title}</span>
                  <ChevronDown size={14} strokeWidth={2.1} className="flow-node-group-chevron" />
                </button>

                <div className="flow-node-group-items" aria-hidden={!isOpen}>
                  {group.nodes.map(({ kind, label, icon: Icon, description }) => (
                    <button
                      key={kind}
                      type="button"
                      className="dash-nav-item flow-node-palette-item"
                      onClick={() => addNode(kind)}
                      title={description || label}
                      data-tooltip={description}
                    >
                      <span className="flow-node-palette-item-icon" aria-hidden="true">
                        <Icon size={17} strokeWidth={1.9} className="text-current" />
                      </span>
                      <span className="dash-nav-label">{label}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>

        <div style={{ marginTop: 'auto' }}>
          <div className="dash-nav-divider" />
          <Link href="/dashboard/flows" className="dash-nav-item active" title="Lista de fluxos" style={{ textDecoration: 'none' }}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6"/>
            </svg>
            <span className="dash-nav-label">Fluxos</span>
          </Link>
          {selectedFlowId && (
            <Link href={`/dashboard/flows/${selectedFlowId}/analytics`} className="dash-nav-item" title="Analytics do fluxo" style={{ textDecoration: 'none' }}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="20" x2="18" y2="10"/>
                <line x1="12" y1="20" x2="12" y2="4"/>
                <line x1="6" y1="20" x2="6" y2="14"/>
              </svg>
              <span className="dash-nav-label">Analytics</span>
            </Link>
          )}
        </div>
      </nav>

      {flowValidationError && (
        <div style={{ position: 'absolute', top: showEmptyFlowWarning ? 50 : 12, right: 16, zIndex: 25, background: '#fef2f2', color: '#b91c1c', border: '1px solid #fca5a5', borderRadius: 8, padding: '8px 12px', fontSize: 13 }}>
          {flowValidationError}
        </div>
      )}
      {validationWarnings.length > 0 && nodes.length > 0 && (
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
      {toastMessage && (
        <div style={{ position: 'fixed', right: 24, bottom: 24, background: toastMessage.type === 'success' ? '#16a34a' : '#dc2626', color: '#fff', padding: '10px 16px', borderRadius: 10, fontSize: 13, boxShadow: '0 8px 24px rgba(0,0,0,0.2)', zIndex: 60 }}>
          {toastMessage.message}
        </div>
      )}
      {flowSource === 'fallback' && (
        <div style={{ position: 'absolute', top: 12, left: '50%', transform: 'translateX(-50%)', zIndex: 25, background: '#eff6ff', color: '#1d4ed8', border: '1px solid #93c5fd', borderRadius: 8, padding: '6px 10px', fontSize: 12 }}>
          Flow recuperado automaticamente
        </div>
      )}
      <main ref={flowCanvasRef} style={{ flex: 1, background: '#F7F7F5', position: 'relative', minWidth: 0 }}>
        <div className="flow-builder-header">
          <div className="flow-builder-breadcrumb" aria-label="Breadcrumb">
            <Link href="/dashboard/flows" aria-label="Voltar para Fluxos">← Fluxos</Link>
            {selectedFlow && (
              <>
                <span aria-hidden="true">/</span>
                <span>{selectedFlow.name || selectedFlow.id}</span>
              </>
            )}
          </div>

          <div className="flow-builder-top-actions">
            {normalizedFlows.length === 0 && (
              <div className="flow-empty-create-row">
                <span>Nenhum fluxo criado ainda</span>
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
                        {selectedFlow && (() => {
                          const badge = getFlowBadge(selectedFlow);
                          return (
                            <span className="flow-status-cluster">
                              <span className="flow-badge" style={badge.style}>{badge.label}</span>
                              {flowStatusIndicator && (
                                <span className={flowStatusIndicator.className} title={flowStatusIndicator.title}>
                                  <span aria-hidden="true">•</span>
                                  <span>{flowStatusIndicator.label}</span>
                                </span>
                              )}
                            </span>
                          );
                        })()}
                      </div>
                    </button>
                    {isFlowSelectOpen && normalizedFlows.length > 0 && (
                      <div className="flow-select-dropdown" role="listbox">
                        {normalizedFlows.map((flow) => (
                          <button
                            key={flow.id}
                            type="button"
                            className={`flow-select-option${flow.id === selectedFlowId ? ' flow-select-option-active' : ''}`}
                            style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}
                            onClick={async () => {
                              await handleSelectFlow(flow.id);
                            }}
                          >
                            <span className="flow-name" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{flow.name || flow.id}</span>
                            {(() => {
                              const badge = getFlowBadge(flow);
                              return <span className="flow-badge" style={badge.style}>{badge.label}</span>;
                            })()}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>

              <div className="flow-toolbar-section flow-toolbar-center" aria-label="Ações do flow">
                <div className="flow-toolbar-group flow-toolbar-group-secondary-actions">
                  <button
                    type="button"
                    className="flow-top-btn flow-top-btn-secondary"
                    onClick={handleCreateFlow}
                    disabled={isCreatingFlow}
                  >
                    {isCreatingFlow ? 'Criando...' : 'Novo'}
                  </button>
                  <button
                    type="button"
                    className="flow-top-btn flow-top-btn-neutral"
                    ref={renameTriggerRef}
                    onClick={openRenameFlowModal}
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
                  <button
                    type="button"
                    className="flow-top-btn flow-top-btn-neutral"
                    onClick={() => setAnalyticsOverlayEnabled((enabled) => !enabled)}
                    disabled={!selectedFlowId}
                    title="Camada visual read-only de analytics"
                  >
                    {analyticsOverlayEnabled ? 'Heatmap ligado' : 'Heatmap'}
                  </button>
                  <button
                    type="button"
                    className="flow-top-btn flow-top-btn-neutral"
                    onClick={() => {
                      setIsSnapshotPanelOpen((open) => !open);
                      void loadRuntimeObservability();
                    }}
                    disabled={!selectedFlowId}
                  >
                    Snapshot
                  </button>
                </div>
                <div className="flow-toolbar-group flow-toolbar-group-primary-actions">
                  {(flowDirty || flowSaveStatus === 'saving') && (
                    <button
                      type="button"
                      className="flow-top-btn flow-top-btn-primary"
                      onClick={() => void handleSaveFlow(false, { showToast: true })}
                      disabled={isSaving || !selectedFlowId}
                      title={isEditing ? 'Salvar alterações' : 'Visualização'}
                    >
                      {saveButtonLabel}
                    </button>
                  )}
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
                      Simular
                    </button>
                  )}
                  <button
                    type="button"
                    className="flow-top-btn flow-top-btn-primary"
                    onClick={handleActivateFlow}
                    disabled={!selectedFlowId || validationErrors.length > 0}
                  >
                    Ativar
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
        {isSnapshotPanelOpen && (
          <div style={{ margin: '8px 0', padding: 12, border: '1px solid #dbeafe', borderRadius: 10, background: '#eff6ff', maxWidth: 760, fontSize: 12 }}>
            <strong>Snapshot publicado</strong>
            <div>Versão publicada atual: {publishedSnapshot?.version_id || '—'}</div>
            <div>Nodes publicados: {publishedSnapshot?.nodes_count ?? publishedSnapshot?.nodes?.length ?? 0}</div>
            <div>Edges publicadas: {publishedSnapshot?.edges_count ?? publishedSnapshot?.edges?.length ?? 0}</div>
            <div>Hash: {publishedSnapshot?.graph_hash || '—'}</div>
            <strong style={{ display: 'block', marginTop: 8 }}>Runtime Inspector</strong>
            <div>Flow Version ID: {runtimeInspector?.flow_version_id || '—'}</div>
            <div>Current Node: {runtimeInspector?.current_node_id || '—'}</div>
            <div>Previous Node: {runtimeInspector?.previous_node_id || '—'}</div>
            <div>Next Node: {runtimeInspector?.next_node_id || '—'}</div>
            <div>Session ID: {runtimeInspector?.session_id || '—'}</div>
            <div>Status: {runtimeInspector?.status || '—'}</div>
          </div>
        )}
        {validationErrors.length > 0 && (
          <div style={{ margin: '8px 0', padding: 10, border: '1px solid #fecaca', borderRadius: 8, background: '#fff1f2', maxWidth: 420 }}>
            <strong style={{ fontSize: 12 }}>Problemas do fluxo</strong>
            {validationErrors.map((issue, idx) => (
              <div key={`${issue.code}-${idx}`} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12, marginTop: 6 }}>
                <span>⚠️ {issue.message}</span>
                <button type="button" onClick={() => focusNodeIssue(issue.node_id)} style={{ color: '#b91c1c' }}>Ir para bloco</button>
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
            {NODE_GROUPS.flatMap((group) => group.nodes).map(({ kind, label, icon: Icon }) => (
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
            <div className="flow-context-menu-divider" />
            <button
              type="button"
              onClick={() => { setContextMenu(null); void deleteFlow(); }}
              disabled={!selectedFlowId}
              className="flow-context-menu-item flow-context-menu-danger flex items-center gap-2 px-3 py-2 rounded-md transition-all duration-150"
            >
              Excluir flow
            </button>
          </div>
        )}
        {isLoadingFlow && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 20, display: 'grid', placeItems: 'center', pointerEvents: 'none' }}>
            <div style={{ width: 'min(560px, calc(100% - 32px))', borderRadius: 22, border: '1px solid #E5E7EB', background: 'rgba(255,255,255,0.85)', padding: '30px 26px', boxShadow: '0 18px 40px rgba(16,24,40,0.08)' }}>
              <div style={{ height: 16, borderRadius: 999, background: '#ECFDF3', marginBottom: 14 }} />
              <div style={{ height: 12, borderRadius: 999, background: '#F3F4F6', marginBottom: 10, width: '80%' }} />
              <div style={{ height: 12, borderRadius: 999, background: '#F3F4F6', width: '60%' }} />
            </div>
          </div>
        )}
        {shouldRenderEmptyState && (
          <div style={{ position: 'absolute', inset: 0, zIndex: 20, display: 'grid', placeItems: 'center', pointerEvents: 'none' }}>
            <div style={{ pointerEvents: 'auto', width: 'min(640px, calc(100% - 32px))', background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(247,252,249,0.98) 100%)', border: '1px solid #DCEFE3', borderRadius: 24, padding: '40px 36px', textAlign: 'center', boxShadow: '0 26px 60px rgba(16,24,40,0.12)' }}>
              <div style={{ width: 66, height: 66, margin: '0 auto 18px', borderRadius: 18, display: 'grid', placeItems: 'center', background: 'radial-gradient(circle at 30% 20%, #D1FAE5, #A7F3D0 70%)', color: '#047857' }}>
                <Zap size={30} strokeWidth={1.9} />
              </div>
              <h3 style={{ margin: 0, fontSize: 30, lineHeight: 1.15, letterSpacing: '-0.02em', color: '#0F172A', fontWeight: 700 }}>Comece seu primeiro fluxo</h3>
              <p style={{ margin: '14px auto 28px', fontSize: 16, lineHeight: 1.55, color: '#334155', maxWidth: 540 }}>Crie automações para responder clientes, qualificar leads e vender no WhatsApp.</p>
              <div style={{ display: 'flex', gap: 16, justifyContent: 'center', flexWrap: 'wrap' }}>
                <button type="button" onClick={handleCreateInitialMessage} className="flow-top-btn flex items-center justify-center min-h-11 rounded-xl font-medium transition-all duration-200" style={{ minWidth: 260, padding: '12px 24px', borderRadius: 12, boxShadow: '0 10px 18px rgba(22,163,74,0.2)' }}>Adicionar mensagem inicial</button>
                <button type="button" onClick={handleUseSimpleTemplate} className="flow-top-btn flow-top-btn-secondary flex items-center justify-center min-h-11 rounded-xl font-medium transition-all duration-200" style={{ minWidth: 260, padding: '12px 24px', borderRadius: 12, border: '1px solid #86EFAC', color: '#166534', background: '#F0FDF4' }}>Usar template simples</button>
              </div>
            </div>
          </div>
        )}
        <ReactFlow
          key={flow?.id || 'no-flow'}
          onInit={setRfInstance}
          nodes={safeNodes}
          edges={decoratedEdges}
          onNodesChange={handleNodesChange}
          onEdgesChange={handleEdgesChange}
          onConnect={onConnect}
          onConnectStart={onConnectStart}
          onConnectEnd={onConnectEnd}
          onNodeDoubleClick={handleReactFlowNodeDoubleClick}
          onContextMenu={(e) => {
            e.preventDefault();
            const mainRect = (e.currentTarget as HTMLElement).getBoundingClientRect();
            setContextMenu({ x: e.clientX - mainRect.left, y: e.clientY - mainRect.top });
          }}
          onNodesDelete={(deleted) => {
            const deletedIds = new Set(deleted.map((item) => item.id));
            console.info('[FLOW NODE DELETE COMMIT]', {
              flow_id: selectedFlowId,
              deleted_node_ids: Array.from(deletedIds),
            });
            setNodes((nds) => nds.filter((node) => !deletedIds.has(node.id)));
            setEdges((eds) => eds.filter((edge) => !deletedIds.has(edge.source) && !deletedIds.has(edge.target)));
            markFlowDirty('node_delete_commit', { deleted_node_ids: Array.from(deletedIds) });
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
          <MiniMap
            nodeBorderRadius={8}
            pannable
            zoomable
            nodeColor={(node) => getMiniMapNodeColor(String(node.type || ''))}
            nodeStrokeColor={(node) => (node.id === selectedNodeId ? '#111827' : getMiniMapNodeColor(String(node.type || '')))}
            nodeStrokeWidth={3}
            maskColor="rgba(15, 23, 42, 0.08)"
            style={{ background: '#FFFFFF', border: '1px solid #D9E7DD', borderRadius: 14, boxShadow: '0 12px 30px rgba(15,23,42,0.08)' }}
          />
          <Controls />
        </ReactFlow>
      </main>

      {isAgentSystemModalOpen && (
        <AIStoreModal
          cards={AI_SYSTEM_CARDS}
          templates={AGENT_SYSTEM_TEMPLATES}
          onClose={() => setIsAgentSystemModalOpen(false)}
          onInstall={handleInsertAgentSystemTemplate}
        />
      )}

      {selectedNode && (
        <>
          <button
            type="button"
            className="flow-node-editor-backdrop"
            onClick={closeNodeEditor}
            aria-label="Fechar editor de bloco"
          />
          <FlowNodeEditorPanel
            node={selectedNode}
            draft={nodeEditorDraft}
            onDraftChange={handleNodeEditorDraftChange}
            onClose={closeNodeEditor}
            onUpload={(file, mediaType) => { void uploadEditorMedia(file, mediaType); }}
            isUploading={isMediaUploading}
            uploadError={mediaUploadError}
            flows={normalizedFlows}
            currentFlowId={selectedFlowId}
            allNodes={nodes}
            mcpTools={mcpTools}
          />
        </>
      )}
      <CreateFlowModal
        open={isCreateFlowOpen}
        onClose={() => setIsCreateFlowOpen(false)}
        onCreated={handleFlowCreated}
      />
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
            <div
              className="typing-indicator"
              style={{
                alignSelf: 'flex-start',
                background: '#FFFFFF',
                padding: '9px 12px',
                borderRadius: '4px 14px 14px 14px',
                maxWidth: '85%',
                fontSize: 12.5,
                lineHeight: 1.55,
                color: '#6b7280',
                border: '1px solid #e4e8e0',
                boxShadow: '0 1px 4px rgba(0,0,0,0.06)',
                fontStyle: 'italic',
              }}
            >
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

      {isRenameFlowOpen && (
        <div className="flow-versions-backdrop" onClick={closeRenameFlowModal}>
          <form
            className="flow-rename-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="flow-rename-title"
            onClick={(event) => event.stopPropagation()}
            onSubmit={(event) => {
              event.preventDefault();
              void handleRenameFlowSubmit();
            }}
            onKeyDown={(event) => {
              if (event.key === 'Escape') {
                event.preventDefault();
                closeRenameFlowModal();
              }
            }}
          >
            <div className="flow-rename-header">
              <div>
                <h3 id="flow-rename-title">Renomear fluxo</h3>
                <p>Atualize o nome exibido no Flow Builder.</p>
              </div>
            </div>
            <label className="flow-rename-field">
              Nome do fluxo
              <input
                ref={renameInputRef}
                value={renameFlowName}
                onChange={(event) => setRenameFlowName(event.target.value)}
              />
            </label>
            <div className="flow-rename-actions">
              <button type="button" className="flow-top-btn flow-top-btn-neutral" onClick={closeRenameFlowModal}>
                Cancelar
              </button>
              <button type="submit" className="flow-top-btn flow-top-btn-primary">
                Salvar
              </button>
            </div>
          </form>
        </div>
      )}
      {activeAiSystemNode && (
        <AISystemModal
          systemTemplate={activeAiSystemTemplate}
          systemData={(activeAiSystemNode.data || {}) as Record<string, unknown>}
          onClose={() => setActiveAiSystemNodeId(null)}
        />
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
