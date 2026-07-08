'use client';

import { useEffect, useMemo, useState } from 'react';
import type { AgentSystemTemplate } from '@/lib/agentSystemTemplates';
import { AISystemArchitectureGraph, SYSTEM_BADGES } from '@/components/flow/nodes/AiSystemNode';

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

  const internalNodes = Array.isArray(systemData.internal_nodes) ? systemData.internal_nodes : systemTemplate?.nodes ?? [];
  const rawEdges = Array.isArray(systemData.internal_edges) ? systemData.internal_edges : systemTemplate?.edges ?? [];
  const systemType = asString(systemData.system_type) || systemTemplate?.id || 'custom';
  const title = asString(systemData.name) || asString(systemData.label) || systemTemplate?.name || SYSTEM_BADGES[systemType] || 'Sistema IA';
  const description = asString(systemData.description) || systemTemplate?.description || 'Sistema operacional de agentes IA com arquitetura modular e integrações prontas para produção.';
  const capabilities = [
    ...asStringArray(systemData.capabilities),
    'Classificação de intenção',
    'Orquestração de especialistas',
    'Fallback seguro',
    'Execução com ferramentas conectadas',
  ];

  return (
    <div className="ai-store-details-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="ai-system-details-modal ai-system-runtime-modal" role="dialog" aria-modal="true" aria-label={`Detalhes de ${title}`} onMouseDown={(event) => event.stopPropagation()}>
        <header className="ai-system-details-header ai-system-runtime-header">
          <div>
            <span className="ai-store-eyebrow">AI System</span>
            <h3>{title}</h3>
            <p>{description}</p>
            <div className="ai-system-runtime-badges" aria-label="Badges do sistema">
              <span>Oficial</span>
              <span>Produção</span>
              <strong>🟢 Operacional</strong>
            </div>
          </div>
          <button type="button" className="ai-store-close-button" onClick={onClose} aria-label="Fechar sistema">×</button>
        </header>

        <nav className="ai-system-runtime-tabs" aria-label="Seções do AI System">
          {TABS.map((tab) => (
            <button key={tab.key} type="button" className={activeTab === tab.key ? 'is-active' : ''} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </nav>

        {activeTab === 'overview' && (
          <div className="ai-system-runtime-grid">
            <section><h4>Descrição</h4><p>{description}</p></section>
            <section><h4>Especialidades</h4><div className="ai-store-integrations">{['Atendimento', 'Agenda', 'Segurança', 'Automação'].map((item) => <span key={item}>{item}</span>)}</div></section>
            <section><h4>Integrações</h4><div className="ai-store-integrations">{integrations.map((item) => <span key={item}>{formatLabel(item)}</span>)}</div></section>
            <section><h4>Capacidades</h4><ul className="ai-store-capabilities">{capabilities.map((item) => <li key={item}>{item}</li>)}</ul></section>
            <section className="ai-system-details-facts"><span>Tempo médio <strong>{asString(systemData.average_time) || '2 min'}</strong></span><span>Complexidade <strong>{asString(systemData.complexity) || 'Premium'}</strong></span><span>Versão <strong>v{asString(systemData.version) || systemTemplate?.version || '1.0.0'}</strong></span></section>
          </div>
        )}

        {activeTab === 'architecture' && <AISystemArchitectureGraph internalNodes={internalNodes} rawEdges={rawEdges} integrations={integrations} />}

        {activeTab === 'integrations' && (
          <div className="ai-system-runtime-list">{integrations.map((item) => <article key={item}><strong>{formatLabel(item)}</strong><span>Disponível para este sistema</span></article>)}</div>
        )}

        {activeTab === 'configuration' && (
          <div className="ai-system-runtime-placeholder"><strong>Configuração avançada</strong><p>Estrutura reservada para futuras configurações do AI System. Nenhuma configuração existente foi movida nesta sprint.</p></div>
        )}
      </section>
    </div>
  );
}
