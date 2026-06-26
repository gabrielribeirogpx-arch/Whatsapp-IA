'use client';

import { memo } from 'react';
import { Handle, NodeProps, Position } from 'reactflow';

type AiSystemNodeData = {
  name?: string;
  label?: string;
  system_type?: string;
  collapsed?: boolean;
  internal_nodes?: unknown[];
  internal_edges?: unknown[];
  tools?: string[];
  integrations?: string[];
  statuses?: string[];
  average_time?: string;
  onToggleSystem?: (nodeId: string) => void;
  running?: boolean;
  isStart?: boolean;
  hasValidationError?: boolean;
};

type InternalCard = {
  id: string;
  visualKey: string;
  type: 'agent' | 'integration';
  icon: string;
  title: string;
  description: string;
  tone: 'blue' | 'green' | 'orange' | 'purple' | 'amber' | 'slate';
};

type InternalEdge = { source: string; target: string };

const SYSTEM_BADGES: Record<string, string> = {
  ai_calendar_agent_system: 'Agenda Inteligente',
  ai_support_agent_system: 'Atendimento Inteligente',
  ai_sales_agent_system: 'Comercial Inteligente',
  ai_rag_agent_system: 'Conhecimento (RAG)',
  ai_mcp_advanced_system: 'MCP Automation',
  ai_custom_system: 'Sistema Personalizado',
  custom: 'Sistema Personalizado',
};

