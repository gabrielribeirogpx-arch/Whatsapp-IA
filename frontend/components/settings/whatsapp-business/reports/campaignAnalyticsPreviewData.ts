import type {
  CampaignAnalyticsPage,
  CampaignAnalyticsSummary,
  FailureAnalyticsRow,
  HeatmapAnalytics,
  TemplateAnalyticsRow,
  TimelineAnalytics,
} from "@/lib/api";
import type {
  WhatsAppCampaign,
  WhatsAppProvider,
  WhatsAppTemplate,
} from "@/lib/types";

export type CampaignReportPreviewScenario =
  | "low"
  | "medium"
  | "high"
  | "failures";

export const PREVIEW_SCENARIOS: Array<{
  value: CampaignReportPreviewScenario;
  label: string;
}> = [
  { value: "low", label: "Volume baixo" },
  { value: "medium", label: "Volume médio" },
  { value: "high", label: "Volume alto" },
  { value: "failures", label: "Muitas falhas" },
];

type ScenarioSeed = {
  recipients: number;
  sent: number;
  delivered: number;
  read: number;
  failed: number;
  campaignCount: number;
  timelineDays: number;
  heatmapScale: number;
};

const SCENARIOS: Record<CampaignReportPreviewScenario, ScenarioSeed> = {
  low: {
    recipients: 1380,
    sent: 1250,
    delivered: 1188,
    read: 742,
    failed: 76,
    campaignCount: 6,
    timelineDays: 30,
    heatmapScale: 7,
  },
  medium: {
    recipients: 132400,
    sent: 128960,
    delivered: 122780,
    read: 84630,
    failed: 3440,
    campaignCount: 12,
    timelineDays: 30,
    heatmapScale: 140,
  },
  high: {
    recipients: 132500,
    sent: 125430,
    delivered: 119820,
    read: 86450,
    failed: 2180,
    campaignCount: 18,
    timelineDays: 45,
    heatmapScale: 430,
  },
  failures: {
    recipients: 38500,
    sent: 36420,
    delivered: 28610,
    read: 13980,
    failed: 6420,
    campaignCount: 10,
    timelineDays: 30,
    heatmapScale: 90,
  },
};

const campaignNames = [
  "Black Friday VIP",
  "Recuperação de carrinho",
  "Lançamento Coleção Verão",
  "Renovação de assinatura",
  "NPS pós-atendimento",
  "Boas-vindas novos leads",
  "Reativação 90 dias",
  "Oferta relâmpago regional",
  "Webinar consultivo",
  "Cross-sell clientes premium",
  "Confirmação de agendamento",
  "Sazonal Dia dos Pais",
  "Campanha com nome longo para validar truncamento visual em tabelas e drawers",
];

const templates = [
  {
    id: "tpl-promo-vip",
    name: "promo_vip_desconto",
    category: "MARKETING",
    language: "pt_BR",
  },
  {
    id: "tpl-cart",
    name: "carrinho_recuperacao",
    category: "MARKETING",
    language: "pt_BR",
  },
  {
    id: "tpl-launch",
    name: "lancamento_produto",
    category: "MARKETING",
    language: "pt_BR",
  },
  {
    id: "tpl-renewal",
    name: "renovacao_assinatura",
    category: "UTILITY",
    language: "pt_BR",
  },
  {
    id: "tpl-nps",
    name: "pesquisa_nps",
    category: "UTILITY",
    language: "pt_BR",
  },
  {
    id: "tpl-welcome",
    name: "boas_vindas_lead",
    category: "MARKETING",
    language: "pt_BR",
  },
  {
    id: "tpl-reactivation",
    name: "reativacao_cliente",
    category: "MARKETING",
    language: "es",
  },
  {
    id: "tpl-appointment",
    name: "confirmacao_agendamento",
    category: "UTILITY",
    language: "pt_BR",
  },
];

const statuses = [
  "completed",
  "running",
  "scheduled",
  "paused",
  "failed",
  "cancelled",
];
const failureCategories = [
  [
    "Telefone inválido",
    "Revise DDI, DDD e normalização dos números antes do próximo disparo.",
    ["WZ-400", "META-131026"],
  ],
  [
    "Bloqueio",
    "Monitore opt-out, ajuste frequência e evite reenvio imediato para contatos inativos.",
    ["META-131047"],
  ],
  [
    "Limite Meta",
    "Distribua o envio em janelas menores ou solicite aumento de limite de qualidade.",
    ["META-130429"],
  ],
  [
    "Template",
    "Valide variáveis obrigatórias e política de conteúdo do template aprovado.",
    ["META-132000"],
  ],
  [
    "Erro temporário",
    "Mantenha retentativas com backoff e acompanhe incidentes do provedor.",
    ["WZ-503", "META-2"],
  ],
] as const;

