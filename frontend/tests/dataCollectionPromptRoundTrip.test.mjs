import assert from 'node:assert/strict';
import fs from 'node:fs';

const builder = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const normalization = fs.readFileSync(new URL('../lib/flowNormalization.ts', import.meta.url), 'utf8');

assert.match(builder, /Mensagem de solicitação/, 'editor exposes the request-message section');
assert.match(builder, /draft\.prompt[\s\S]*onDraftChange\(\{prompt:/, 'textarea reads and updates canonical prompt');
assert.match(builder, /VariableChips[\s\S]*value=\{toText\(draft\.prompt\)\}/, 'prompt supports variables');
assert.match(builder, /data_collection:[\s\S]*prompt: 'Por favor, informe o dado solicitado\.'/,'new nodes receive a non-empty prompt');
assert.match(builder, /const \{ onChange, onToggleStart, running, hasValidationError, \.\.\.cleanData \}/, 'serialization preserves prompt in clean node data');
assert.match(normalization, /: nodeData;/, 'hydration preserves data fields including prompt');
console.log('data collection prompt round-trip contract: ok');
