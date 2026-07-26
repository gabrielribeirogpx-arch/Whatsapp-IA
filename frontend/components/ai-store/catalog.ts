import type { AIStoreCardData, AutomationLevel, MarketplaceType, NodeEducation } from './types';

const education = (node: string, ai = false): NodeEducation => ({
  summary: `${node} participa desta etapa do fluxo.`, purpose: `Executar a responsabilidade de ${node} usando o runtime padrão do Flow Builder.`,
  inputs: ['Contexto da conversa'], outputs: ['Contexto atualizado'], why_here: 'Mantém cada responsabilidade explícita e editável.',
  common_mistakes: ['Não mapear a saída esperada'], customization_tips: ['Revise mensagens e variáveis antes de publicar'],
  alternative_nodes: ai ? ['Condition', 'Buttons'] : ['AI Agent'], ai_usage: ai ? 'Este node utiliza IA.' : 'Este node não utiliza IA.', difficulty: ai ? 'intermediate' : 'beginner',
});

const baseManifest = (nodes: readonly string[]) => ({ flows: [{ nodes }], ai_agents: [], knowledge_bases: [], pipelines: [], tags: [], custom_fields: [], integrations: [], settings: [], dependencies: [], post_install_steps: ['Revisar e publicar o fluxo'] });
const make = (title: string, type: MarketplaceType, level: AutomationLevel, segment: string, nodes: string[], integrations: string[] = [], id?: string): AIStoreCardData => {
  const slug = id || title.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '');
  const aiCount = nodes.filter((node) => /AI|RAG/.test(node)).length;
  return { id: slug, icon: type === 'Kit de Negócio' ? '🧰' : type === 'AI System' ? '✦' : level === 'Sem IA' ? '⚙' : '◈', title,
    subtitle: `${title}: automação reutilizável, transparente e totalmente editável.`, category: type, marketplaceType: type, automationLevel: level, segment,
    setupTime: `${Math.max(5, nodes.length * 3)} min`, setupMinutes: Math.max(5, nodes.length * 3), difficulty: nodes.length > 6 ? 'Avançado' : aiCount ? 'Intermediário' : 'Iniciante',
    integrations, capabilities: ['Fluxo editável', 'Preview antes de instalar', 'Documentação educacional'], nodes,
    nodeEducation: Object.fromEntries(nodes.map((node) => [node, education(node, /AI|RAG/.test(node))])), recommended: ['Menu inicial', 'Agenda Inteligente', 'Clínica Odontológica'].includes(title),
    productionReady: false, official: true, free: true, compatible: true, details: `Composição declarativa que reutiliza exclusivamente nodes existentes: ${nodes.join(', ')}.`, version: '1.0.0', installManifest: baseManifest(nodes) };
};

const noAi = ['Menu inicial','Atendimento por setor','Qualificação de lead','Agendamento simples','Follow-up','Pesquisa NPS','Cobrança','Transferência humana','FAQ estruturado','Coleta de dados'];
const hybrid = ['Atendimento com fallback para IA','Qualificação inteligente','Agendamento híbrido','FAQ com RAG','CRM assistido por IA','Comercial com handoff','Recuperação de lead com IA'];
const systems: Array<[string,string?]> = [['Agenda Inteligente','ai_calendar_agent_system'],['Atendimento Inteligente','ai_support_agent_system'],['Comercial Inteligente','ai_sales_agent_system'],['Suporte Inteligente'],['Pós-venda Inteligente']];
const kits = ['Clínica Odontológica','Imobiliária','Restaurante','Advocacia','Pet Shop','Oficina Mecânica'];

export const MARKETPLACE_CATALOG: readonly AIStoreCardData[] = [
  ...noAi.map((name) => make(name, 'Template de Fluxo', 'Sem IA', 'Geral', ['Start','Message','Condition','Variables','End'])),
  ...hybrid.map((name) => make(name, 'Fluxo Híbrido', 'Híbrido', 'Geral', ['Start','Message','Condition','AI Agent','Transfer to Human','End'], name.includes('RAG') ? ['Base de Conhecimento'] : [])),
  ...systems.map(([name,id]) => make(name, 'AI System', 'IA Completa', 'Geral', ['Start','AI Agent','RAG','CRM','Transfer to Human','End'], ['WhatsApp'], id)),
  ...kits.map((name) => make(name, 'Kit de Negócio', 'Sistema Completo', name, ['Start','Message','Condition','AI Agent','CRM','Tags','Transfer to Human','End'])),
];

export const automationShare = (card: AIStoreCardData) => {
  const ai = card.nodes.filter((node) => /AI|RAG/.test(node)).length;
  const aiPercent = Math.round((ai / Math.max(1, card.nodes.length)) * 100);
  return { ai: aiPercent, traditional: 100 - aiPercent };
};