const pct = (a: number, b: number) => (b ? (a / b) * 100 : null);
const isoDaysAgo = (days: number) =>
  new Date(Date.now() - days * 86400000).toISOString();

function distribute(total: number, weights: number[]) {
  const weightTotal = weights.reduce((sum, weight) => sum + weight, 0);
  let used = 0;
  return weights.map((weight, index) => {
    if (index === weights.length - 1) return total - used;
    const value = Math.round((total * weight) / weightTotal);
    used += value;
    return value;
  });
}

function timelineWeights(days: number) {
  return Array.from({ length: days }, (_, index) => {
    const weekday = new Date(
      Date.now() - (days - 1 - index) * 86400000,
    ).getDay();
    const weekdayBoost = weekday === 0 ? 0.62 : weekday === 6 ? 0.7 : 1;
    const wave = 1 + Math.sin(index / 2.7) * 0.18;
    const launchBoost = index > days * 0.7 ? 1.18 : 1;
    return Math.max(0.25, weekdayBoost * wave * launchBoost);
  });
}

function buildTimeline(seed: ScenarioSeed): TimelineAnalytics {
  const weights = timelineWeights(seed.timelineDays);
  const sent = distribute(seed.sent, weights);
  const delivered = distribute(
    seed.delivered,
    weights.map((weight, index) => weight * (0.96 + (index % 5) * 0.018)),
  );
  const read = distribute(
    seed.read,
    weights.map((weight, index) => weight * (0.85 + (index % 7) * 0.035)),
  );
  const failed = distribute(
    seed.failed,
    weights.map((weight, index) => weight * (index % 6 === 0 ? 1.8 : 0.82)),
  );

  return {
    grain: "day",
    items: sent.map((value, index) => ({
      bucket: isoDaysAgo(seed.timelineDays - 1 - index),
      sent: value,
      delivered: delivered[index],
      read: read[index],
      failed: failed[index],
    })),
  };
}

function buildCampaigns(
  scenario: CampaignReportPreviewScenario,
  seed: ScenarioSeed,
): CampaignAnalyticsPage {
  const weights = Array.from(
    { length: seed.campaignCount },
    (_, index) => 1 + ((index * 7) % 9) / 5 + (index < 3 ? 0.9 : 0),
  );
  const recipients = distribute(seed.recipients, weights);
  const sent = distribute(
    seed.sent,
    weights.map((weight, index) => weight * (index % 5 === 0 ? 0.92 : 1)),
  );
  const delivered = distribute(
    seed.delivered,
    weights.map(
      (weight, index) =>
        weight * (scenario === "failures" && index % 4 === 0 ? 0.58 : 1),
    ),
  );
  const read = distribute(
    seed.read,
    weights.map((weight, index) => weight * (index % 3 === 0 ? 1.25 : 0.9)),
  );
  const failed = distribute(
    seed.failed,
    weights.map(
      (weight, index) =>
        weight * (scenario === "failures" && index % 4 === 0 ? 2.4 : 0.8),
    ),
  );

  const items = recipients.map((totalRecipients, index) => {
    const template = templates[index % templates.length];
    const status =
      scenario === "failures" && index % 4 === 0
        ? "failed"
        : statuses[index % statuses.length];
    return {
      id: `preview_${scenario}_${index + 1}`,
      name: campaignNames[index % campaignNames.length],
      status,
      provider_id: index % 2 ? "preview_provider_sp" : "preview_provider_rj",
      template_id: template.id,
      template_name: template.name,
      template_category: template.category,
      template_language: template.language,
      total_recipients: totalRecipients,
      total_sent: sent[index],
      total_delivered: delivered[index],
      total_read: read[index],
      total_failed: failed[index],
      delivery_rate: pct(delivered[index], sent[index]),
      read_rate: pct(read[index], delivered[index]),
      failure_rate: pct(failed[index], totalRecipients),
      scheduled_at: isoDaysAgo(index + 3),
      started_at: isoDaysAgo(index + 2),
      completed_at:
        status === "completed" || status === "failed"
          ? isoDaysAgo(index + 1)
          : null,
      duration_seconds: 420 + index * 95,
      created_at: isoDaysAgo(index + 4),
      updated_at: isoDaysAgo(index),
      metadata_json: { preview: true, scenario },
    };
  });

  return {
    items: items.slice(0, 20) as any,
    page: 1,
    page_size: 20,
    total: items.length,
  };
}

