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
  formatTaskHistoryDescription,
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
assert.equal(
  formatTaskHistoryDescription(details),
  "Ligar para cliente · Prioridade: Alta · Responsável: Maria · Prazo: 30 min",
);

const mobileAlertPayload = { action: "TASK_CREATED", task: { title: "Sem prioridade" } };
const mobileDetails = getTaskNotificationDetails(mobileAlertPayload);
assert.equal(isTaskCreatedPayload(mobileAlertPayload), true);
assert.equal(mobileDetails.priority, "normal");
assert.equal(formatTaskHistoryDescription(mobileDetails).includes("Prioridade: Normal"), true);
