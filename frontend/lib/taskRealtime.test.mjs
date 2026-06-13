import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const source = readFileSync(new URL("./taskRealtime.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const context = { exports: {}, module: { exports: {} } };
context.exports = context.module.exports;
vm.runInNewContext(compiled, context, { filename: "taskRealtime.ts" });
const {
  buildTaskNotificationText,
  formatTaskHistoryDescription,
  formatTaskPriorityLabel,
  getTaskNotificationDetails,
  isTaskCreatedPayload,
  normalizeTaskPriorityLabel,
} = context.module.exports;

const payload = {
  event: "task_created",
  conversation_id: "conv-1",
  task: {
    id: "task-1",
    title: "Ligar para cliente",
    description: "Confirmar pagamento",
    priority: "high",
    assigned_to: "Maria",
    due_minutes: 30,
  },
};

assert.equal(isTaskCreatedPayload(payload), true);
const details = getTaskNotificationDetails(payload);
assert.equal(details.id, "task-1");
assert.equal(details.conversationId, "conv-1");
assert.equal(details.title, "Ligar para cliente");
assert.equal(details.description, "Confirmar pagamento");
assert.equal(details.priority, "high");
assert.equal(details.assignee, "Maria");
assert.equal(details.dueLabel, "30 min");
assert.equal(normalizeTaskPriorityLabel(details.priority), "Alta");
assert.equal(formatTaskPriorityLabel(details.priority), "Alta");
assert.equal(
  formatTaskHistoryDescription(details),
  "Ligar para cliente · Prioridade: Alta · Responsável: Maria · Prazo: 30 min",
);
assert.equal(
  JSON.stringify(buildTaskNotificationText(details).toastLines),
  JSON.stringify([
    "Ligar para cliente",
    "Responsável: Maria",
    "Prioridade: Alta",
    "Prazo: 30 min",
  ]),
);
assert.equal(
  buildTaskNotificationText(details).alertTitle,
  "Tarefa criada · Alta",
);

const mobileAlertPayload = { action: "TASK_CREATED", task: { title: "Sem prioridade" } };
const mobileDetails = getTaskNotificationDetails(mobileAlertPayload);
assert.equal(isTaskCreatedPayload(mobileAlertPayload), true);
assert.equal(mobileDetails.priority, "normal");
assert.equal(formatTaskHistoryDescription(mobileDetails).includes("Prioridade: Normal"), true);

const wrappedPayload = {
  event: "dashboard_event",
  data: {
    type: "TASK_CREATED",
    conversation_id: "conv-2",
    event_id: "evt-2",
    task: { title: "Enviar contrato", due_at: "2026-06-13T15:30:00Z" },
  },
};
const wrappedDetails = getTaskNotificationDetails(wrappedPayload);
assert.equal(isTaskCreatedPayload(wrappedPayload), true);
assert.equal(wrappedDetails.id, "evt-2");
assert.equal(wrappedDetails.conversationId, "conv-2");
assert.equal(wrappedDetails.title, "Enviar contrato");
assert.notEqual(wrappedDetails.dueLabel, "Sem prazo");

const flatPayload = {
  type: "task_created",
  task_title: "Enviar boleto",
  task_assignee: "João",
  task_due_minutes: "45",
  priority: "low",
};
const flatDetails = getTaskNotificationDetails(flatPayload);
assert.equal(flatDetails.title, "Enviar boleto");
assert.equal(flatDetails.assignee, "João");
assert.equal(flatDetails.dueLabel, "45 min");
assert.equal(flatDetails.priorityLabel, "Baixa");
assert.equal(
  buildTaskNotificationText(flatDetails).bannerText,
  "Enviar boleto\nResponsável: João\nPrazo: 45 min",
);
