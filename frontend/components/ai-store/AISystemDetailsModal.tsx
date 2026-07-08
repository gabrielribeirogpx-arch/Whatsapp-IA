import { useEffect } from 'react';
import type { AIStoreCardData, AIStoreTemplateMeta } from './types';

type AISystemDetailsModalProps = {
  card: AIStoreCardData;
  template?: AIStoreTemplateMeta;
  onBack: () => void;
  onClose: () => void;
  onInstall: (id: string) => void;
};

export default function AISystemDetailsModal({ card, template, onBack, onClose, onInstall }: AISystemDetailsModalProps) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  return (
    <div className="ai-store-details-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="ai-system-details-modal" role="dialog" aria-modal="true" aria-label={`Detalhes de ${card.title}`} onMouseDown={(event) => event.stopPropagation()}>
        <header className="ai-system-details-header">
          <button type="button" className="ai-store-back-button" onClick={onBack}>← Voltar</button>
          <button type="button" className="ai-store-close-button" onClick={onClose} aria-label="Fechar detalhes">×</button>
        </header>

        <div className="ai-system-details-hero">
          <div className="ai-system-details-icon" aria-hidden="true">{card.icon}</div>
          <div>
            <span className="ai-store-eyebrow">{card.category === 'Vendas' ? 'Comercial' : card.category}</span>
            <h3>{card.title}</h3>
            <p>{card.subtitle}</p>
          </div>
        </div>

        <div className="ai-system-architecture" aria-label="Preview estático da arquitetura">
          <div className="architecture-node architecture-node-main">Dispatcher</div>
          <svg viewBox="0 0 460 130" aria-hidden="true" preserveAspectRatio="none">
            <path d="M230 12 C140 42 115 62 95 91" />
            <path d="M230 12 C315 42 340 62 365 91" />
            <path d="M365 100 L365 126" />
          </svg>
          <div className="architecture-row">
            <div className="architecture-node">Atendimento</div>
            <div className="architecture-node">Agenda</div>
          </div>
          <div className="architecture-node architecture-node-tool">Google Calendar</div>
        </div>

        <div className="ai-system-details-grid">
          <section>
            <h4>Descrição</h4>
            <p>{card.details}</p>
          </section>
          <section>
            <h4>Integrações</h4>
            <div className="ai-store-integrations">{card.integrations.map((item) => <span key={item}>{item}</span>)}</div>
          </section>
          <section>
            <h4>Capacidades</h4>
            <ul className="ai-store-capabilities">{card.capabilities.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
          <section className="ai-system-details-facts">
            <span>Tempo configuração <strong>{card.setupTime}</strong></span>
            <span>Complexidade <strong>{card.difficulty}</strong></span>
            <span>Versão <strong>v{template?.version || '1.0.0'}</strong></span>
          </section>
        </div>

        <footer className="ai-system-details-footer">
          <button type="button" className="ai-store-back-button" onClick={onBack}>Voltar</button>
          <button type="button" className="ai-store-install" onClick={() => onInstall(card.id)}>Instalar</button>
        </footer>
      </section>
    </div>
  );
}