const FRIENDLY_NODES: Record<string, Omit<InternalCard, 'id' | 'visualKey'>> = {
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

function toInternalCards(nodes: unknown[], integrations: string[]): InternalCard[] {
  const cards = nodes.map((node, index) => {
    const key = friendlyKeyForNode(node);
    const friendly = FRIENDLY_NODES[key] || { type: 'agent' as const, icon: '🤖', title: 'Agente', description: 'Especialista interno', tone: 'slate' as const };
    return { id: nodeId(node) || `${key}-${index}`, visualKey: key, ...friendly };
  });
  const hasCalendar = cards.some((card) => card.title === 'Google Calendar') || integrations.includes('google_calendar');
  if (hasCalendar && !cards.some((card) => card.id === 'google_calendar')) cards.push({ id: 'google_calendar', visualKey: 'google_calendar', ...FRIENDLY_NODES.google_calendar });
  return cards.length ? cards : DEFAULT_INTERNAL_CARDS;
}

function toInternalEdges(edges: unknown[], cards: InternalCard[]): InternalEdge[] {
  const cardIds = new Set(cards.map((card) => card.id));
  const parsed = edges.map((edge) => ({ source: textValue(getRecordValue(edge, 'source')), target: textValue(getRecordValue(edge, 'target')) })).filter((edge) => cardIds.has(edge.source) && cardIds.has(edge.target));
  const calendarCard = cards.find((card) => card.visualKey === 'calendar' || card.visualKey === 'ai_calendar_agent');
  if (calendarCard && cardIds.has('google_calendar')) parsed.push({ source: calendarCard.id, target: 'google_calendar' });
  return parsed.length ? parsed : DEFAULT_INTERNAL_EDGES.filter((edge) => cardIds.has(edge.source) && cardIds.has(edge.target));
}

function AiSystemNode({ id, data, selected }: NodeProps) {
  const nodeData = (data || {}) as AiSystemNodeData;
  const internalNodes = Array.isArray(nodeData.internal_nodes) ? nodeData.internal_nodes : [];
  const rawEdges = Array.isArray(nodeData.internal_edges) ? nodeData.internal_edges : [];
  const integrations = Array.isArray(nodeData.integrations) ? nodeData.integrations : [];
  const statusItems = ['Conversando', 'Agenda pronta', 'Integração ativa'];
  const graphCards = toInternalCards(internalNodes, integrations);
  const graphEdges = toInternalEdges(rawEdges, graphCards);
  const summaryCards = graphCards.filter((card) => card.type === 'agent').slice(0, 4);
  const isExpanded = nodeData.collapsed === false;
  const systemType = nodeData.system_type || 'custom';
  const badge = SYSTEM_BADGES[systemType] || nodeData.name || 'Sistema IA';
  const specialistCount = graphCards.filter((card) => card.type === 'agent').length || 4;
  const integrationCount = graphCards.filter((card) => card.type === 'integration').length || integrations.length || 1;

  return (
    <div className={`ai-system-node${isExpanded ? ' is-expanded' : ''}${selected ? ' is-selected' : ''}${nodeData.running ? ' is-running' : ''}${nodeData.hasValidationError ? ' has-error' : ''}`}>
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
      <section className="ai-system-architecture" aria-hidden={!isExpanded}>
        <div className="ai-system-architecture-stage">
          <svg className="ai-system-architecture-lines" viewBox="0 0 520 430" preserveAspectRatio="none" aria-hidden="true">
            {graphEdges.map((edge, index) => {
              const source = graphCards.find((card) => card.id === edge.source)?.visualKey || edge.source;
              const target = graphCards.find((card) => card.id === edge.target)?.visualKey || edge.target;
              const path = (source === 'dispatcher' || source === 'ai_dispatcher') && (target === 'greeting' || target === 'ai_greeting')
                ? 'M260 82 C260 132 116 120 116 170'
                : (source === 'dispatcher' || source === 'ai_dispatcher') && (target === 'calendar' || target === 'ai_calendar_agent')
                  ? 'M260 82 C260 132 404 120 404 170'
                  : target === 'google_calendar'
                    ? 'M404 232 C404 270 404 278 404 312'
                    : source === 'google_calendar'
                      ? 'M404 360 C404 392 260 386 260 410'
                      : 'M260 82 C260 170 260 260 260 342';
              return <path key={`${edge.source}-${edge.target}-${index}`} className="ai-system-architecture-line" d={path} />;
            })}
          </svg>
          {graphCards.map((card) => <article key={card.id} className={`ai-system-architecture-card tone-${card.tone} slot-${card.visualKey === 'dispatcher' || card.visualKey === 'ai_dispatcher' ? 'dispatcher' : card.visualKey === 'greeting' || card.visualKey === 'ai_greeting' ? 'greeting' : card.visualKey === 'calendar' || card.visualKey === 'ai_calendar_agent' ? 'calendar' : card.visualKey === 'google_calendar' ? 'integration' : card.visualKey === 'fallback' || card.visualKey === 'ai_safe_fallback' ? 'fallback' : 'unknown'}`}><strong>{card.icon} {card.title}</strong><small>{card.description}</small></article>)}
        </div>
        <div className="ai-system-architecture-footer"><span>{specialistCount} especialistas</span><span>{integrationCount} integração</span><span>3 ações disponíveis</span><strong>Operacional</strong></div>
      </section>
      {!isExpanded ? <details className="ai-system-node-integrations">
        <summary><span>Integrações</span><strong>📅 Google Calendar</strong></summary>
        <ul><li>✓ Criar eventos</li><li>✓ Consultar agenda</li><li>✓ Alterar eventos</li><li>✓ Cancelar eventos</li></ul>
      </details> : null}
      <div className="ai-system-node-statuses" aria-label="Status"><strong>Status</strong>{statusItems.map((status) => <small key={status}>🟢 {status}</small>)}</div>
      <div className="ai-system-node-footer"><strong>Equipe IA</strong><span>{specialistCount} Especialistas</span><span>{integrationCount} Integração</span><span>Google Calendar</span></div>
      <button type="button" className="ai-system-node-toggle" onClick={(event) => { event.stopPropagation(); nodeData.onToggleSystem?.(id); }}>
        {isExpanded ? '▲ Ocultar arquitetura' : '▼ Ver arquitetura'}
      </button>
      <Handle type="source" position={Position.Right} id="default" />
    </div>
  );
}

export default memo(AiSystemNode);
