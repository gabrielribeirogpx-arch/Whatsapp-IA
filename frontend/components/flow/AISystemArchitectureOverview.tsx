'use client';

const ARCHITECTURE_STEPS = [
  {
    key: 'input',
    icon: '💬',
    eyebrow: 'Entrada',
    title: 'Canal do cliente',
    description: 'Recebe mensagens do WhatsApp e contexto inicial da conversa.',
    tone: 'emerald',
  },
  {
    key: 'orchestrator',
    icon: '🧠',
    eyebrow: 'Núcleo IA',
    title: 'Orquestrador inteligente',
    description: 'Entende a intenção, escolhe especialistas e coordena a resposta.',
    tone: 'blue',
  },
  {
    key: 'specialists',
    icon: '🤖',
    eyebrow: 'Especialistas',
    title: 'Agentes de domínio',
    description: 'Executam tarefas específicas com regras, memória e segurança.',
    tone: 'violet',
  },
  {
    key: 'tools',
    icon: '🔌',
    eyebrow: 'Ferramentas',
    title: 'Integrações externas',
    description: 'Conecta calendário, CRM, bases de conhecimento e automações.',
    tone: 'amber',
  },
  {
    key: 'response',
    icon: '✨',
    eyebrow: 'Entrega',
    title: 'Resposta operacional',
    description: 'Retorna uma resposta clara, auditável e pronta para o usuário.',
    tone: 'rose',
  },
] as const;

const SUPPORT_LAYERS = [
  { icon: '🛡️', title: 'Governança', description: 'Fallbacks, políticas e validações antes de executar ações sensíveis.' },
  { icon: '📚', title: 'Memória e contexto', description: 'Histórico da conversa e dados relevantes enriquecem cada decisão.' },
  { icon: '📈', title: 'Observabilidade', description: 'Logs e sinais operacionais ajudam a acompanhar qualidade e performance.' },
] as const;

export default function AISystemArchitectureOverview() {
  return (
    <section className="ai-system-architecture-overview" aria-label="Visão conceitual da arquitetura do AI System">
      <div className="ai-system-architecture-overview-intro">
        <span className="ai-system-architecture-overview-eyebrow">Arquitetura conceitual</span>
        <h4>Do atendimento à ação, com uma camada IA coordenando cada etapa.</h4>
        <p>Este diagrama mostra como o sistema organiza canais, agentes, ferramentas e resposta final no modal — sem representar o grafo de runtime.</p>
      </div>

      <div className="ai-system-architecture-overview-canvas">
        <svg className="ai-system-architecture-overview-lines" viewBox="0 0 1000 260" preserveAspectRatio="none" aria-hidden="true">
          <defs>
            <linearGradient id="aiSystemArchitectureLine" x1="0" x2="1" y1="0" y2="0">
              <stop offset="0%" stopColor="#10b981" stopOpacity="0.32" />
              <stop offset="45%" stopColor="#2563eb" stopOpacity="0.5" />
              <stop offset="100%" stopColor="#f97316" stopOpacity="0.34" />
            </linearGradient>
            <marker id="aiSystemArchitectureArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
              <path d="M 0 0 L 10 5 L 0 10 z" fill="#2563eb" opacity="0.55" />
            </marker>
          </defs>
          <path d="M95 130 C190 70 300 70 390 130 S590 190 685 130 S835 70 930 130" markerEnd="url(#aiSystemArchitectureArrow)" />
          <path className="is-secondary" d="M500 46 C520 86 520 174 500 214" />
        </svg>

        <div className="ai-system-architecture-overview-flow">
          {ARCHITECTURE_STEPS.map((step) => (
            <article key={step.key} className={`ai-system-architecture-overview-card tone-${step.tone}`}>
              <span className="ai-system-architecture-overview-icon" aria-hidden="true">{step.icon}</span>
              <span className="ai-system-architecture-overview-card-eyebrow">{step.eyebrow}</span>
              <strong>{step.title}</strong>
              <p>{step.description}</p>
            </article>
          ))}
        </div>

        <div className="ai-system-architecture-overview-layers" aria-label="Camadas de suporte">
          {SUPPORT_LAYERS.map((layer) => (
            <article key={layer.title}>
              <span aria-hidden="true">{layer.icon}</span>
              <div>
                <strong>{layer.title}</strong>
                <p>{layer.description}</p>
              </div>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
