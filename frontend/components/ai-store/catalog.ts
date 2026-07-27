import type { AIStoreCardData, AutomationLevel, BusinessKit, KitVersion, MarketplaceType, Methodology, NodeEducation } from './types';

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
    productionReady: true, official: true, free: true, compatible: true, availability: 'installable_real', details: `Composição declarativa que reutiliza exclusivamente nodes existentes: ${nodes.join(', ')}.`, version: '1.0.0', installManifest: baseManifest(nodes) };
};

const noAi = ['Menu inicial','Atendimento por setor','Qualificação de lead','Agendamento simples','Follow-up','Pesquisa NPS','Cobrança','Transferência humana','FAQ estruturado','Coleta de dados'];
const hybrid = ['Atendimento com fallback para IA','Qualificação inteligente','Agendamento híbrido','FAQ com RAG','CRM assistido por IA','Comercial com handoff','Recuperação de lead com IA'];
const systems: Array<[string,string?]> = [['Agenda Inteligente','agenda_inteligente'],['Atendimento Inteligente','atendimento_inteligente'],['Comercial Inteligente','comercial_inteligente']];
const kitSegments = ['Clínica Odontológica','Clínica Médica','Veterinária','Imobiliária','Advocacia','Restaurante','Pet Shop','Academia','Escola','Hotel','Contabilidade','Oficina','E-commerce','Estética','Salão'];
const operationalNodes = ['Start','Contextualização','Identificação','Captura de variáveis','Router','Qualificação','Score','Tag','CRM','Pipeline','Confirmação','Espera','Follow-up','Fallback','Transferência humana','Encerramento'];
const initialMenuNodes = ['Início','Boas-vindas','Identificação','Menu principal','Atendimento','Comercial','Financeiro','Agendamento','FAQ','Humano','Encerramento'];
const hybridNodes = [...operationalNodes.slice(0, 5),'Classificação IA',...operationalNodes.slice(5)];
const intelligentNodes = ['Start','Contexto','RAG','Classificação IA','Condição','Captura de variáveis','CRM','Pipeline','Integração','Confirmação','Espera','Follow-up','Fallback','Transferência humana','Encerramento'];

