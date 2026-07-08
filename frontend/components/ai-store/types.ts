export type AIStoreCategoryValue = 'Recomendados' | 'Produtividade' | 'Atendimento' | 'Vendas' | 'Conhecimento' | 'Automação' | 'Personalizados';

export type AIStoreCardData = {
  id: string;
  icon: string;
  title: string;
  subtitle: string;
  category: Exclude<AIStoreCategoryValue, 'Recomendados'>;
  setupTime: string;
  difficulty: string;
  integrations: readonly string[];
  capabilities: readonly string[];
  recommended: boolean;
  productionReady: boolean;
  details: string;
};

export type AIStoreTemplateMeta = {
  id: string;
  name: string;
  category: string;
  version: string;
  description?: string;
};
