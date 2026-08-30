import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const source = readFileSync(new URL('../lib/flowElementDeletion.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const module = { exports: {} };
class FakeElement {
  constructor(matches = []) { this.matches = new Set(matches); }
  closest(selector) { return selector.split(',').some((part) => this.matches.has(part.trim())) ? this : null; }
}
vm.runInNewContext(compiled, { module, exports: module.exports, Element: FakeElement, Set });
const { isFlowEditorTextEntryTarget, isFlowElementDeleteKey, removeElementsById, selectedDeletableIds } = module.exports;

assert.equal(isFlowElementDeleteKey('Delete'), true, 'Delete is supported');
assert.equal(isFlowElementDeleteKey('Backspace'), true, 'Backspace is supported');
assert.equal(isFlowElementDeleteKey('Enter'), false, 'unrelated shortcuts are preserved');

const nodes = [{ id: 'choice', selected: false }, { id: 'message', selected: false }];
const edges = [
  { id: 'custom-labelled', selected: true, type: 'smart', label: 'Escolher outro horário' },
  { id: 'unselected', selected: false },
];
const deletedIds = selectedDeletableIds(edges, false);
assert.deepEqual([...deletedIds], ['custom-labelled'], 'custom and labelled selected edges are deletable');
const serialized = { nodes, edges: removeElementsById(edges, deletedIds) };
assert.deepEqual(serialized.edges.map(({ id }) => id), ['unselected'], 'deleted edge is absent from serialized state');
assert.deepEqual(serialized.nodes.map(({ id }) => id), ['choice', 'message'], 'unselected nodes remain intact');
const rehydrated = JSON.parse(JSON.stringify(serialized));
assert.equal(rehydrated.edges.some(({ id }) => id === 'custom-labelled'), false, 'deleted edge does not reappear after rehydration');

assert.deepEqual([...selectedDeletableIds(edges, true)], [], 'locked canvas cannot delete selected edges');
assert.deepEqual([...selectedDeletableIds([{ id: 'protected', selected: true, deletable: false }], false)], [], 'non-deletable edges stay intact');
assert.equal(isFlowEditorTextEntryTarget(new FakeElement(['input'])), true, 'input typing is protected');
assert.equal(isFlowEditorTextEntryTarget(new FakeElement(['textarea'])), true, 'textarea typing is protected');
assert.equal(isFlowEditorTextEntryTarget(new FakeElement(['.flow-node-editor-panel'])), true, 'the entire editor panel is protected');

console.log('flow element deletion regression checks passed');
