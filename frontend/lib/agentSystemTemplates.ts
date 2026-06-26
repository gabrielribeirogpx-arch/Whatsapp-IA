import type { Edge, Node } from "reactflow";

export const ENABLE_AGENT_SYSTEM_TEMPLATES =
  process.env.NEXT_PUBLIC_ENABLE_AGENT_SYSTEM_TEMPLATES !== "false";

export type AgentSystemTemplate = {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  default_prompts: Record<string, string>;
  required_tools: string[];
  required_integrations: string[];
  nodes: Array<{
    key: string;
    type: string;
    label: string;
    position: { x: number; y: number };
    data: Record<string, unknown>;
  }>;
  edges: Array<{
    source: string;
    target: string;
    sourceHandle?: string;
    label?: string;
  }>;
};

export const AGENT_SYSTEM_PROMPTS = {
  dispatcher:
    "Classifique a intenção da mensagem do usuário. Responda apenas com uma intent válida. Não execute ações.",
  greeting:
    "Você responde saudações de forma curta, humana e natural no WhatsApp.",
  calendar:
    "Você é um agente especializado em agenda. Use Google Calendar apenas quando necessário. Nunca confirme evento sem retorno real da ferramenta. Use o DateResolver determinístico.",
  safeFallback:
    "Não consegui entender totalmente. Você quer agendar algo, tirar uma dúvida ou falar com um atendente?",
} as const;

export const AGENT_SYSTEM_INTENTS = [
  "greeting",
  "calendar_create",
  "calendar_list",
  "calendar_delete",
  "support_question",
  "sales_lead",
  "rag_question",
  "human_handoff",
  "unknown",
] as const;

export const AGENT_SYSTEM_TEMPLATES: AgentSystemTemplate[] = [
  {
    id: "ai_calendar_agent_system",
    name: "Agente de Agenda",
    description:
      "Agenda reuniões, consulta disponibilidade e cria eventos no Google Calendar.",
    category: "Agenda",
    version: "1.0.0",
    default_prompts: AGENT_SYSTEM_PROMPTS,
    required_tools: [
      "google_calendar_create_event",
      "google_calendar_list_events",
      "google_calendar_delete_event",
    ],
    required_integrations: ["google_calendar"],
    nodes: [
      {
        key: "dispatcher",
        type: "ai_dispatcher",
        label: "Start / IA Dispatcher",
        position: { x: 280, y: 240 },
        data: {
          instruction: AGENT_SYSTEM_PROMPTS.dispatcher,
          input_template: "{{last_message}}",
          intents: AGENT_SYSTEM_INTENTS,
          allow_mcp_tools: false,
          allowed_tools: ["responder"],
          after_agent_behavior: "continue_to_next",
          isStart: true,
        },
      },
      {
        key: "greeting",
        type: "ai_greeting",
        label: "IA Greeting",
        position: { x: 760, y: 80 },
        data: {
          instruction: AGENT_SYSTEM_PROMPTS.greeting,
          input_template: "{{last_message}}",
          allow_mcp_tools: false,
          allowed_tools: ["responder"],
          fallback_message: "Olá! 👋 Como posso ajudar?",
          after_agent_behavior: "end_flow",
        },
      },
      {
        key: "calendar",
        type: "ai_calendar_agent",
        label: "IA Calendar Agent",
        position: { x: 760, y: 260 },
        data: {
          instruction: AGENT_SYSTEM_PROMPTS.calendar,
          input_template: "{{last_message}}",
          allowed_tools: ["responder", "chamar_mcp"],
          allow_mcp_tools: true,
          mcp_tool_ids: [
            "google_calendar_create_event",
            "google_calendar_list_events",
            "google_calendar_delete_event",
          ],
          max_mcp_calls: 3,
          use_date_resolver: true,
          after_agent_behavior: "end_flow",
        },
      },
      {
        key: "fallback",
        type: "ai_safe_fallback",
        label: "IA Fallback Seguro",
        position: { x: 760, y: 460 },
        data: {
          instruction: AGENT_SYSTEM_PROMPTS.safeFallback,
          input_template: "{{last_message}}",
          allow_mcp_tools: false,
          allowed_tools: ["responder"],
          fallback_message: AGENT_SYSTEM_PROMPTS.safeFallback,
          after_agent_behavior: "end_flow",
        },
      },
    ],
    edges: [
      {
        source: "dispatcher",
        target: "greeting",
        sourceHandle: "greeting",
        label: "greeting",
      },
      {
        source: "dispatcher",
        target: "calendar",
        sourceHandle: "calendar_create",
        label: "calendar_create",
      },
      {
        source: "dispatcher",
        target: "calendar",
        sourceHandle: "calendar_list",
        label: "calendar_list",
      },
      {
        source: "dispatcher",
        target: "calendar",
        sourceHandle: "calendar_delete",
        label: "calendar_delete",
      },
      {
        source: "dispatcher",
        target: "fallback",
        sourceHandle: "unknown",
        label: "unknown",
      },
    ],
  },
  {
    id: "ai_support_agent_system",
    name: "Agente de Atendimento",
    description: "Responde saudações, dúvidas simples e encaminha para humano.",
    category: "Atendimento",
    version: "0.1.0",
    default_prompts: AGENT_SYSTEM_PROMPTS,
    required_tools: [],
    required_integrations: [],
    nodes: [],
    edges: [],
  },
  {
    id: "ai_sales_agent_system",
    name: "Agente de Vendas",
    description: "Qualifica leads e atualiza CRM.",
    category: "Vendas",
    version: "0.1.0",
    default_prompts: AGENT_SYSTEM_PROMPTS,
    required_tools: ["crm_update_lead"],
    required_integrations: ["crm"],
    nodes: [],
    edges: [],
  },
  {
    id: "ai_rag_agent_system",
    name: "Agente RAG",
    description: "Responde com base em documentos e base de conhecimento.",
    category: "Conhecimento",
    version: "0.1.0",
    default_prompts: AGENT_SYSTEM_PROMPTS,
    required_tools: ["rag_search"],
    required_integrations: ["knowledge_base"],
    nodes: [],
    edges: [],
  },
  {
    id: "ai_mcp_advanced_system",
    name: "Agente MCP Avançado",
    description: "Executa ferramentas externas conectadas.",
    category: "MCP",
    version: "0.1.0",
    default_prompts: AGENT_SYSTEM_PROMPTS,
    required_tools: ["mcp_tools"],
    required_integrations: ["mcp"],
    nodes: [],
    edges: [],
  },
];

export function instantiateAgentSystemTemplate(
  template: AgentSystemTemplate,
  makeId: () => string,
  origin = { x: 0, y: 0 },
): { nodes: Node[]; edges: Edge[] } {
  const ids = new Map(template.nodes.map((node) => [node.key, makeId()]));
  const nodes = template.nodes.map((node) => ({
    id: ids.get(node.key) as string,
    type: node.type,
    position: { x: origin.x + node.position.x, y: origin.y + node.position.y },
    data: {
      label: node.label,
      agent_system_template_id: template.id,
      agent_system_template_version: template.version,
      ...node.data,
    },
  }));
  const edges = template.edges.map((edge) => ({
    id: makeId(),
    source: ids.get(edge.source) as string,
    target: ids.get(edge.target) as string,
    sourceHandle: edge.sourceHandle || "default",
    type: "default",
    label: edge.label || "",
    data: {
      sourceHandle: edge.sourceHandle || "default",
      agent_system_template_id: template.id,
    },
  }));
  return { nodes, edges };
}
