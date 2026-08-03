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
const { getNodeHandleContract, migrateEdgeHandles, validateNodeConnection } = module.exports;
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

const connectionNodes = [
  { id: 'dynamic', type: 'choice_dynamic', data: {} },
  { id: 'collection', type: 'data_collection', data: {} },
  { id: 'static', type: 'choice', data: { buttons: [{ handleId: 'yes' }] } },
  { id: 'mcp', type: 'mcp_tool', data: {} },
];
const dynamicToCollection = validateNodeConnection(connectionNodes, {
  source: 'dynamic', sourceHandle: 'selected', target: 'collection', targetHandle: 'default',
});
assert.equal(dynamicToCollection.accepted, true);
assert.deepEqual([...dynamicToCollection.validSourceHandles], ['selected']);
assert.deepEqual([...dynamicToCollection.validTargetHandles], ['default']);

// onConnect persists the normalized values; JSON round-tripping models save,
// reload and publication payload boundaries without changing either handle.
const state = [{ id: 'edge-dynamic-collection', source: 'dynamic', target: 'collection', sourceHandle: dynamicToCollection.sourceHandle, targetHandle: dynamicToCollection.targetHandle }];
const reloaded = JSON.parse(JSON.stringify({ nodes: connectionNodes, edges: state }));
assert.equal(reloaded.edges[0].sourceHandle, 'selected');
assert.equal(reloaded.edges[0].targetHandle, 'default');
assert.equal(validateNodeConnection(reloaded.nodes, reloaded.edges[0]).accepted, true);

assert.equal(validateNodeConnection(connectionNodes, { source: 'dynamic', sourceHandle: 'default', target: 'collection', targetHandle: 'default' }).accepted, false);
assert.equal(validateNodeConnection(connectionNodes, { source: 'static', sourceHandle: 'yes', target: 'collection', targetHandle: 'default' }).accepted, true);
assert.equal(validateNodeConnection(connectionNodes, { source: 'mcp', sourceHandle: 'success', target: 'dynamic', targetHandle: null }).accepted, true);
assert.equal(validateNodeConnection(connectionNodes, { source: 'collection', sourceHandle: 'success', target: 'mcp', targetHandle: 'default' }).accepted, true);
console.log('node handle contract regression checks passed');
