import { automationShare } from './catalog';
import type { AIStoreCardData } from './types';
export default function AIStoreCard({ card, onInstall, onDetails }: { card: AIStoreCardData; onInstall: (id: string, variant?: string) => void; onDetails: (card: AIStoreCardData) => void }) {
  const share = automationShare(card);
  const install = () => {
    console.info(`[MARKETPLACE TRACE] AIStoreCard Install ${card.id}`);
    onInstall(card.id);
  };
  return <article className="ai-store-card">
    <div className="ai-store-card-topline"><div className="ai-store-icon" aria-hidden="true">{card.icon}</div><div className="ai-store-badges"><span>{card.automationLevel}</span><span>{card.official ? 'Oficial' : 'Comunidade'}</span></div></div>
    <div className="ai-store-card-heading"><p>{card.marketplaceType} · {card.segment}</p><h3>{card.title}</h3><span>{card.subtitle}</span></div>
    {card.automationLevel === 'Híbrido' && <div className="ai-store-share"><span style={{ width: `${share.traditional}%` }}>Automação {share.traditional}%</span><span style={{ width: `${share.ai}%` }}>IA {share.ai}%</span></div>}
    <div className="ai-store-meta"><span>⏱ {card.setupTime}</span><span>◇ {card.difficulty}</span><span>{card.nodes.length} nodes</span></div>
    <div className="ai-store-integrations">{(card.integrations.length ? card.integrations : ['Sem integração obrigatória']).slice(0, 2).map((value) => <span key={value}>{value}</span>)}</div>
    <ul className="ai-store-capabilities">{card.capabilities.slice(0, 2).map((value) => <li key={value}>{value}</li>)}</ul>
    <div className="ai-store-card-actions"><button type="button" className="ai-store-details-button" onClick={() => onDetails(card)}>Visualizar e aprender</button>{card.availability === 'installable_real' ? <button type="button" className="ai-store-install" onClick={install}>Instalar</button> : <span title="Template ainda não disponível para instalação">Preview</span>}</div>
  </article>;
}
