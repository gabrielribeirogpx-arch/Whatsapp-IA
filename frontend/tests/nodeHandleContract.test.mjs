import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../lib/nodeHandleContract.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const module = { exports: {} };
const require = (id) => {
  if (id === './dataCollectionHandles') return {
    DATA_COLLECTION_HANDLES: ['success', 'cancel', 'timeout', 'invalid'],
    normalizeDataCollectionEdges: (nodes, edges) => {
      const ids = new Set(nodes.filter((node) => node.type === 'data_collection').map((node) => node.id));
      return edges.map((edge) => ids.has(edge.source) && edge.sourceHandle === 'retry_exhausted'
        ? { ...edge, sourceHandle: 'invalid' }
        : edge);
    },
  };
  throw new Error(`Unexpected import: ${id}`);
};
vm.runInNewContext(compiled, { module, exports: module.exports, require });
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
const legacy = migrateEdgeHandles([{ id: 'collection', type: 'data_collection' }], [{ source: 'collection', target: 'target', sourceHandle: 'retry_exhausted' }]);
assert.equal(legacy[0].sourceHandle, 'invalid');
console.log('node handle contract regression checks passed');
