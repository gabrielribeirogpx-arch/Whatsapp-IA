'use client';

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
import type { Connection, Edge, Node, ReactFlowInstance } from 'reactflow';
import 'reactflow/dist/style.css';
import { Clock, FileText, GitBranch, History, Image as ImageIcon, ListChecks, MessageSquare, MousePointerClick, RotateCcw, Zap } from 'lucide-react';

import ActionNode from '@/components/flow/nodes/ActionNode';
import ChoiceNode from '@/components/flow/nodes/ChoiceNode';
import ConditionNode from '@/components/flow/nodes/ConditionNode';
import DelayNode from '@/components/flow/nodes/DelayNode';
import MessageNode from '@/components/flow/nodes/MessageNode';
import { DocumentNode, ImageNode } from '@/components/flow/nodes/RichMediaNode';
import ButtonsNode from '@/components/flow/nodes/ButtonsNode';
import ListNode from '@/components/flow/nodes/ListNode';
import CreateFlowModal from '@/components/flows/CreateFlowModal';
import { apiFetch, getFlowGraph, getTenantSessionFromStorage, listFlowVersions, parseApiResponse, restoreFlowVersion } from '@/lib/api';
import { getLayoutedElements } from '@/lib/autoLayout';
import { orderChoiceChildrenEdges } from '@/lib/flowChoiceOrdering';
import { normalizeFlow } from '@/lib/flowNormalization';
import { FlowEdgePayload, FlowNodePayload, FlowVersionItem } from '@/lib/types';

const FETCH_TIMEOUT_MS = 8000;

const nodeTypes = {
  message: MessageNode,
  choice: ChoiceNode,
  condition: ConditionNode,
  delay: DelayNode,
  action: ActionNode,
  image_node: ImageNode,
  document_node: DocumentNode,
  buttons_node: ButtonsNode,
  list_node: ListNode,
  IMAGE_NODE: ImageNode,
  DOCUMENT_NODE: DocumentNode,
  BUTTONS_NODE: ButtonsNode,
  LIST_NODE: ListNode,
  messageNode: MessageNode,
  choiceNode: ChoiceNode,
  conditionNode: ConditionNode,
  delayNode: DelayNode,
  actionNode: ActionNode,
};

type FlowNodeKind = 'message' | 'choice' | 'condition' | 'delay' | 'action' | 'image_node' | 'document_node' | 'buttons_node' | 'list_node';
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
  image_node: { label: 'Imagem', type: 'image_node', data: { media_url: '', caption: '' } },
  document_node: { label: 'Documento', type: 'document_node', data: { document_url: '', filename: '', caption: '' } },
  buttons_node: {
    label: 'Botões',
    type: 'buttons_node',
    data: { body_text: '', buttons: [{ id: 'button-1', label: 'Vendas', handleId: 'vendas' }, { id: 'button-2', label: 'Suporte', handleId: 'suporte' }] },
  },
  list_node: {
    label: 'Lista',
    type: 'list_node',
    data: { body_text: '', sections: [{ title: 'Opções', rows: [{ id: 'row-1', title: 'Vendas', handleId: 'vendas' }, { id: 'row-2', title: 'Suporte', handleId: 'suporte' }] }] },
  },
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


const serializeFlowGraph = (nodes: Node[], edges: Edge[]) => {
  const payloadNodes: FlowNodePayload[] = nodes.map((node) => {
    const nodeData = node.data || {};
    const { onChange, onToggleStart, running, hasValidationError, ...cleanData } = nodeData as Record<string, unknown>;

    return {
      id: node.id,
      type: node.type || 'message',
      position: node.position || { x: 0, y: 0 },
      data: {
        ...cleanData,
        isStart: !!cleanData.isStart,
      },
    };
  });

  const nodeTypeById = new Map(nodes.map((node) => [node.id, node.type]));
  const cleanEdges: FlowEdgePayload[] = edges
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
type EditorRow = { id?: string; title?: string; handleId?: string };
type EditorSection = { title?: string; rows?: EditorRow[] };

const toText = (value: unknown) => (typeof value === 'string' ? value : value == null ? '' : String(value));
const fieldHandleId = (value: string, fallback: string) => value.toLowerCase().trim().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '') || fallback;
const getBuilderNodeKind = (node?: Node | null) => String(node?.type || 'message').toLowerCase();
const getBuilderNodeTitle = (node?: Node | null) => NODE_PRESETS[getBuilderNodeKind(node) as FlowNodeKind]?.label || 'Node';
const getMiniMapNodeColor = (type: string) => {
  const normalized = type.toLowerCase();
  if (['message', 'image_node', 'document_node'].includes(normalized)) return '#3b82f6';
  if (['buttons_node', 'list_node'].includes(normalized)) return '#16a34a';
  if (['choice', 'condition', 'delay', 'action'].includes(normalized)) return '#f97316';
  return '#94a3b8';
};

