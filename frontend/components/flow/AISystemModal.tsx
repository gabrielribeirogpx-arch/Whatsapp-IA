'use client';

import { useEffect, useMemo, useState } from 'react';
import type { AgentSystemTemplate } from '@/lib/agentSystemTemplates';
import { SYSTEM_BADGES } from '@/components/flow/nodes/AiSystemNode';
import AISystemArchitectureOverview from '@/components/flow/AISystemArchitectureOverview';

type AISystemModalProps = {
  systemTemplate?: AgentSystemTemplate;
  systemData: Record<string, unknown>;
  onClose: () => void;
};

type TabKey = 'overview' | 'architecture' | 'integrations' | 'configuration';

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'overview', label: 'Visão Geral' },
  { key: 'architecture', label: 'Arquitetura' },
  { key: 'integrations', label: 'Integrações' },
  { key: 'configuration', label: 'Configuração' },
];

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');
const asStringArray = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []);
const formatLabel = (value: string) => value.replace(/_/g, ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());

const friendlyToolName = (value: string): string => {
  const normalized = value.toLowerCase();
  if (normalized.includes('create')) return 'Criar eventos';
  if (normalized.includes('list') || normalized.includes('search')) return 'Listar eventos';
  if (normalized.includes('get') || normalized.includes('consult')) return 'Consultar agenda';
  if (normalized.includes('delete') || normalized.includes('cancel')) return 'Cancelar eventos';
  if (normalized.includes('update')) return 'Alterar eventos';
  return formatLabel(value);
};

export default function AISystemModal({ systemTemplate, systemData, onClose }: AISystemModalProps) {
  const [activeTab, setActiveTab] = useState<TabKey>('overview');

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const integrations = useMemo(() => {
    const items = [
      ...asStringArray(systemData.integrations),
      ...(systemTemplate?.required_integrations ?? []),
      ...asStringArray(systemData.tools),
      ...(systemTemplate?.required_tools ?? []),
    ];
    return Array.from(new Set(items.length ? items : ['google_calendar', 'whatsapp', 'crm', 'mcp', 'rag']));
  }, [systemData, systemTemplate]);

  const systemType = asString(systemData.system_type) || systemTemplate?.id || 'custom';
  const title = asString(systemData.name) || asString(systemData.label) || systemTemplate?.name || SYSTEM_BADGES[systemType] || 'Sistema IA';
  const description = asString(systemData.description) || systemTemplate?.description || 'Sistema operacional de agentes IA com arquitetura modular e integrações prontas para produção.';
  const capabilities = Array.from(new Set([
    ...asStringArray(systemData.capabilities),
    'Classificação de intenção',
    'Orquestração de especialistas',
    'Fallback seguro',
    'Execução com ferramentas conectadas',
  ]));
  const version = asString(systemData.version) || systemTemplate?.version || '1.0.0';
  const rawCalendarTools = integrations.filter((item) => item.toLowerCase().includes('calendar') || item.toLowerCase().includes('event'));
  const calendarTools = Array.from(new Set((rawCalendarTools.length ? rawCalendarTools : ['create_event', 'get_calendar', 'list_events', 'delete_event']).map(friendlyToolName)));

  return (
    <div className="ai-store-details-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="ai-system-details-modal ai-system-runtime-modal" role="dialog" aria-modal="true" aria-label={`Detalhes de ${title}`} onMouseDown={(event) => event.stopPropagation()}>
        <header className="ai-system-details-header ai-system-runtime-header">
          <div className="ai-system-runtime-hero-icon" aria-hidden="true">🤖</div>
          <div className="ai-system-runtime-header-copy">
            <span className="ai-store-eyebrow">AI System</span>
            <h3>{title}</h3>
            <p>{description}</p>
            <div className="ai-system-runtime-badges" aria-label="Badges do sistema">
              <span>Oficial</span>
              <span>Produção</span>
              <strong>🟢 Operacional</strong>
            </div>
            <div className="ai-system-runtime-meta" aria-label="Metadados do sistema">
              <span>v{version}</span><span>Equipe Wazza</span><span>Runtime V2</span><span>4 especialistas</span><span>1 integração</span>
            </div>
          </div>
          <button type="button" className="ai-store-close-button" onClick={onClose} aria-label="Fechar sistema">×</button>
        </header>

        <div className="ai-system-runtime-body">
        <nav className="ai-system-runtime-tabs" aria-label="Seções do AI System">
          {TABS.map((tab) => (
            <button key={tab.key} type="button" className={activeTab === tab.key ? 'is-active' : ''} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </nav>

        {activeTab === 'overview' && (
          <div className="ai-system-runtime-grid">
            <section className="is-wide"><h4>Descrição</h4><p>{description}</p></section>
            <section><h4>Especialidades</h4><div className="ai-store-integrations">{['Atendimento', 'Agenda', 'Segurança', 'Automação'].map((item) => <span key={item}>{item}</span>)}</div></section>
            <section><h4>Capacidades</h4><ul className="ai-store-capabilities">{capabilities.map((item) => <li key={item}>{item}</li>)}</ul></section>
            <section className="ai-system-details-facts is-wide"><h4>Resumo operacional</h4><span>Tempo médio <strong>{asString(systemData.average_time) || '2 min'}</strong></span><span>Complexidade <strong>{asString(systemData.complexity) || 'Fácil/Premium'}</strong></span><span>Versão <strong>v{version}</strong></span></section>
          </div>
        )}

        {activeTab === 'architecture' && <AISystemArchitectureOverview />}

        {activeTab === 'integrations' && (
          <div className="ai-system-runtime-list"><article className="ai-system-integration-card"><strong>📅 Google Calendar</strong><span>Status: Disponível / Conectado</span><small>Ferramentas disponíveis:</small><ul>{calendarTools.map((item) => <li key={item}>{item}</li>)}</ul></article></div>
        )}

        {activeTab === 'configuration' && (
          <div className="ai-system-runtime-grid">
            <section><h4>IA</h4><p>Modelo: Configuração global</p><p>Temperatura: 0.2</p><p>Idioma: pt-BR</p></section>
            <section><h4>Memória</h4><p>Long Memory: Ativa</p></section>
            <section><h4>Observabilidade</h4><p>Logs: Ativo</p><p>Replay: Em breve</p><p>Tracing: Em breve</p></section>
            <section><h4>Integrações</h4><p>Google Calendar: Necessário</p></section>
          </div>
        )}
        </div>
      </section>
    </div>
  );
}
