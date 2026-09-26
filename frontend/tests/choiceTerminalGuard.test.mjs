import assert from 'node:assert/strict';
import fs from 'node:fs';

const editor = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const validation = fs.readFileSync(new URL('../lib/flowValidation.ts', import.meta.url), 'utf8');

assert.match(editor, /const hasOutgoingEdges = allEdges\.some\(\(edge\) => edge\.source === node\.id\)/, 'editor detects outgoing edges');
assert.match(editor, /disabled=\{hasOutgoingEdges && !draft\.is_terminal\}/, 'terminal checkbox is disabled after a node has an outgoing edge');
assert.match(editor, /Desmarque esta opção se o flow for legado/, 'legacy contradictory nodes can still be unmarked');
assert.match(validation, /CHOICE_TERMINAL_WITH_OUTGOING_EDGE/, 'local publish validation rejects contradictory Choice state');

console.log('choice terminal guard regression: ok');