function FlowNodeEditorPanel({
  node,
  draft,
  onDraftChange,
  onClose,
  onUpload,
  isUploading,
  uploadError,
}: {
  node: Node | null;
  draft: Record<string, unknown>;
  onDraftChange: (patch: Record<string, unknown>) => void;
  onClose: () => void;
  onUpload: (file: File | null, mediaType: 'image' | 'document') => void;
  isUploading: boolean;
  uploadError: string | null;
}) {
  if (!node) return null;
  const kind = getBuilderNodeKind(node);
  const title = getBuilderNodeTitle(node);
  const buttons = ((draft.buttons as EditorButton[] | undefined) || []).slice(0, kind === 'buttons_node' ? 3 : undefined);
  const sections = ((draft.sections as EditorSection[] | undefined) || [{ title: 'Opções', rows: [] }]);
  const rows = sections.flatMap((section) => section.rows || []);
  const updateButton = (index: number, label: string) => {
    const next = [...buttons];
    next[index] = { ...next[index], label, handleId: fieldHandleId(label, `option_${index + 1}`) };
    onDraftChange({ buttons: next });
  };
  const addButton = () => {
    const nextIndex = buttons.length + 1;
    if (kind === 'buttons_node' && buttons.length >= 3) return;
    onDraftChange({ buttons: [...buttons, { id: `${node.id}-button-${nextIndex}`, label: `Opção ${nextIndex}`, handleId: `option_${nextIndex}` }] });
  };
  const updateRow = (index: number, titleValue: string) => {
    const baseSection = sections[0] || { title: 'Opções', rows: [] };
    const nextRows = [...(baseSection.rows || [])];
    nextRows[index] = { ...nextRows[index], title: titleValue, handleId: fieldHandleId(titleValue, `option_${index + 1}`) };
    onDraftChange({ sections: [{ ...baseSection, rows: nextRows }, ...sections.slice(1)] });
  };
  const addRow = () => {
    const baseSection = sections[0] || { title: 'Opções', rows: [] };
    const nextRows = [...(baseSection.rows || [])];
    const nextIndex = nextRows.length + 1;
    nextRows.push({ id: `${node.id}-row-${nextIndex}`, title: `Opção ${nextIndex}`, handleId: `option_${nextIndex}` });
    onDraftChange({ sections: [{ ...baseSection, rows: nextRows }, ...sections.slice(1)] });
  };
  const removeRow = (index: number) => {
    const baseSection = sections[0] || { title: 'Opções', rows: [] };
    onDraftChange({ sections: [{ ...baseSection, rows: (baseSection.rows || []).filter((_, rowIndex) => rowIndex !== index) }, ...sections.slice(1)] });
  };

  return (
    <aside className="flow-node-editor-panel">
      <div className="flow-node-editor-header">
        <div>
          <span className="flow-node-editor-kicker">Editar bloco</span>
          <h3>{title}</h3>
        </div>
        <button type="button" onClick={onClose} aria-label="Fechar painel">×</button>
      </div>

      <div className="flow-node-editor-content">
        {kind === 'message' && (
          <label className="flow-editor-field">
            Mensagem
            <textarea value={toText(draft.content)} onChange={(event) => onDraftChange({ content: event.target.value })} placeholder="Digite a mensagem..." />
          </label>
        )}

        {kind === 'image_node' && (
          <>
            <label className="flow-editor-field">
              Arquivo
              <input type="file" accept="image/*" disabled={isUploading} onChange={(event) => onUpload(event.target.files?.[0] || null, 'image')} />
            </label>
            <label className="flow-editor-field">
              URL da imagem
              <input value={toText(draft.media_url)} onChange={(event) => onDraftChange({ media_url: event.target.value })} placeholder="https://..." />
            </label>
            <label className="flow-editor-field">
              Legenda
              <textarea value={toText(draft.caption)} onChange={(event) => onDraftChange({ caption: event.target.value })} placeholder="Legenda opcional" />
            </label>
          </>
        )}

        {kind === 'document_node' && (
          <>
            <label className="flow-editor-field">
              Arquivo
              <input type="file" accept="application/pdf,.pdf,.doc,.docx" disabled={isUploading} onChange={(event) => onUpload(event.target.files?.[0] || null, 'document')} />
            </label>
            <label className="flow-editor-field">
              URL do documento
              <input value={toText(draft.document_url)} onChange={(event) => onDraftChange({ document_url: event.target.value })} placeholder="https://..." />
            </label>
            <label className="flow-editor-field">
              Nome
              <input value={toText(draft.filename)} onChange={(event) => onDraftChange({ filename: event.target.value })} placeholder="cardapio.pdf" />
            </label>
            <label className="flow-editor-field">
              Legenda
              <textarea value={toText(draft.caption)} onChange={(event) => onDraftChange({ caption: event.target.value })} placeholder="Legenda opcional" />
            </label>
          </>
        )}

        {kind === 'buttons_node' && (
          <>
            <label className="flow-editor-field">
              Texto principal
              <textarea value={toText(draft.body_text)} onChange={(event) => onDraftChange({ body_text: event.target.value })} placeholder="Como posso ajudar?" />
            </label>
            <div className="flow-editor-repeatable">
              <strong>Botões ({buttons.length}/3)</strong>
              {buttons.map((button, index) => (
                <div key={button.id || index} className="flow-editor-row">
                  <input value={button.label || ''} onChange={(event) => updateButton(index, event.target.value)} placeholder={`Botão ${index + 1}`} />
                  <button type="button" onClick={() => onDraftChange({ buttons: buttons.filter((_, buttonIndex) => buttonIndex !== index) })}>Remover</button>
                </div>
              ))}
              <button type="button" className="flow-editor-secondary-btn" onClick={addButton} disabled={buttons.length >= 3}>+ Adicionar botão</button>
            </div>
          </>
        )}

        {kind === 'list_node' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> WhatsApp Interactive List <span>META LIST</span></div>
            <label className="flow-editor-field">
              Texto principal
              <textarea value={toText(draft.body_text)} onChange={(event) => onDraftChange({ body_text: event.target.value })} placeholder="Escolha uma opção" />
            </label>
            <div className="flow-editor-repeatable">
              <strong>Itens ({rows.length})</strong>
              {rows.map((row, index) => (
                <div key={row.id || index} className="flow-editor-row">
                  <input value={row.title || ''} onChange={(event) => updateRow(index, event.target.value)} placeholder={`Item ${index + 1}`} />
                  <button type="button" onClick={() => removeRow(index)}>Remover</button>
                </div>
              ))}
              <button type="button" className="flow-editor-secondary-btn" onClick={addRow}>+ Adicionar item</button>
            </div>
          </>
        )}

        {kind === 'choice' && (
          <>
            <div className="flow-editor-info-card"><strong>Tipo:</strong> Lógica interna do fluxo <span>LOGIC</span></div>
            <label className="flow-editor-field">
              Texto
              <textarea value={toText(draft.content)} onChange={(event) => onDraftChange({ content: event.target.value })} placeholder="Roteamento interno" />
            </label>
            <div className="flow-editor-repeatable">
              <strong>Opções de roteamento</strong>
              {buttons.map((button, index) => (
                <div key={button.id || index} className="flow-editor-row">
                  <input value={button.label || ''} onChange={(event) => updateButton(index, event.target.value)} placeholder={`Opção ${index + 1}`} />
                  <button type="button" onClick={() => onDraftChange({ buttons: buttons.filter((_, buttonIndex) => buttonIndex !== index) })}>Remover</button>
                </div>
              ))}
              <button type="button" className="flow-editor-secondary-btn" onClick={addButton}>+ Adicionar opção</button>
            </div>
          </>
        )}

        {kind === 'condition' && (
          <label className="flow-editor-field">
            Regras / palavras-chave
            <textarea value={toText(draft.condition)} onChange={(event) => onDraftChange({ condition: event.target.value })} placeholder="sim, suporte, ajuda" />
            <small>Separe múltiplas palavras por vírgula. Saídas: Sim e Não.</small>
          </label>
        )}

        {kind === 'delay' && (
          <label className="flow-editor-field">
            Tempo em segundos
            <input type="number" min="0" value={toText(draft.content || draft.delay || draft.seconds)} onChange={(event) => onDraftChange({ content: event.target.value })} />
          </label>
        )}

        {kind === 'action' && (
          <label className="flow-editor-field">
            Nome da ação
            <input value={toText(draft.action)} onChange={(event) => onDraftChange({ action: event.target.value })} placeholder="Ex.: notificar equipe" />
          </label>
        )}

        <label className="flow-editor-checkbox">
          <input type="checkbox" checked={!!draft.is_terminal} onChange={(event) => onDraftChange({ is_terminal: event.target.checked })} />
          Este é o fim do fluxo
        </label>
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

const UNSAVED_CHANGES_MESSAGE = 'Você possui alterações não salvas. Deseja sair mesmo assim?';
const AUTOSAVE_DELAY_MS = 5000;

export default function FlowBuilderClient({ flowId: _initialFlowId }: FlowBuilderClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const flowIdFromUrl = searchParams.get('flow_id') || searchParams.get('flowId') || _initialFlowId || '';
  const showDebugFlowActionsFlag = process.env.NEXT_PUBLIC_SHOW_DEBUG_FLOW_ACTIONS === 'true';
  const [flows, setFlows] = useState<Array<{ id: string; name?: string | null; created_at?: string | null; is_active?: boolean; status?: string | null; is_published?: boolean | null }>>([]);
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
  console.log('FLOW SELECIONADO:', selectedFlowId);
  console.log('FLOW ATIVO:', activeFlowId);
  console.log('FLOWS DISPONÍVEIS:', flows);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>(initialEdges);
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
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number } | null>(null);
  const [isTyping, setIsTyping] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [userInputText, setUserInputText] = useState('');
  const [isVersionsModalOpen, setIsVersionsModalOpen] = useState(false);
  const [isLoadingVersions, setIsLoadingVersions] = useState(false);
  const [isRestoringVersion, setIsRestoringVersion] = useState(false);
  const [isCreatingFlow, setIsCreatingFlow] = useState(false);
  const [isCreateFlowOpen, setIsCreateFlowOpen] = useState(false);
  const [flowVersions, setFlowVersions] = useState<FlowVersionItem[]>([]);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [flowSource, setFlowSource] = useState<string>('version');
  const [showEmptyFlowWarning, setShowEmptyFlowWarning] = useState(false);
  const [flowValidationError, setFlowValidationError] = useState<string | null>(null);
  const [validationWarnings, setValidationWarnings] = useState<FlowValidationIssue[]>([]);
  const [validationErrors, setValidationErrors] = useState<FlowValidationIssue[]>([]);
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [isForceRepublishing, setIsForceRepublishing] = useState(false);
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
  const isSavingRef = useRef(false);
  const lastPersistedFlowSignatureRef = useRef<string | null>(null);
  const saveStatusTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const playbackIdRef = useRef(0);
  const isMountedRef = useRef(true);

  const flowSelectRef = useRef<HTMLDivElement | null>(null);
  const flowCanvasRef = useRef<HTMLElement | null>(null);
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

  const canSeeDebugFlowActions = useMemo(() => {
    if (showDebugFlowActionsFlag) return true;
    if (typeof window === 'undefined') return false;

    try {
      const tenantRaw = window.localStorage.getItem('tenant');
      const parsed = tenantRaw ? JSON.parse(tenantRaw) as Record<string, unknown> : {};
      const role = String(parsed?.role || parsed?.user_role || parsed?.profile || '').toLowerCase();
      const isAdminLike = role.includes('admin') || role.includes('dev');
      return isAdminLike;
    } catch {
      return false;
    }
  }, [showDebugFlowActionsFlag]);
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

  const saveButtonLabel = useMemo(() => {
    if (flowSaveStatus === 'saving') return 'Salvando...';
    if (flowSaveStatus === 'success') return 'Salvo agora';
    if (flowSaveStatus === 'error') return 'Erro ao salvar';
    return '✓ Salvar alterações';
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
    nodesRef.current = nodes;
  }, [nodes]);
  useEffect(() => {
    edgesRef.current = edges;
  }, [edges]);

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

  const openNodeEditor = useCallback((node: Node, source: 'click' | 'selection' = 'click') => {
    const canvasWidthBefore = flowCanvasRef.current?.getBoundingClientRect().width ?? 0;
    console.info('[NODE CLICK]', { node_id: node.id, node_type: node.type, source });
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

  const handleReactFlowNodeClick = useCallback((_: unknown, node: Node) => {
    openNodeEditor(node, 'click');
  }, [openNodeEditor]);

  const handleReactFlowSelectionChange = useCallback(({ nodes: selectedNodes }: { nodes: Node[] }) => {
    if (selectedNodes.length === 1) {
      openNodeEditor(selectedNodes[0], 'selection');
    }
  }, [openNodeEditor]);

  const uploadEditorMedia = useCallback(async (file: File | null, mediaType: 'image' | 'document') => {
    if (!file) return;
    setMediaUploadError(null);
    setIsMediaUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const response = await apiFetch('/api/flow-media/upload', { method: 'POST', body: formData });
      const result = await parseApiResponse<{ url: string; filename?: string }>(response);
      const patch = mediaType === 'image'
        ? { media_url: result.url }
        : { document_url: result.url, filename: result.filename || nodeEditorDraft.filename };
      setNodeEditorDraft((prev) => ({
        ...prev,
        ...patch,
      }));
      const nodeId = selectedNodeIdRef.current;
      if (nodeId) {
        console.info('[NODE CHANGED]', { node_id: nodeId, patch_keys: Object.keys(patch), media_type: mediaType });
        updateNodeData(nodeId, patch);
        markFlowDirty('media_uploaded', { node_id: nodeId, media_type: mediaType, url: result.url });
      }
    } catch (error) {
      setMediaUploadError(error instanceof Error ? error.message : 'Falha ao enviar arquivo');
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
          isStart: node.data?.isStart ?? false,
          buttons: node.type === 'choice' ? normalizeChoiceButtons(node.id, node.data?.buttons) : (node.type === 'buttons_node' ? normalizeChoiceButtons(node.id, node.data?.buttons).slice(0, 3) : node.data?.buttons),
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
      const resolvedSource = payload?.source || 'unknown';
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

      const nodesToRender = formattedNodes;
      let edgesToRender = formattedEdges;
      if (nodesToRender.length === 0) {
        console.info('[BUILDER EMPTY FLOW]', { flow_id: flowId, nodes_count: 0, edges_count: edgesToRender.length });
        setNodes([]);
        setEdges([]);
        setOperationError(null);
        setFlowValidationError(null);
        setValidationWarnings([]);
        setValidationErrors([]);
        lastPersistedFlowSignatureRef.current = getFlowGraphSignature(serializeFlowGraph([], []));
        return;
      }

      const hasStoredPositions = nodesToRender.some((n) => n.position && (n.position.x !== 0 || n.position.y !== 0));
      if (hasStoredPositions) {
        const orderedEdges = orderChoiceChildrenEdges(nodesToRender, edgesToRender);
        setNodes(nodesToRender);
        setEdges(orderedEdges);
        lastPersistedFlowSignatureRef.current = getFlowGraphSignature(serializeFlowGraph(nodesToRender, orderedEdges));
        requestAnimationFrame(() => { rfInstance?.fitView(); });
      } else {
        const layoutedFlow = applyLayoutAndSetFlow(nodesToRender, edgesToRender);
        lastPersistedFlowSignatureRef.current = getFlowGraphSignature(serializeFlowGraph(layoutedFlow.nodes, layoutedFlow.edges));
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
  }, [applyLayoutAndSetFlow, buildFlowEdge, buildFlowNode, rfInstance, setEdges, setNodes]);

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

    const safeFlow = getCurrentSerializedFlow();
    const endpoint = `/api/flows/${selectedFlowId}`;

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

  const handleForceRepublish = useCallback(async () => {
    if (!selectedFlowId || isForceRepublishing) return;

    setIsForceRepublishing(true);
    try {
      const response = await apiFetch(`/api/flows/${selectedFlowId}/force-republish-current`, { method: 'POST' });
      await parseApiResponse(response);
      console.log('[FORCE REPUBLISH]', { flowId: selectedFlowId, status: 200 });
      toast.success('Flow republicado com sucesso');
      await loadFlow(selectedFlowId);
      console.log('[PUBLISHED VERSION UPDATED]', { flowId: selectedFlowId });
    } catch (error) {
      console.error('[FORCE REPUBLISH] erro ao republicar flow', error);
    } finally {
      setIsForceRepublishing(false);
    }
  }, [isForceRepublishing, loadFlow, selectedFlowId, toast]);

  const handleActivateFlow = useCallback(async () => {
    if (!selectedFlowId) return;
    if (validationErrors.length > 0) return;

    const currentNodes = rfInstance?.getNodes?.() || [];
    const currentEdges = rfInstance?.getEdges?.() || [];
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

      console.log('[PUBLISH REQUEST]', { flowId: selectedFlowId });
      const response = await apiFetch(`/api/flows/${selectedFlowId}/publish`, { method: 'POST', body: JSON.stringify({}) });
      if (!response.ok) {
        const body = await response.text();
        console.error('[PUBLISH ERROR BODY]', body);
        throw new Error(`HTTP ${response.status}: ${body}`);
      }
      const publishData = await parseApiResponse(response);
      console.log('[PUBLISH RESPONSE]', { flowId: selectedFlowId, status: response.status, payload: publishData });

      const activateResponse = await apiFetch(`/api/flows/${selectedFlowId}/activate`, { method: 'PUT' });
      await parseApiResponse(activateResponse);

      setActiveFlowId(selectedFlowId);
      setFlows((prev) => prev.map((flow) => ({ ...flow, is_active: flow.id === selectedFlowId })));
      await loadFlow(selectedFlowId);
    } catch (error) {
      console.error('[PUBLISH ERROR]', { flowId: selectedFlowId, error });
      const message = error instanceof Error && error.message ? error.message : 'Não foi possível publicar o fluxo.';
      toast.error(`Falha ao publicar: ${message}`);
    }
  }, [flowDirty, getCurrentSerializedFlow, handleSaveFlow, loadFlow, rfInstance, selectedFlowId, toast, validationErrors.length]);

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

  const decoratedEdges = useMemo(
    () =>
      safeEdges.map((edge) => ({
        ...edge,
        className: activeEdgeIds.includes(edge.id) ? 'flow-edge flow-edge-active' : 'flow-edge',
      })),
    [activeEdgeIds, safeEdges],
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

        <span className="dash-nav-section">Comunicação</span>
        {([
          { kind: 'message' as FlowNodeKind, label: 'Mensagem', icon: MessageSquare },
          { kind: 'image_node' as FlowNodeKind, label: 'Imagem', icon: ImageIcon },
          { kind: 'document_node' as FlowNodeKind, label: 'Documento', icon: FileText },
        ]).map(({ kind, label, icon: Icon }) => (
          <button key={kind} type="button" className="dash-nav-item" onClick={() => addNode(kind)} title={label} style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
            <Icon size={18} strokeWidth={1.8} className="text-current" />
            <span className="dash-nav-label">{label}</span>
          </button>
        ))}

        <span className="dash-nav-section">Interação</span>
        {([
          { kind: 'buttons_node' as FlowNodeKind, label: 'Botões', icon: MousePointerClick },
          { kind: 'list_node' as FlowNodeKind, label: 'Lista', icon: ListChecks },
        ]).map(({ kind, label, icon: Icon }) => (
          <button key={kind} type="button" className="dash-nav-item" onClick={() => addNode(kind)} title={label} style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
            <Icon size={18} strokeWidth={1.8} className="text-current" />
            <span className="dash-nav-label">{label}</span>
          </button>
        ))}

        <span className="dash-nav-section">Lógica</span>
        {([
          { kind: 'choice' as FlowNodeKind, label: 'Escolha', icon: ListChecks },
          { kind: 'condition' as FlowNodeKind, label: 'Condição', icon: GitBranch },
          { kind: 'delay' as FlowNodeKind, label: 'Delay', icon: Clock },
          { kind: 'action' as FlowNodeKind, label: 'Ação', icon: Zap },
        ]).map(({ kind, label, icon: Icon }) => (
          <button key={kind} type="button" className="dash-nav-item" onClick={() => addNode(kind)} title={label} style={{ border: 'none', background: 'none', cursor: 'pointer', width: '100%', textAlign: 'left' }}>
            <Icon size={18} strokeWidth={1.8} className="text-current" />
            <span className="dash-nav-label">{label}</span>
          </button>
        ))}

        <div className="dash-nav-divider" />

        <button
          type="button"
          className="dash-nav-item"
          onClick={() => void handleSaveFlow(false, { showToast: true })}
          disabled={isSaving || !selectedFlowId}
          title={isEditing ? 'Salvar alterações' : 'Visualização'}
          style={{ border: flowDirty ? '1px solid #22c55e' : 'none', background: flowDirty ? '#ecfdf5' : 'none', cursor: isSaving ? 'not-allowed' : 'pointer', width: '100%', textAlign: 'left', opacity: isSaving ? 0.6 : 1 }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
            <polyline points="17 21 17 13 7 13 7 21"/>
            <polyline points="7 3 7 8 15 8"/>
          </svg>
          <span className="dash-nav-label">{saveButtonLabel}</span>
        </button>

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
        <div className="flow-builder-breadcrumb" aria-label="Breadcrumb">
          <Link href="/dashboard/flows">Fluxos</Link>
          <span aria-hidden="true">›</span>
          <span>{selectedFlow ? (selectedFlow.name || selectedFlow.id) : 'Selecione um fluxo'}</span>
          {flowDirty && (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: '#b45309', background: '#fffbeb', border: '1px solid #f59e0b', borderRadius: 999, padding: '3px 9px', fontSize: 12, fontWeight: 600 }}>
              ● Alterações não salvas
            </span>
          )}
          <span aria-hidden="true">›</span>
          <strong>Builder</strong>
        </div>
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
                    <div className="flow-selected-label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, minWidth: 0 }}>
                      <span className="flow-name" style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {selectedFlow ? (selectedFlow.name || selectedFlow.id) : (normalizedFlows.length === 0 ? 'Nenhum flow disponível' : 'Selecione um flow')}
                      </span>
                      {flowDirty && (
                        <span className="flow-badge" style={{ background: '#FEF3C7', color: '#92400E' }}>● Alterações não salvas</span>
                      )}
                      {selectedFlow && (() => {
                        const badge = getFlowBadge(selectedFlow);
                        return <span className="flow-badge" style={badge.style}>{badge.label}</span>;
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
              <div className="flow-toolbar-group flow-toolbar-group-primary-actions">
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
              {canSeeDebugFlowActions && (
                <div className="flow-toolbar-group flow-toolbar-group-debug">
                  <button
                    type="button"
                    className="flow-top-btn flow-top-btn-neutral"
                    onClick={() => {
                      void handleForceRepublish();
                    }}
                    disabled={!selectedFlowId || isForceRepublishing}
                  >
                    {isForceRepublishing ? 'Republicando...' : 'Force Republish'}
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
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
            {([
              { kind: 'message' as FlowNodeKind, label: 'Mensagem', icon: MessageSquare },
              { kind: 'choice' as FlowNodeKind, label: 'Escolha', icon: ListChecks },
              { kind: 'image_node' as FlowNodeKind, label: 'Imagem', icon: ImageIcon },
              { kind: 'document_node' as FlowNodeKind, label: 'Documento', icon: FileText },
              { kind: 'buttons_node' as FlowNodeKind, label: 'Botões', icon: MousePointerClick },
              { kind: 'list_node' as FlowNodeKind, label: 'Lista', icon: ListChecks },
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
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={handleReactFlowNodeClick}
          onSelectionChange={handleReactFlowSelectionChange}
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
