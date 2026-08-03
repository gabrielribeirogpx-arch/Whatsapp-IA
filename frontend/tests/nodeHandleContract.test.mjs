import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../lib/nodeHandleContract.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const module = { exports: {} };
vm.runInNewContext(compiled, { module, exports: module.exports });
const { getNodeHandleContract, migrateEdgeHandles } = module.exports;
const expected = {
  mcp_tool: [['success', 'error', 'timeout'], ['default']],
  choice_dynamic: [['selected'], ['default']],
  data_collection: [['success', 'cancel', 'timeout', 'invalid'], ['default']],
  condition: [['true', 'false'], ['default']], message: [['default'], ['default']], action: [['default'], ['default']],
};
for (const [type, [sources, targets]] of Object.entries(expected)) {
  const contract = getNodeHandleContract({ type, data: {} });
  assert.deepEqual([...contract.sourceHandles], sources);
  assert.deepEqual([...contract.targetHandles], targets);
}
const nodes = [{ id: 'mcp', type: 'mcp_tool' }, { id: 'target', type: 'message' }];
const migrated = migrateEdgeHandles(nodes, ['sucesso', 'erro', 'tempo_esgotado'].map((sourceHandle) => ({ source: 'mcp', target: 'target', sourceHandle })));
assert.deepEqual(migrated.map((edge) => edge.sourceHandle), ['success', 'error', 'timeout']);
assert.ok(migrated.every((edge) => edge.targetHandle == null || edge.targetHandle === 'default'));
console.log('node handle contract regression checks passed');
