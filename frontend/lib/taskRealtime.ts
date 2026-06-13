export type TaskRealtimePayload = Record<string, unknown> & {
  event?: string;
  type?: string;
  action?: string;
  event_id?: string;
  conversation_id?: string;
  title?: string;
  message?: unknown;
  priority?: string;
  task?: {
    id?: string;
    title?: string;
    description?: string | null;
    priority?: string;
    assigned_to?: string | null;
    due_at?: string | null;
    due_minutes?: number | string | null;
  };
  activity?: {
    id?: string;
    title?: string;
    description?: string;
    entity_id?: string;
  };
};

export type TaskNotificationDetails = {
  id: string;
  conversationId: string;
  title: string;
  description: string;
  priority: string;
  assignee: string;
  dueLabel: string;
};

export function normalizeRealtimeType(payload: { event?: unknown; type?: unknown; action?: unknown }) {
  return String(payload.event || payload.type || payload.action || "").toLowerCase();
}

export function isTaskCreatedPayload(payload: TaskRealtimePayload) {
  return normalizeRealtimeType(payload) === "task_created" || payload.action === "TASK_CREATED";
}

export function normalizeTaskPriorityLabel(priority: string) {
  const normalized = priority.toLowerCase();
  if (normalized === "high" || normalized === "alta") return "Alta";
  if (normalized === "low" || normalized === "baixa") return "Baixa";
  return "Normal";
}

export function formatTaskDueLabel(payload: TaskRealtimePayload) {
  const rawMinutes = payload.task?.due_minutes;
  const minutes = typeof rawMinutes === "number" ? rawMinutes : Number(rawMinutes);
  if (Number.isFinite(minutes) && minutes > 0) return `${Math.round(minutes)} min`;
  if (payload.task?.due_at) {
    const due = new Date(payload.task.due_at);
    if (!Number.isNaN(due.getTime())) {
      return due.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    }
  }
  return "Sem prazo";
}

export function getTaskNotificationDetails(payload: TaskRealtimePayload): TaskNotificationDetails {
  const title = String(payload.task?.title || payload.title || payload.activity?.title || "Nova tarefa").trim() || "Nova tarefa";
  const rawMessage = typeof payload.message === "string" ? payload.message : "";
  const description = String(payload.task?.description || rawMessage || payload.activity?.description || "").trim();
  const priority = String(payload.task?.priority || payload.priority || "normal").toLowerCase();
  const assignee = String(payload.task?.assigned_to || "").trim();
  const conversationId = String(payload.conversation_id || payload.activity?.entity_id || "");
  const dueLabel = formatTaskDueLabel(payload);
  const id = String(
    payload.event_id ||
      payload.task?.id ||
      payload.activity?.id ||
      [conversationId, title, priority, assignee, dueLabel].join("|"),
  );

  return { id, conversationId, title, description, priority, assignee, dueLabel };
}

export function formatTaskHistoryDescription(details: Pick<TaskNotificationDetails, "title" | "priority" | "assignee" | "dueLabel">) {
  return [
    details.title,
    `Prioridade: ${normalizeTaskPriorityLabel(details.priority)}`,
    details.assignee ? `Responsável: ${details.assignee}` : "Responsável: -",
    `Prazo: ${details.dueLabel}`,
  ]
    .filter(Boolean)
    .join(" · ");
}
