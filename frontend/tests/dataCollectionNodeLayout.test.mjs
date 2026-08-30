import assert from 'node:assert/strict';
import fs from 'node:fs';

const node = fs.readFileSync(new URL('../components/flow/nodes/DataCollectionNode.tsx', import.meta.url), 'utf8');
const editor = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const types = fs.readFileSync(new URL('../lib/dataCollectionTypes.ts', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

assert.match(node, /variableName \|\| 'Variável não definida'/);
assert.ok(!node.includes('summary={`{{'), 'must not format the variable as a technical placeholder');
assert.match(types, /value: 'choice', label: 'Escolha'/);
assert.match(node, /DATA_COLLECTION_HANDLES\.map\(\(id\)/, 'React Flow handles must be derived from the canonical contract');
assert.ok(!node.includes("const CANONICAL_HANDLE_IDS"), 'the renderer must not maintain a second handle list');
assert.match(node, /selected=\{selected\}/);
assert.match(node, /hasValidationError=\{nodeData\.hasValidationError\}/);
assert.match(node, /structuralSignature/);
assert.match(node, /updateNodeInternals\(id\)/);
assert.match(node, /choiceLayout/);
assert.match(css, /text-overflow: ellipsis/);
assert.match(css, /\.data-collection-editor[\s\S]*overflow: hidden/);
assert.match(editor, /1\. Variável[\s\S]*2\. Tipo de dado[\s\S]*3\. Validação[\s\S]*4\. Tentativas e timeout[\s\S]*5\. Persistência[\s\S]*6\. Saídas/);

console.log('Data collection node layout regression checks passed.');
