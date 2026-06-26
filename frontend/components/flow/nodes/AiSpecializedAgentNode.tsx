"use client";

import { NodeProps } from "reactflow";
import CompactFlowNode, { NodeStatus } from "./CompactFlowNode";

const DISPATCHER_HANDLES = [
  "greeting",
  "calendar_create",
  "calendar_list",
  "calendar_delete",
  "support_question",
  "sales_lead",
  "rag_question",
  "human_handoff",
  "unknown",
];

const configByType: Record<
  string,
  {
    title: string;
    emoji: string;
    badge: string;
    summary: string;
    accent: string;
    chips: string[];
  }
> = {
  ai_dispatcher: {
    title: "IA Dispatcher",
    emoji: "🧭",
    badge: "ROUTER",
    summary:
      "Classifica a intenção e encaminha para o agente correto sem executar ferramentas.",
    accent: "linear-gradient(135deg, #0f766e, #2563eb)",
    chips: ["Sem MCP", "Classificação", "Roteamento"],
  },
  ai_greeting: {
    title: "IA Greeting",
    emoji: "👋",
    badge: "CHAT",
    summary: "Responde saudações de forma curta, humana e natural.",
    accent: "linear-gradient(135deg, #22c55e, #14b8a6)",
    chips: ["Sem MCP", "Saudações", "WhatsApp"],
  },
  ai_calendar_agent: {
    title: "IA Calendar Agent",
    emoji: "📅",
    badge: "AGENDA",
    summary:
      "Resolve criação, consulta e cancelamento de eventos usando Google Calendar.",
    accent: "linear-gradient(135deg, #2563eb, #7c3aed)",
    chips: ["Calendar", "DateResolver", "MCP seguro"],
  },
  ai_safe_fallback: {
    title: "IA Fallback Seguro",
    emoji: "🛟",
    badge: "SAFE",
    summary: "Responde de forma humana quando a intenção não é reconhecida.",
    accent: "linear-gradient(135deg, #f97316, #dc2626)",
    chips: ["Sem técnico", "Ajuda", "Handoff"],
  },
};

export default function AiSpecializedAgentNode({
  id,
  type,
  data,
  selected,
}: NodeProps) {
  const nodeData = (data || {}) as Record<string, any>;
  const cfg = configByType[String(type)] || configByType.ai_safe_fallback;
  const handles =
    String(type) === "ai_dispatcher"
      ? DISPATCHER_HANDLES.map((intent) => ({
          id: intent,
          label: intent,
          color: intent === "unknown" ? "#f97316" : "#2563eb",
        }))
      : undefined;
  const mcpEnabled = nodeData.allow_mcp_tools === true;

  return (
    <CompactFlowNode
      id={id}
      selected={selected}
      running={nodeData.running}
      title={cfg.title}
      emoji={cfg.emoji}
      badge={cfg.badge}
      badgeTone={{ background: "#eef2ff", color: "#3730a3" }}
      accent={cfg.accent}
      summary={cfg.summary}
      meta={mcpEnabled ? "MCP controlado" : "Sem MCP"}
      chips={cfg.chips}
      sourceHandles={handles}
      footer={
        <NodeStatus
          active
          label={mcpEnabled ? "Ferramentas restritas" : "Seguro"}
        />
      }
      premium
      isStart={nodeData.isStart}
      hasValidationError={nodeData.hasValidationError}
      onToggleStart={nodeData.onToggleStart}
      analytics={nodeData.analytics}
    />
  );
}
