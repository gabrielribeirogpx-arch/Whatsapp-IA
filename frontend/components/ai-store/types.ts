export type AIStoreCategoryValue = 'Todos' | 'Fluxos' | 'Híbridos' | 'AI Systems' | 'Business Kits' | 'Aprender';
export type AutomationLevel = 'Sem IA' | 'Híbrido' | 'IA Completa' | 'Sistema Completo';
export type MarketplaceType = 'Template de Fluxo' | 'Fluxo Híbrido' | 'AI System' | 'Kit de Negócio';

export type NodeEducation = {
  summary: string;
  purpose: string;
  inputs: readonly string[];
  outputs: readonly string[];
  why_here: string;
  common_mistakes: readonly string[];
  customization_tips: readonly string[];
  alternative_nodes: readonly string[];
  ai_usage: string;
  difficulty: 'beginner' | 'intermediate' | 'advanced';
};

export type AIStoreCardData = {
  id: string;
  icon: string;
  title: string;
  subtitle: string;
  category: string;
  marketplaceType: MarketplaceType;
  automationLevel: AutomationLevel;
  segment: string;
  setupTime: string;
  setupMinutes: number;
  difficulty: string;
  integrations: readonly string[];
  capabilities: readonly string[];
  nodes: readonly string[];
  nodeEducation: Readonly<Record<string, NodeEducation>>;
  recommended: boolean;
  productionReady: boolean;
  official: boolean;
  free: boolean;
  compatible: boolean;
  details: string;
  version: string;
  installManifest: Readonly<Record<string, readonly unknown[]>>;
  businessKit?: BusinessKit;
};

export type AIStoreTemplateMeta = { id: string; name: string; category: string; version: string; description?: string };

export type KitVersion = 'Sem IA' | 'Híbrida' | 'IA Completa';
export type Methodology = {
  id: string; name: string; version: string; purpose: string;
  variants: Readonly<Record<KitVersion, string>>;
};
export type StrategyStage = { name: string; objective: string; rationale: string; outcome: string; indicators: readonly string[] };
export type CopySample = { category: string; text: string };
export type BusinessKit = {
  problem: string; expectedOutcome: string; implementationTime: string; complexity: string;
  versions: Readonly<Record<KitVersion, readonly string[]>>;
  methodologies: readonly Methodology[]; strategy: readonly StrategyStage[];
  consultantRationale: readonly string[]; copies: readonly CopySample[];
  crmFields: readonly string[]; pipeline: readonly string[]; tags: readonly string[];
  knowledgeBase: readonly string[]; dashboards: readonly string[]; kpis: readonly string[];
  documentation: readonly string[]; academy: readonly string[]; checklist: readonly string[];
};
