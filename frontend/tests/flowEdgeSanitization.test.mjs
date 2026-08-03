import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../lib/flowEdgeDiagnostics.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const module = { exports: {} };
vm.runInNewContext(compiled, {
  module,
  exports: module.exports,
  require: (id) => {
    if (id === './dataCollectionHandles') return { DATA_COLLECTION_HANDLES: ['success', 'invalid', 'cancel', 'timeout'] };
    throw new Error(`Unexpected import: ${id}`);
  },
});
const { diagnoseFlowEdges, sanitizeEdges, sanitizeNodes } = module.exports;

const node = (id, type = 'message', data = {}) => ({ id, type, data });
const edge = (id, sourceId, targetId, sourceHandle = 'default', targetHandle = 'default') =>
  ({ id, source: sourceId, target: targetId, sourceHandle, targetHandle });
const target = node('target');

assert.deepEqual(sanitizeNodes([node(''), node('source'), node('source')]).map((item) => item.id), ['source']);

// delete node, orphan endpoints and self loops
assert.deepEqual([...sanitizeEdges([target], [edge('out', 'deleted', 'target')])], []);
assert.deepEqual([...sanitizeEdges([node('source')], [edge('in', 'source', 'deleted')])], []);
assert.equal(diagnoseFlowEdges([target], [edge('loop', 'target', 'target')])[0].reason, 'self_loop');

// duplicate, paste/import and duplicate-node operations retain only the first edge
const duplicateEdges = [edge('first', 'source', 'target'), edge('copy', 'source', 'target')];
assert.deepEqual(sanitizeEdges([node('source'), target], duplicateEdges).map((item) => item.id), ['first']);

// Conversions derive handles afresh; no old MCP/Choice handles survive.
for (const staleHandle of ['error', 'success', 'timeout', 'selected', 'invalid']) {
  assert.deepEqual([...sanitizeEdges([node('source', 'message'), target], [edge(staleHandle, 'source', 'target', staleHandle)])], []);
}
for (const handle of ['success', 'error', 'timeout']) {
  assert.equal(sanitizeEdges([node('source', 'mcp_tool'), target], [edge(handle, 'source', 'target', handle)]).length, 1);
}
// Choice -> Dynamic Choice removes option handles and accepts only its current default output.
const dynamic = node('source', 'choice_dynamic', { buttons: [{ handleId: 'selected' }] });
assert.deepEqual([...sanitizeEdges([dynamic, target], [edge('selected', 'source', 'target', 'selected')])], []);
assert.equal(sanitizeEdges([dynamic, target], [edge('default', 'source', 'target')]).length, 1);

// Handle removal, undo/redo snapshots, export/import and pre-publish sanitization all use the same pure invariant.
const choiceBefore = node('source', 'choice', { buttons: [{ handleId: 'selected' }] });
const choiceAfter = node('source', 'choice', { buttons: [] });
const selectedEdge = edge('selected', 'source', 'target', 'selected');
assert.equal(sanitizeEdges([choiceBefore, target], [selectedEdge]).length, 1, 'undo snapshot restores a valid handle');
assert.equal(sanitizeEdges([choiceAfter, target], [selectedEdge]).length, 0, 'redo snapshot removes the stale handle');
const exported = JSON.parse(JSON.stringify({ nodes: [choiceAfter, target], edges: [selectedEdge] }));
assert.equal(sanitizeEdges(exported.nodes, exported.edges).length, 0, 'import and publish cannot serialize stale edges');

console.log('flow edge sanitization regression checks passed');
