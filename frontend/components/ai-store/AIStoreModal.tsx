import { useEffect, useMemo, useState } from 'react';
import AIStoreCard from './AIStoreCard';
import AIStoreCategoryBar from './AIStoreCategoryBar';
import AIStoreSearch from './AIStoreSearch';
import AISystemDetailsModal from './AISystemDetailsModal';
import type { AIStoreCardData, AIStoreCategoryValue, AIStoreTemplateMeta } from './types';

type AIStoreModalProps = {
  cards: readonly AIStoreCardData[];
  templates: readonly AIStoreTemplateMeta[];
  onClose: () => void;
  onInstall: (id: string) => void;
};

export default function AIStoreModal({ cards, templates, onClose, onInstall }: AIStoreModalProps) {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState<AIStoreCategoryValue>('Recomendados');
  const [detailsCard, setDetailsCard] = useState<AIStoreCardData | null>(null);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onClose]);

  const filteredCards = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();
    return cards.filter((card) => {
      const matchesCategory = category === 'Recomendados' ? card.recommended : card.category === category;
      const haystack = [card.title, card.subtitle, card.category, ...card.integrations, ...card.capabilities].join(' ').toLowerCase();
      return matchesCategory && (!normalizedSearch || haystack.includes(normalizedSearch));
    });
  }, [cards, category, search]);

  const selectedTemplate = detailsCard ? templates.find((template) => template.id === detailsCard.id) : undefined;

  return (
    <div className="flow-modal-backdrop ai-store-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="flow-modal-card ai-store-modal" role="dialog" aria-modal="true" aria-label="AI Store" onMouseDown={(event) => event.stopPropagation()}>
        <header className="flow-modal-header ai-store-header">
          <div>
            <span className="ai-store-eyebrow">Marketplace de sistemas inteligentes</span>
            <h2>AI Store</h2>
            <p>Instale sistemas inteligentes prontos para sua empresa.</p>
          </div>
          <button type="button" className="ai-store-close-button" onClick={onClose} aria-label="Fechar AI Store">×</button>
        </header>

        <div className="ai-store-modal-body">
          <div className="ai-store-toolbar">
            <AIStoreSearch value={search} onChange={setSearch} />
            <AIStoreCategoryBar selected={category} onSelect={setCategory} />
          </div>

          <div className="ai-store-grid">
            {filteredCards.map((card) => (
              <AIStoreCard key={card.id} card={card} onInstall={onInstall} onDetails={setDetailsCard} />
            ))}
          </div>
          {filteredCards.length === 0 && (
            <div className="ai-store-empty">Nenhum sistema encontrado para a busca atual.</div>
          )}
        </div>
      </section>

      {detailsCard && (
        <AISystemDetailsModal
          card={detailsCard}
          template={selectedTemplate}
          onBack={() => setDetailsCard(null)}
          onClose={onClose}
          onInstall={onInstall}
        />
      )}
    </div>
  );
}
