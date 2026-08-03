import type { Edge, Node } from 'reactflow';
import { normalizeDataCollectionHandle } from './dataCollectionHandles';

export type FlowValidationIssue = { code: string; message: string; summary?: string; node_id?: string | null; node_type?: string | null; node_label?: string | null; field?: string | null; focus_field?: string | null; severity?: 'error' | 'warning'; suggestion?: string; metadata?: Record<string, unknown> };
const issue = (code: string, message: string, node?: Node, field?: string): FlowValidationIssue => ({ code, message, node_id: node?.id || null, node_type: String(node?.type || ''), node_label: String(node?.data?.label || node?.data?.title || node?.type || 'Fluxo'), field, focus_field: field, severity: 'error' });

/** Node kinds understood by the editor-side validator. */
export const VALID_BUILDER_NODE_TYPES = new Set([
  'start', 'message', 'data_collection', 'choice', 'choice_dynamic', 'condition',
  'delay', 'action', 'mcp_tool', 'media', 'cta_url', 'cta_link', 'ai_rag',
  'ai_response', 'ai_classification', 'ai_extraction', 'ai_summary', 'ai_agent',
  'ai_supervisor', 'ai_dispatcher', 'ai_greeting', 'ai_calendar_agent',
  'ai_safe_fallback', 'ai_system',
]);

/**
 * Calculates reachability from Start using the graph itself as the authority.
 * Every valid edge whose source is the current node is traversed; handles and
 * node kinds intentionally have no bearing on graph connectivity.
 */
export function calculateReachableNodeIds(nodes: Node[], edges: Edge[]): Set<string> {
  const nodeIds = new Set(nodes.map((node) => node.id));
  const adjacency = new Map<string, string[]>();
  edges.forEach((edge) => {
    if (!nodeIds.has(edge.source) || !nodeIds.has(edge.target)) return;
    adjacency.set(edge.source, [...(adjacency.get(edge.source) || []), edge.target]);
  });
  const starts = nodes.filter((node) => Boolean(node.data?.isStart));
  const pending = starts.length === 1 ? [starts[0].id] : [];
  const reachable = new Set<string>();
  while (pending.length) {
    const current = pending.pop()!;
    if (reachable.has(current)) continue;
    reachable.add(current);
    pending.push(...(adjacency.get(current) || []));
  }
  return reachable;
}

