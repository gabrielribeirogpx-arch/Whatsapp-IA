'use client';

import { memo } from 'react';
import { Handle, NodeProps, Position } from 'reactflow';

export type AiSystemNodeData = {
  name?: string;
  label?: string;
  system_type?: string;
  internal_nodes?: unknown[];
  internal_edges?: unknown[];
  tools?: string[];
  integrations?: string[];
  statuses?: string[];
  average_time?: string;
  onOpenSystem?: (nodeId: string) => void;
  running?: boolean;
  isStart?: boolean;
  hasValidationError?: boolean;
};

export type InternalCard = {
  id: string;
  visualKey: string;
  type: 'agent' | 'integration';
  icon: string;
  title: string;
  description: string;
  tone: 'blue' | 'green' | 'orange' | 'purple' | 'amber' | 'slate';
};

export type InternalEdge = { source: string; target: string };

export const SYSTEM_BADGES: Record<string, string> = {
  ai_calendar_agent_system: 'Agenda Inteligente',
  ai_support_agent_system: 'Atendimento Inteligente',
  ai_sales_agent_system: 'Comercial Inteligente',
  ai_rag_agent_system: 'Conhecimento (RAG)',
  ai_mcp_advanced_system: 'MCP Automation',
  ai_custom_system: 'Sistema Personalizado',
  custom: 'Sistema Personalizado',
};

export const FRIENDLY_NODES: Record<string, Omit<InternalCard, 'id' | 'visualKey'>> = {
  ai_dispatcher: { type: 'agent', icon: '🧠', title: 'Entendimento', description: 'Identifica intenção', tone: 'blue' },
  dispatcher: { type: 'agent', icon: '🧠', title: 'Entendimento', description: 'Identifica intenção', tone: 'blue' },
  ai_greeting: { type: 'agent', icon: '💬', title: 'Conversa', description: 'Responde saudações', tone: 'green' },
  greeting: { type: 'agent', icon: '💬', title: 'Conversa', description: 'Responde saudações', tone: 'green' },
  ai_calendar_agent: { type: 'agent', icon: '📅', title: 'Agenda', description: 'Cria e consulta eventos', tone: 'orange' },
  calendar: { type: 'agent', icon: '📅', title: 'Agenda', description: 'Cria e consulta eventos', tone: 'orange' },
  ai_safe_fallback: { type: 'agent', icon: '🛡', title: 'Segurança', description: 'Fallback e proteção', tone: 'purple' },
  fallback: { type: 'agent', icon: '🛡', title: 'Segurança', description: 'Fallback e proteção', tone: 'purple' },
  google_calendar: { type: 'integration', icon: '📅', title: 'Google Calendar', description: 'Ferramenta conectada', tone: 'amber' },
};

const DEFAULT_INTERNAL_CARDS: InternalCard[] = ['dispatcher', 'greeting', 'calendar', 'google_calendar', 'fallback'].map((key) => ({ id: key, visualKey: key, ...FRIENDLY_NODES[key] }));
const DEFAULT_INTERNAL_EDGES: InternalEdge[] = [
  { source: 'dispatcher', target: 'greeting' },
  { source: 'dispatcher', target: 'calendar' },
  { source: 'calendar', target: 'google_calendar' },
  { source: 'google_calendar', target: 'fallback' },
];

const getRecordValue = (value: unknown, key: string): unknown => (value && typeof value === 'object' && key in value ? (value as Record<string, unknown>)[key] : undefined);
const textValue = (value: unknown): string => (typeof value === 'string' ? value : '');
const normalizeKey = (value: string) => value.trim().toLowerCase().replace(/^node_/, '');
const friendlyKeyForNode = (node: unknown) => normalizeKey(textValue(getRecordValue(node, 'type')) || textValue(getRecordValue(node, 'key')) || textValue(getRecordValue(node, 'id')));
const nodeId = (node: unknown) => textValue(getRecordValue(node, 'id')) || textValue(getRecordValue(node, 'key')) || friendlyKeyForNode(node);

export function toInternalCards(nodes: unknown[], integrations: string[]): InternalCard[] {
  const cards = nodes.map((node, index) => {
    const key = friendlyKeyForNode(node);
    const friendly = FRIENDLY_NODES[key] || { type: 'agent' as const, icon: '🤖', title: 'Agente', description: 'Especialista interno', tone: 'slate' as const };
    return { id: nodeId(node) || `${key}-${index}`, visualKey: key, ...friendly };
  });
  const hasCalendar = cards.some((card) => card.title === 'Google Calendar') || integrations.includes('google_calendar');
  if (hasCalendar && !cards.some((card) => card.id === 'google_calendar')) cards.push({ id: 'google_calendar', visualKey: 'google_calendar', ...FRIENDLY_NODES.google_calendar });
  return cards.length ? cards : DEFAULT_INTERNAL_CARDS;
}

export function toInternalEdges(edges: unknown[], cards: InternalCard[]): InternalEdge[] {
  const cardIds = new Set(cards.map((card) => card.id));
  const parsed = edges.map((edge) => ({ source: textValue(getRecordValue(edge, 'source')), target: textValue(getRecordValue(edge, 'target')) })).filter((edge) => cardIds.has(edge.source) && cardIds.has(edge.target));
  const calendarCard = cards.find((card) => card.visualKey === 'calendar' || card.visualKey === 'ai_calendar_agent');
  if (calendarCard && cardIds.has('google_calendar')) parsed.push({ source: calendarCard.id, target: 'google_calendar' });
  return parsed.length ? parsed : DEFAULT_INTERNAL_EDGES.filter((edge) => cardIds.has(edge.source) && cardIds.has(edge.target));
}


