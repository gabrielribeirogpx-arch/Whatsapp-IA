import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = fs.readFileSync(new URL('../lib/flowValidation.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const module = { exports: {} };
const require = (id) => {
  if (id === './dataCollectionHandles') return { normalizeDataCollectionHandle: String };
  if (id === './nodeHandleContract') return {
    normalizeLegacyHandle: (value) => String(value ?? '').trim().toLowerCase(),
    getNodeHandleContract: (node) => ({ sourceHandles: node.type === 'choice_dynamic' ? ['selected', 'empty'] : ['default'], targetHandles: ['default'] }),
  };
  throw new Error(`Unexpected import: ${id}`);
};
vm.runInNewContext(compiled, { module, exports: module.exports, require, console: { info() {} } });
const { validateFlowLocally } = module.exports;

const start = { id: 'start', type: 'start', data: { isStart: true, content: 'Início' } };
const dynamic = (data = {}) => ({ id: 'dynamic', type: 'choice_dynamic', data: { options_mode: 'dynamic', options_variable: 'appointments', label_field: 'label', value_field: 'id', result_variable: 'selected_slot', ...data } });
const end = { id: 'end', type: 'message', data: { content: 'Fim', is_terminal: true } };
const baseEdges = [
  { id: 'start-dynamic', source: 'start', target: 'dynamic', sourceHandle: 'default', targetHandle: 'default' },
  { id: 'selected-end', source: 'dynamic', target: 'end', sourceHandle: 'selected', targetHandle: 'default' },
];
const emptyIssue = (nodes, edges) => validateFlowLocally(nodes, edges).find((issue) => issue.code === 'DYNAMIC_CHOICE_EMPTY_REQUIRED');

assert.ok(emptyIssue([start, dynamic(), end], baseEdges), 'selected alone remains invalid');
assert.equal(emptyIssue([start, dynamic({ empty_message: 'Sem horários disponíveis.' }), end], baseEdges), undefined, 'canonical message permits activation');
assert.equal(emptyIssue([start, dynamic(), end], [...baseEdges, { id: 'empty-end', source: 'dynamic', target: 'end', sourceHandle: 'empty', targetHandle: 'default' }]), undefined, 'empty edge permits activation');
const oldNode = JSON.parse(JSON.stringify(dynamic()));
assert.equal(oldNode.data.empty_message, undefined, 'legacy nodes remain readable without migration defaults');
const rehydrated = JSON.parse(JSON.stringify(dynamic({ empty_message: 'Tente outro período.' })));
assert.equal(rehydrated.data.empty_message, 'Tente outro período.', 'message survives save/reload JSON boundary');

console.log('dynamic choice activation regression: ok');