/** Fast, conservative checks before publish. The backend remains authoritative. */
export function validateFlowLocally(nodes: Node[], edges: Edge[]): FlowValidationIssue[] {
  const issues: FlowValidationIssue[] = []; const outgoing = new Map<string, Edge[]>();
  edges.forEach((edge) => outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge]));
  const starts = nodes.filter((node) => Boolean(node.data?.isStart));
  if (!starts.length) issues.push(issue('START_MISSING', 'Defina um node inicial.'));
  if (starts.length > 1) issues.push(issue('MULTIPLE_STARTS', 'O fluxo deve ter apenas um node inicial.'));
  const reachable = calculateReachableNodeIds(nodes, edges);
  nodes.forEach((node) => {
    const data = (node.data || {}) as Record<string, unknown>; const type = String(node.type || data.type || '').toLowerCase(); const next = outgoing.get(node.id) || [];
    if (starts.length === 1 && !reachable.has(node.id)) issues.push(issue('NODE_ORPHAN', 'Este node não está conectado ao caminho iniciado pelo Start.', node, 'connections'));
    const terminal = ['is_terminal', 'isEnd', 'isFinal', 'endFlow'].some((key) => Boolean(data[key]));
    if (type === 'message' || type === 'start') {
      if (!String(data.content || data.text || data.message || '').trim()) issues.push(issue('MESSAGE_EMPTY', 'Adicione o conteúdo da mensagem.', node, 'content'));
      if (!next.length && !terminal) issues.push(issue('MESSAGE_REQUIRES_OUTPUT', 'Conecte esta mensagem a outro node ou marque-a como fim do fluxo.', node, 'connections'));
    }
    if (type === 'condition') {
      const rules = (data.conditions || data.rules) as unknown;
      if (!Array.isArray(rules) || !rules.length) issues.push(issue('CONDITION_EMPTY', 'Adicione pelo menos uma regra.', node, 'conditions'));
      else if (rules.some((value) => { const rule = (value || {}) as Record<string, unknown>; return !String(rule.field || rule.left || rule.path || '').trim() || !String(rule.operator || rule.op || '').trim() || (rule.value ?? rule.right) === '' || (rule.value ?? rule.right) == null; })) issues.push(issue('CONDITION_INCOMPLETE', 'Preencha campo, operador e valor.', node, 'conditions'));
      const handles = new Set(next.map((edge) => String(edge.sourceHandle || edge.data?.sourceHandle || '').toLowerCase()));
      if (!handles.has('true') || !handles.has('false')) issues.push(issue('CONDITION_NEEDS_BOTH_BRANCHES', 'Conecte as saídas Sim e Não.', node, 'connections'));
    }
    if ((type === 'choice' && String(data.options_mode || data.option_mode || 'fixed') === 'dynamic') || type === 'choice_dynamic') {
      if (!String(data.options_variable || data.source_variable || '').trim()) issues.push(issue('DYNAMIC_CHOICE_VARIABLE_REQUIRED', 'Selecione a variável de origem.', node, 'options_variable'));
      if (!String(data.label_field || '').trim()) issues.push(issue('DYNAMIC_CHOICE_LABEL_REQUIRED', 'Defina o campo do título.', node, 'label_field'));
      if (!String(data.value_field || '').trim()) issues.push(issue('DYNAMIC_CHOICE_VALUE_REQUIRED', 'Defina o campo do valor.', node, 'value_field'));
    }
    if (type === 'data_collection') {
      const variable = String(data.variable_name || '');
      if (!variable) issues.push(issue('DATA_COLLECTION_VARIABLE_REQUIRED', 'Defina o nome da variável.', node, 'variable_name'));
      else if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(variable)) issues.push(issue('DATA_COLLECTION_VARIABLE_INVALID', 'Use letras, números e underscore; não comece com número.', node, 'variable_name'));
      if (Number(data.max_attempts || 0) < 1) issues.push(issue('DATA_COLLECTION_ATTEMPTS_INVALID', 'O máximo de tentativas deve ser maior que zero.', node, 'max_attempts'));
      const options = Array.isArray(data.options) ? data.options as Array<Record<string, unknown>> : [];
      if (data.data_type === 'choice' && !options.length) issues.push(issue('DATA_COLLECTION_OPTIONS_REQUIRED', 'Adicione pelo menos uma opção.', node, 'options'));
      const handles = new Set(next.map((edge) => normalizeDataCollectionHandle(edge.sourceHandle ?? edge.data?.sourceHandle ?? edge.data?.source_handle)));
      if (!handles.has('success')) issues.push(issue('DATA_COLLECTION_SUCCESS_REQUIRED', 'A saída Sucesso precisa estar conectada.', node, 'connections'));
    }
    if (type === 'mcp_tool') {
      if (!String(data.connection_id || '').trim()) issues.push(issue('MCP_CONNECTION_REQUIRED', 'Selecione uma conexão MCP.', node, 'connection_id'));
      if (!String(data.tool_name || '').trim()) issues.push(issue('MCP_TOOL_REQUIRED', 'Selecione uma ferramenta MCP.', node, 'tool_name'));
      if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(String(data.output_variable || ''))) issues.push(issue('MCP_OUTPUT_INVALID', 'Defina uma variável de saída válida.', node, 'output_variable'));
      const timeout = Number(data.timeout_seconds || 0); if (timeout < 1 || timeout > 60) issues.push(issue('MCP_TIMEOUT_INVALID', 'O timeout deve ficar entre 1 e 60 segundos.', node, 'timeout_seconds'));
      const handles = new Set(next.map((edge) => String(edge.sourceHandle || edge.data?.sourceHandle || '').toLowerCase()));
      if (!terminal && !handles.has('success')) issues.push(issue('MCP_SUCCESS_REQUIRED', 'Conecte a saída Sucesso ou marque o node como final.', node, 'connections'));
      if (!terminal && !handles.has('error')) issues.push(issue('MCP_ERROR_REQUIRED', 'Conecte a saída Erro.', node, 'connections'));
      if (String(data.tool_classification || '').toUpperCase() === 'DESTRUCTIVE' && (data.destructive_confirmed !== true || !String(data.idempotency_key || '').trim())) issues.push(issue('MCP_DESTRUCTIVE_CONFIRMATION_REQUIRED', 'Ação destrutiva exige confirmação e idempotency key.', node, 'destructive_confirmed'));
    }
  }); return issues;
}

export function extractValidationIssues(payload: unknown): FlowValidationIssue[] {
  const body = (payload || {}) as Record<string, unknown>; const detail = (body.detail || {}) as Record<string, unknown>;
  const values = body.errors || detail.errors || (body.error && typeof body.error === 'object' ? [body.error] : detail.error && typeof detail.error === 'object' ? [detail.error] : []);
  return Array.isArray(values) ? values.filter((value): value is FlowValidationIssue => Boolean(value && typeof value === 'object' && (value as FlowValidationIssue).message)) : [];
}
