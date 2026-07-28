import type { Edge, Node } from 'reactflow';

export type FlowValidationIssue = { code: string; message: string; summary?: string; node_id?: string | null; node_type?: string | null; node_label?: string | null; field?: string | null; focus_field?: string | null; severity?: 'error' | 'warning'; suggestion?: string; metadata?: Record<string, unknown> };
const issue = (code: string, message: string, node?: Node, field?: string): FlowValidationIssue => ({ code, message, node_id: node?.id || null, node_type: String(node?.type || ''), node_label: String(node?.data?.label || node?.data?.title || node?.type || 'Fluxo'), field, focus_field: field, severity: 'error' });

/** Fast, conservative checks before publish. The backend remains authoritative. */
export function validateFlowLocally(nodes: Node[], edges: Edge[]): FlowValidationIssue[] {
  const issues: FlowValidationIssue[] = []; const outgoing = new Map<string, Edge[]>();
  edges.forEach((edge) => outgoing.set(edge.source, [...(outgoing.get(edge.source) || []), edge]));
  const starts = nodes.filter((node) => Boolean(node.data?.isStart));
  if (!starts.length) issues.push(issue('START_MISSING', 'Defina um node inicial.'));
  if (starts.length > 1) issues.push(issue('MULTIPLE_STARTS', 'O fluxo deve ter apenas um node inicial.'));
  nodes.forEach((node) => {
    const data = (node.data || {}) as Record<string, unknown>; const type = String(node.type || data.type || '').toLowerCase(); const next = outgoing.get(node.id) || [];
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
  }); return issues;
}

export function extractValidationIssues(payload: unknown): FlowValidationIssue[] {
  const body = (payload || {}) as Record<string, unknown>; const detail = (body.detail || {}) as Record<string, unknown>;
  const values = body.errors || detail.errors || (body.error && typeof body.error === 'object' ? [body.error] : detail.error && typeof detail.error === 'object' ? [detail.error] : []);
  return Array.isArray(values) ? values.filter((value): value is FlowValidationIssue => Boolean(value && typeof value === 'object' && (value as FlowValidationIssue).message)) : [];
}
