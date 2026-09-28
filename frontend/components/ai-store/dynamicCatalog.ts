import type { MarketplaceCatalogItem } from '@/lib/api';
import type { AIStoreCardData, AutomationLevel, MarketplaceType } from './types';

const modality = (value: string): AutomationLevel => {
  const normalized = value.toLowerCase().replace('_', ' ');
  if (normalized === 'hybrid' || normalized === 'híbrida' || normalized === 'híbrido') return 'Híbrido';
  if (normalized === 'full ai' || normalized === 'ia completa') return 'IA Completa';
  if (normalized === 'sistema completo') return 'Sistema Completo';
  return 'Sem IA';
};

const marketplaceType = (item: MarketplaceCatalogItem, level: AutomationLevel): MarketplaceType => {
  if (item.template_type === 'business_kit') return 'Kit de Negócio';
  if (level === 'Híbrido') return 'Fluxo Híbrido';
  if (level === 'IA Completa' || level === 'Sistema Completo') return 'AI System';
  return 'Template de Fluxo';
};

/** Adapts the safe public catalogue projection; no graph snapshot is required. */
export function marketplaceCatalogItemToCard(item: MarketplaceCatalogItem): AIStoreCardData {
  const level = modality(item.modality);
  const type = marketplaceType(item, level);
  const capabilities = item.capabilities.length ? item.capabilities : ['Fluxo editável', 'Instalação oficial'];
  return {
    id: item.source === 'official' ? `official:${item.version_id}` : item.key,
    icon: type === 'Kit de Negócio' ? '🧰' : type === 'AI System' ? '✦' : level === 'Sem IA' ? '⚙' : '◈',
    title: item.name, subtitle: item.description || `${item.name}: template reutilizável e editável.`,
    category: item.category, marketplaceType: type, automationLevel: level,
    segment: item.segment || 'Geral', setupTime: item.commercial.estimated_time || '5 min',
    setupMinutes: Number.parseInt(item.commercial.estimated_time || '5', 10) || 5,
    difficulty: item.commercial.level || (level === 'Sem IA' ? 'Iniciante' : 'Intermediário'),
    integrations: [], capabilities, nodes: [], nodeEducation: {}, recommended: false,
    productionReady: true, official: true, free: true, compatible: true,
    availability: item.commercial.availability, details: item.description || item.name,
    version: item.version, installManifest: {}, catalogSource: item.source,
    templateId: item.template_id, templateVersionId: item.version_id, slug: item.slug,
  };
}

/** Dynamic official products win only on proven stable identity (key or slug). */
export function mergeMarketplaceCatalog(staticCards: readonly AIStoreCardData[], items: readonly MarketplaceCatalogItem[]): AIStoreCardData[] {
  const dynamic = items.filter((item) => item.source === 'official' && item.status === 'published').map(marketplaceCatalogItemToCard);
  const officialIdentities = new Set(items.filter((item) => item.source === 'official').flatMap((item) => [item.key, item.slug]));
  const legacy = staticCards.filter((card) => !officialIdentities.has(card.id) && !(card.slug && officialIdentities.has(card.slug)));
  return [...legacy, ...dynamic];
}
