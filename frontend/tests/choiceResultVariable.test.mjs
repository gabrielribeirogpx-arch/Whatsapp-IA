import assert from 'node:assert/strict';
import fs from 'node:fs';

const editor = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');

const sharedField = /\}\s*<label className="flow-editor-field">\s*Salvar resposta em[\s\S]*?value=\{toText\(draft\.result_variable\)\}[\s\S]*?onDraftChange\(\{ result_variable: event\.target\.value \}\)[\s\S]*?placeholder="Ex\.: appointment_type"[\s\S]*?Variável que receberá a opção escolhida\./;

assert.match(editor, sharedField, 'fixed and dynamic Choice modes render the canonical result_variable field');
assert.match(editor, /pattern="\[A-Za-z_\]\[A-Za-z0-9_\]\*"/, 'uses the same variable-name shape as Data Collection');
assert.doesNotMatch(editor, /Salvar seleção em/, 'does not keep a second dynamic-only result field');

const choicePreset = editor.match(/choice:\s*\{[\s\S]*?choice_dynamic:/)?.[0] || '';
assert.match(choicePreset, /result_variable: 'selected_slot'/, 'existing Choice default remains unchanged');

console.log('choice result variable editor regression tests passed');
