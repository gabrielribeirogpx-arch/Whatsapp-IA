export type TaskRealtimePayload = Record<string, unknown> & {
  event?: string;
  type?: string;
  action?: string;
  data?: TaskRealtimePayload;
  payload?: TaskRealtimePayload;
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

export function normalizeRealtimeType(payload: {
  event?: unknown;
  type?: unknown;
  action?: unknown;
}) {
  return String(
    payload.event || payload.type || payload.action || "",
  ).toLowerCase();
}

export function unwrapTaskCreatedPayload(
  payload: TaskRealtimePayload,
): TaskRealtimePayload {
  const nestedPayloads = [payload.data, payload.payload].filter(
    (item): item is TaskRealtimePayload =>
      Boolean(item && typeof item === "object"),
  );
  const nestedTaskCreated = nestedPayloads.find(
    (item) =>
      normalizeRealtimeType(item) === "task_created" ||
      item.action === "TASK_CREATED",
  );

  if (nestedTaskCreated) return nestedTaskCreated;
  if (
    normalizeRealtimeType(payload) === "task_created" ||
    payload.action === "TASK_CREATED"
  ) {
    return payload;
  }

  return payload;
}

export function isTaskCreatedPayload(payload: TaskRealtimePayload) {
  const candidate = unwrapTaskCreatedPayload(payload);
  return (
    normalizeRealtimeType(candidate) === "task_created" ||
    candidate.action === "TASK_CREATED"
  );
}

export function normalizeTaskPriorityLabel(priority: string) {
  const normalized = priority.toLowerCase();
  if (normalized === "high" || normalized === "alta") return "Alta";
  if (normalized === "low" || normalized === "baixa") return "Baixa";
  return "Normal";
}

export function formatTaskDueLabel(payload: TaskRealtimePayload) {
  const normalizedPayload = unwrapTaskCreatedPayload(payload);
  const rawMinutes = normalizedPayload.task?.due_minutes;
  const minutes =
    typeof rawMinutes === "number" ? rawMinutes : Number(rawMinutes);
  if (Number.isFinite(minutes) && minutes > 0) {
    return `${Math.round(minutes)} min`;
  }
  if (normalizedPayload.task?.due_at) {
    const due = new Date(normalizedPayload.task.due_at);
    if (!Number.isNaN(due.getTime())) {
      return due.toLocaleString("pt-BR", {
        day: "2-digit",
        month: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    }
  }
  return "Sem prazo";
}

export function getTaskNotificationDetails(
  payload: TaskRealtimePayload,
): TaskNotificationDetails {
  const normalizedPayload = unwrapTaskCreatedPayload(payload);
  const title =
    String(
      normalizedPayload.task?.title ||
        normalizedPayload.title ||
        normalizedPayload.activity?.title ||
        "Nova tarefa",
    ).trim() || "Nova tarefa";
  const rawMessage =
    typeof normalizedPayload.message === "string"
      ? normalizedPayload.message
      : "";
  const description = String(
    normalizedPayload.task?.description ||
      rawMessage ||
      normalizedPayload.activity?.description ||
      "",
  ).trim();
  const priority = String(
    normalizedPayload.task?.priority || normalizedPayload.priority || "normal",
  ).toLowerCase();
  const assignee = String(normalizedPayload.task?.assigned_to || "").trim();
  const conversationId = String(
    normalizedPayload.conversation_id ||
      normalizedPayload.activity?.entity_id ||
      "",
  );
  const dueLabel = formatTaskDueLabel(normalizedPayload);
  const id = String(
    normalizedPayload.event_id ||
      normalizedPayload.task?.id ||
      normalizedPayload.activity?.id ||
      [conversationId, title, priority, assignee, dueLabel].join("|"),
  );

  return {
    id,
    conversationId,
    title,
    description,
    priority,
    assignee,
    dueLabel,
  };
}

export function formatTaskHistoryDescription(
  details: Pick<
    TaskNotificationDetails,
    "title" | "priority" | "assignee" | "dueLabel"
  >,
) {
  return [
    details.title,
    `Prioridade: ${normalizeTaskPriorityLabel(details.priority)}`,
    details.assignee ? `Responsável: ${details.assignee}` : "Responsável: -",
    `Prazo: ${details.dueLabel}`,
  ]
    .filter(Boolean)
    .join(" · ");
}
