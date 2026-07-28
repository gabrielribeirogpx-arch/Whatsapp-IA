import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const builder = readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const validator = readFileSync(new URL('../lib/flowValidation.ts', import.meta.url), 'utf8');
const node = readFileSync(new URL('../components/flow/nodes/CompactFlowNode.tsx', import.meta.url), 'utf8');

assert.match(builder, /validateFlowLocally\(currentNodes, currentEdges\)/, 'activation validates before the request');
assert.match(builder, /Não foi possível ativar o fluxo/);
assert.match(builder, /Ir para o node/);
assert.match(builder, /openNodeEditor\(target\)/, 'navigation opens and selects the editor');
assert.match(builder, /setCenter\(/, 'navigation centers the canvas');
assert.match(builder, /validationErrors\.some/, 'all invalid nodes are decorated');
assert.match(node, /Node com configuração inválida/);
assert.match(validator, /CONDITION_EMPTY/);
assert.match(validator, /MESSAGE_REQUIRES_OUTPUT/);
console.log('flow validation UX regression checks passed');
