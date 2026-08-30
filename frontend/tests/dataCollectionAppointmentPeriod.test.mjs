import assert from 'node:assert/strict';
import fs from 'node:fs';

const types = fs.readFileSync(new URL('../lib/dataCollectionTypes.ts', import.meta.url), 'utf8');
const editor = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const node = fs.readFileSync(new URL('../components/flow/nodes/DataCollectionNode.tsx', import.meta.url), 'utf8');

const expectedLegacyTypes = ['text', 'number', 'email', 'phone', 'date', 'time', 'cpf', 'cnpj', 'url', 'currency', 'boolean', 'choice'];
for (const value of expectedLegacyTypes) {
  assert.match(types, new RegExp(`value: '${value}'`), `legacy type ${value} remains available`);
}

assert.match(types, /value: 'appointment_period', label: 'Período de agendamento'/, 'appointment_period is shown with its product label');
assert.match(editor, /DATA_COLLECTION_TYPE_OPTIONS\.map\(type=><option key=\{type\.value\} value=\{type\.value\}>\{type\.label\}<\/option>\)/, 'the dropdown persists the canonical option value');
assert.match(editor, /value=\{toText\(draft\.data_type\|\|'text'\)\}/, 'reopening binds the select to the persisted data_type and keeps text as the legacy fallback');
assert.match(editor, /onDraftChange\(\{data_type:e\.target\.value\}\)/, 'selection is saved to the canonical data_type field');
assert.match(editor, /const \{ onChange, onToggleStart, running, hasValidationError, \.\.\.cleanData \} = nodeData/, 'snapshot serialization retains data_type without remapping it');
assert.match(editor, /data: \{[\s\S]{0,80}\.\.\.cleanData/, 'snapshot uses the same canonical node data object');
assert.doesNotMatch(editor, /data_type\s*:\s*['"]text['"][\s\S]{0,80}(?:serializeFlowGraph|cleanData)/, 'serialization does not coerce structured or old data types to text');
assert.match(node, /getDataCollectionTypeLabel\(dataType\)/, 'the node card renders the friendly appointment period label');

// Old flows commonly used this variable name while storing an ordinary text value.
// Neither hydration nor serialization special-cases it, so both shapes remain lossless.
assert.match(editor, /placeholder="preferred_period"/, 'preferred_period remains supported as a variable name');

console.log('Appointment period data collection regression checks passed.');
