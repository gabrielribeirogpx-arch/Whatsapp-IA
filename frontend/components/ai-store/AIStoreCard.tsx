import type { AIStoreCardData } from './types';

type AIStoreCardProps = {
  card: AIStoreCardData;
  onInstall: (id: string) => void;
  onDetails: (card: AIStoreCardData) => void;
};

export default function AIStoreCard({ card, onInstall, onDetails }: AIStoreCardProps) {
  return (
    <article className="ai-store-card">
      <div className="ai-store-card-topline">
        <div className="ai-store-icon" aria-hidden="true">{card.icon}</div>
        <div className="ai-store-badges">
          <span>Oficial</span>
          {card.productionReady && <span>Pronto para produção</span>}
        </div>
      </div>
      <div className="ai-store-card-heading">
        <p>{card.category === 'Vendas' ? 'Comercial' : card.category}</p>
        <h3>{card.title}</h3>
        <span>{card.subtitle}</span>
      </div>
      <div className="ai-store-meta" aria-label="Tempo e dificuldade">
        <span>⏱ {card.setupTime}</span>
        <span>✨ {card.difficulty}</span>
      </div>
      <div className="ai-store-integrations" aria-label="Integrações">
        {card.integrations.map((integration) => <span key={integration}>{integration}</span>)}
      </div>
      <ul className="ai-store-capabilities">
        {card.capabilities.slice(0, 4).map((capability) => <li key={capability}>{capability}</li>)}
      </ul>
      <div className="ai-store-card-actions">
        <button type="button" className="ai-store-details-button" onClick={() => onDetails(card)}>
          Ver detalhes
        </button>
        <button type="button" className="ai-store-install" onClick={() => onInstall(card.id)}>
          Instalar
        </button>
      </div>
    </article>
  );
}