function buildTemplates(
  campaigns: CampaignAnalyticsPage,
): TemplateAnalyticsRow[] {
  return templates
    .map((template) => {
      const rows = campaigns.items.filter(
        (campaign: any) => campaign.template_id === template.id,
      );
      const totals = rows.reduce(
        (acc, row: any) => ({
          total_recipients: acc.total_recipients + row.total_recipients,
          total_sent: acc.total_sent + row.total_sent,
          total_delivered: acc.total_delivered + row.total_delivered,
          total_read: acc.total_read + row.total_read,
          total_failed: acc.total_failed + row.total_failed,
        }),
        {
          total_recipients: 0,
          total_sent: 0,
          total_delivered: 0,
          total_read: 0,
          total_failed: 0,
        },
      );

      return {
        template_id: template.id,
        template_name: template.name,
        category: template.category,
        language: template.language,
        campaigns: rows.length,
        ...totals,
        delivery_rate: pct(totals.total_delivered, totals.total_sent),
        read_rate: pct(totals.total_read, totals.total_delivered),
      };
    })
    .filter((template) => template.campaigns > 0)
    .sort((a, b) => (b.read_rate || 0) - (a.read_rate || 0));
}

function buildFailures(
  seed: ScenarioSeed,
  scenario: CampaignReportPreviewScenario,
): FailureAnalyticsRow[] {
  const weights =
    scenario === "failures"
      ? [3.3, 2.4, 2.1, 1.45, 1.2]
      : [2.6, 1.8, 1.15, 0.8, 0.95];
  const counts = distribute(seed.failed, weights);
  return failureCategories.map(([category, recommendation, codes], index) => ({
    category,
    message: category,
    recommendation,
    count: counts[index],
    percent: pct(counts[index], seed.failed) || 0,
    codes: [...codes],
  }));
}

function buildHeatmap(seed: ScenarioSeed): HeatmapAnalytics {
  return {
    sufficient_data: true,
    items: Array.from({ length: 7 * 24 }, (_, index) => {
      const weekday = Math.floor(index / 24);
      const hour = index % 24;
      const businessHour = hour >= 9 && hour <= 19 ? 1 : 0.2;
      const lunchDip = hour >= 12 && hour <= 13 ? 0.72 : 1;
      const eveningPeak = hour >= 17 && hour <= 20 ? 1.35 : 1;
      const weekend = weekday === 0 ? 0.35 : weekday === 6 ? 0.55 : 1;
      const naturalNoise = 0.85 + ((weekday * 11 + hour * 7) % 10) / 28;
      return {
        weekday,
        hour,
        count: Math.round(
          seed.heatmapScale *
            businessHour *
            lunchDip *
            eveningPeak *
            weekend *
            naturalNoise,
        ),
      };
    }),
  };
}

export function buildCampaignReportPreview(
  scenario: CampaignReportPreviewScenario,
) {
  const seed = SCENARIOS[scenario];
  const campaigns = buildCampaigns(scenario, seed);
  const completed = campaigns.items.filter(
    (campaign) => campaign.status === "completed",
  ).length;
  const summary: CampaignAnalyticsSummary = {
    campaigns_created: seed.campaignCount,
    campaigns_completed: completed,
    total_recipients: seed.recipients,
    total_sent: seed.sent,
    total_delivered: seed.delivered,
    total_read: seed.read,
    total_failed: seed.failed,
    delivery_rate: pct(seed.delivered, seed.sent),
    read_rate: pct(seed.read, seed.delivered),
    failure_rate: pct(seed.failed, seed.recipients),
    timestamp_basis: { preview: "demo-mode" },
  };

  return {
    summary,
    campaigns,
    templates: buildTemplates(campaigns),
    timeline: buildTimeline(seed),
    failures: buildFailures(seed, scenario),
    heatmap: buildHeatmap(seed),
    providers: buildPreviewProviders(),
    allCampaigns: campaigns.items as unknown as WhatsAppCampaign[],
    allTemplates: buildPreviewTemplates(),
  };
}

export function buildPreviewProviders(): WhatsAppProvider[] {
  return [
    {
      id: "preview_provider_sp",
      display_name: "Preview São Paulo",
      phone_number_id: "5511999990001",
      provider: "meta",
      is_active: true,
    } as any,
    {
      id: "preview_provider_rj",
      display_name: "Preview Rio de Janeiro",
      phone_number_id: "5521999990002",
      provider: "meta",
      is_active: true,
    } as any,
  ];
}

export function buildPreviewTemplates(): WhatsAppTemplate[] {
  return templates.map((template) => ({
    id: template.id,
    name: template.name,
    category: template.category,
    language: template.language,
    status: "APPROVED",
  })) as WhatsAppTemplate[];
}