const methodology = (id: string, name: string, purpose: string): Methodology => ({ id, name, purpose, version: '1.0.0', variants: {
  'Sem IA': 'Regras, mensagens e decisões determinísticas.', Híbrida: 'Regras com IA assistiva e transferência humana.', 'IA Completa': 'Agente especializado com RAG, limites e fallback humano.',
} });
export const OPERATIONAL_METHODOLOGIES: readonly Methodology[] = [
  methodology('lead-capture','Captação de Leads','Registrar origem e iniciar atendimento.'), methodology('initial-service','Atendimento Inicial','Recepcionar e identificar a necessidade.'),
  methodology('qualification','Qualificação','Coletar dados necessários sem criar atrito.'), methodology('conversion','Conversão Comercial','Conduzir a próxima ação de valor.'),
  methodology('scheduling','Agendamento','Encontrar e reservar o melhor horário.'), methodology('confirmation','Confirmação e Lembrete','Reduzir esquecimentos e faltas.'),
  methodology('after-sales','Pós-venda e Fidelização','Acompanhar resultado e estimular retorno.'), methodology('recovery','Recuperação de Clientes','Reativar contatos inativos com contexto.'),
  methodology('satisfaction','Pesquisa de Satisfação','Medir experiência e detectar detratores.'), methodology('human-handoff','Transferência Humana','Entregar contexto completo a uma pessoa.'),
];
const kitVersionChanges: Record<KitVersion, readonly string[]> = {
  'Sem IA': ['Fluxos determinísticos','Copies segmentadas','CRM, tags, pipeline e dashboards'],
  Híbrida: ['Tudo da versão Sem IA','IA para classificação e sugestão','Fallback e aprovação humana'],
  'IA Completa': ['Tudo da versão Híbrida','Agente especializado e RAG','Memória, guardrails e handoff contextual'],
};
const dentistry = { pipeline: ['Novo paciente','Consulta marcada','Confirmado','Compareceu','Tratamento','Retorno','Concluído'], crm: ['Especialidade','Última consulta','Convênio','Dentista responsável','Retorno previsto'], tags: ['Primeira consulta','Urgência','Particular','Convênio','Implante','Ortodontia','Retorno','Paciente VIP'], dashboard: ['Consultas marcadas','Comparecimento','Faltas','Conversão','Tempo médio de resposta','Avaliação dos pacientes'] };
const makeBusinessKit = (segment: string): BusinessKit => {
  const dental = segment === 'Clínica Odontológica'; const subject = dental ? 'paciente' : 'cliente';
  const stages = ['Recepção','Qualificação','Agendamento','Confirmação','Atendimento','Pós-venda','Fidelização','Recuperação'];
  return {
    problem: `Organiza o atendimento de ${segment} do primeiro contato ao retorno, reduzindo perdas e tarefas manuais.`, expectedOutcome: `Uma operação de ${segment} previsível, mensurável e pronta para personalização.`, implementationTime: dental ? '45–90 min' : '60–120 min', complexity: 'Intermediária',
    versions: kitVersionChanges, methodologies: [OPERATIONAL_METHODOLOGIES[1],OPERATIONAL_METHODOLOGIES[2],OPERATIONAL_METHODOLOGIES[4],OPERATIONAL_METHODOLOGIES[5],OPERATIONAL_METHODOLOGIES[6],OPERATIONAL_METHODOLOGIES[8],OPERATIONAL_METHODOLOGIES[9]],
    strategy: stages.map((name) => ({ name, objective: `${name}: conduzir o ${subject} à próxima etapa com clareza.`, rationale: `Evita perda de contexto e define uma responsabilidade operacional.`, outcome: `Próxima ação registrada no CRM.`, indicators: name === 'Confirmação' ? ['Taxa de confirmação','Faltas'] : ['Conversão da etapa','Tempo de resposta'] })),
    consultantRationale: ['A confirmação automática reduz faltas.','A pesquisa aumenta fidelização.','O follow-up melhora o retorno.'],
    copies: [
      { category: 'Mensagem inicial', text: dental ? 'Olá, {{nome}}! Sou da equipe da clínica. Você busca avaliação, retorno ou atendimento de urgência?' : `Olá, {{nome}}! Sou da equipe de ${segment}. Como podemos ajudar hoje?` },
      { category: 'Confirmação', text: `Seu atendimento está reservado para {{data}} às {{hora}}. Posso confirmar sua presença?` },
      { category: 'Lembrete', text: `Lembrete: esperamos você amanhã às {{hora}}. Responda 1 para confirmar ou 2 para reagendar.` },
      ...['Reagendamento','Cancelamento','Pós-venda','Recuperação','Pesquisa','Urgência','Transferência humana'].map((category) => ({ category, text: `Exemplo de ${category.toLowerCase()} para ${segment}, pronto para revisão do especialista.` })),
    ],
    crmFields: dental ? dentistry.crm : ['Interesse principal','Último atendimento','Responsável','Origem','Próximo contato'], pipeline: dental ? dentistry.pipeline : ['Novo contato','Qualificado','Agendado','Confirmado','Atendido','Pós-venda','Concluído'], tags: dental ? dentistry.tags : [`${segment}: novo contato`,`${segment}: prioridade`,'Retorno','VIP'],
    knowledgeBase: dental ? ['Perguntas frequentes','Horários','Especialidades','Convênios','Preparação para consulta','Pós-operatório'] : ['Perguntas frequentes','Horários','Serviços','Políticas','Orientações pré-atendimento'],
    dashboards: dental ? dentistry.dashboard : ['Novos contatos','Atendimentos','Conversão','Tempo médio de resposta','Satisfação'], kpis: ['Taxa de conversão','Tempo de resposta','Taxa de retorno','Satisfação'],
    documentation: ['Guia da operação','Mapa de dados e dependências','Manual de personalização','Plano de contingência'], academy: ['Como funciona esta operação','Como personalizar','Como vender mais','Como interpretar os indicadores','Como editar os fluxos'],
    checklist: ['WhatsApp conectado','Agenda configurada','IA configurada (quando aplicável)','Pipeline revisado','Horários ajustados','Mensagens revisadas','Primeiro teste realizado'],
  };
};

export const MARKETPLACE_CATALOG: readonly AIStoreCardData[] = [
  ...noAi.map((name) => make(name, 'Template de Fluxo', 'Sem IA', 'Geral', name === 'Menu inicial' ? initialMenuNodes : operationalNodes)),
  ...hybrid.map((name) => make(name, 'Fluxo Híbrido', 'Híbrido', 'Geral', hybridNodes, name.includes('RAG') ? ['Base de Conhecimento'] : [])),
  ...systems.map(([name,id]) => make(name, 'AI System', 'IA Completa', 'Geral', intelligentNodes, ['WhatsApp'], id)),
  ...kitSegments.map((name) => ({ ...make(name, 'Kit de Negócio', 'Sistema Completo', name, hybridNodes), availability: ['Clínica Odontológica','Imobiliária','Restaurante','Advocacia'].includes(name) ? 'installable_real' as const : 'preview_only' as const, productionReady: ['Clínica Odontológica','Imobiliária','Restaurante','Advocacia'].includes(name), subtitle: `Operação completa e mensurável para ${name}, pronta para adaptar.`, businessKit: makeBusinessKit(name), installManifest: { flows: [{ methodologies: makeBusinessKit(name).methodologies.map((item) => ({ id: item.id, version: item.version })) }], ai_agents: ['Agente especializado opcional'], knowledge_bases: makeBusinessKit(name).knowledgeBase, pipelines: makeBusinessKit(name).pipeline, tags: makeBusinessKit(name).tags, custom_fields: makeBusinessKit(name).crmFields, dashboards: makeBusinessKit(name).dashboards, academy: makeBusinessKit(name).academy, documentation: makeBusinessKit(name).documentation, settings: [], dependencies: [], post_install_steps: makeBusinessKit(name).checklist } })),
];

export const automationShare = (card: AIStoreCardData) => {
  const ai = card.nodes.filter((node) => /AI|RAG/.test(node)).length;
  const aiPercent = Math.round((ai / Math.max(1, card.nodes.length)) * 100);
  return { ai: aiPercent, traditional: 100 - aiPercent };
};