export function AISystemArchitectureGraph({ internalNodes, rawEdges, integrations }: { internalNodes: unknown[]; rawEdges: unknown[]; integrations: string[] }) {
  const graphCards = toInternalCards(internalNodes, integrations);
  const graphEdges = toInternalEdges(rawEdges, graphCards);
  const specialistCount = graphCards.filter((card) => card.type === 'agent').length || 4;
  const integrationCount = graphCards.filter((card) => card.type === 'integration').length || integrations.length || 1;

  return (
    <section className="ai-system-architecture" aria-label="Arquitetura do AI System">
      <div className="ai-system-architecture-stage">
        <svg className="ai-system-architecture-lines" viewBox="0 0 600 470" preserveAspectRatio="none" aria-hidden="true">
          {graphEdges.map((edge, index) => {
            const source = graphCards.find((card) => card.id === edge.source)?.visualKey || edge.source;
            const target = graphCards.find((card) => card.id === edge.target)?.visualKey || edge.target;
            const path = (source === 'dispatcher' || source === 'ai_dispatcher') && (target === 'greeting' || target === 'ai_greeting')
              ? 'M300 96 C300 136 123 126 123 164'
              : (source === 'dispatcher' || source === 'ai_dispatcher') && (target === 'calendar' || target === 'ai_calendar_agent')
                ? 'M300 96 C300 136 477 126 477 164'
                : target === 'google_calendar'
                  ? 'M477 232 C477 252 477 262 477 282'
                  : source === 'google_calendar'
                    ? 'M477 350 C477 388 300 372 300 382'
                    : 'M300 96 C300 170 300 275 300 382';
            return <path key={`${edge.source}-${edge.target}-${index}`} className="ai-system-architecture-line" d={path} />;
          })}
        </svg>
        {graphCards.map((card) => <article key={card.id} className={`ai-system-architecture-card tone-${card.tone} slot-${card.visualKey === 'dispatcher' || card.visualKey === 'ai_dispatcher' ? 'dispatcher' : card.visualKey === 'greeting' || card.visualKey === 'ai_greeting' ? 'greeting' : card.visualKey === 'calendar' || card.visualKey === 'ai_calendar_agent' ? 'calendar' : card.visualKey === 'google_calendar' ? 'integration' : card.visualKey === 'fallback' || card.visualKey === 'ai_safe_fallback' ? 'fallback' : 'unknown'}`}><strong>{card.icon} {card.title}</strong><small>{card.description}</small></article>)}
      </div>
      <div className="ai-system-architecture-footer"><span>{specialistCount} especialistas</span><span>{integrationCount} integração</span><span>3 ações disponíveis</span><strong>Operacional</strong></div>
    </section>
  );
}

function AiSystemNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiSystemNodeData;
  const internalNodes = Array.isArray(nodeData.internal_nodes) ? nodeData.internal_nodes : [];
  const integrations = Array.isArray(nodeData.integrations) ? nodeData.integrations : [];
  const statusItems = ['Conversando', 'Agenda pronta', 'Integração ativa'];
  const graphCards = toInternalCards(internalNodes, integrations);
  const summaryCards = graphCards.filter((card) => card.type === 'agent').slice(0, 4);
  const systemType = nodeData.system_type || 'custom';
  const badge = SYSTEM_BADGES[systemType] || nodeData.name || 'Sistema IA';
  const specialistCount = graphCards.filter((card) => card.type === 'agent').length || 4;
  const integrationCount = graphCards.filter((card) => card.type === 'integration').length || integrations.length || 1;

  return (
    <div className={`ai-system-node${selected ? ' is-selected' : ''}${nodeData.running ? ' is-running' : ''}${nodeData.hasValidationError ? ' has-error' : ''}`}>
      <Handle type="target" position={Position.Left} id="default" />
      <div className="ai-system-node-header">
        <div>
          <span className="ai-system-node-kicker">🤖 AI System</span>
          <h3>{badge}</h3>
          <p>Assistente especializado em Google Calendar</p>
        </div>
        <span className="ai-system-node-badge">🟢 Ativo</span>
      </div>
      <div className="ai-system-node-summary">
        {summaryCards.map((item) => (
          <span key={item.id} className={`ai-system-node-mini-card tone-${item.tone}`}>
            <strong>{item.icon}</strong>
            <small>{item.title}</small>
          </span>
        ))}
      </div>
      <details className="ai-system-node-integrations">
        <summary><span>Integrações</span><strong>📅 Google Calendar</strong></summary>
        <ul><li>✓ Criar eventos</li><li>✓ Consultar agenda</li><li>✓ Alterar eventos</li><li>✓ Cancelar eventos</li></ul>
      </details>
      <div className="ai-system-node-statuses" aria-label="Status"><strong>Status</strong>{statusItems.map((status) => <small key={status}>🟢 {status}</small>)}</div>
      <div className="ai-system-node-footer"><strong>Equipe IA</strong><span>{specialistCount} Especialistas</span><span>{integrationCount} Integração</span><span>Google Calendar</span></div>
      <button type="button" className="ai-system-node-toggle" onClick={(event) => { event.stopPropagation(); nodeData.onOpenSystem?.(id); }}>
        Abrir sistema
      </button>
      <Handle type="source" position={Position.Right} id="default" />
    </div>
  );
}

export default memo(AiSystemNode);
