import assert from 'node:assert/strict';
import fs from 'node:fs';

const helper = fs.readFileSync(new URL('../lib/dynamicChoice.ts', import.meta.url), 'utf8');
const editor = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const canvas = fs.readFileSync(new URL('../components/flow/nodes/ChoiceNode.tsx', import.meta.url), 'utf8');

assert.match(helper, /\['label', 'title', 'name', 'text'\]/, 'discovers common title fields');
assert.match(helper, /records\.slice\(0, 5\).*Object\.keys/, 'updates schema from current examples');
assert.match(helper, /items', 'data', 'results', 'appointments', 'options'/, 'unwraps complex MCP objects');
assert.match(editor, /label_field: schema\.labelField[\s\S]*value_field: schema\.valueField/, 'auto-fills mappings');
assert.match(editor, /preview_options: schema\.records\.slice\(0, 5\)/, 'limits real preview to five records');
assert.match(editor, /Nenhum dado disponível\. O preview será exibido após o primeiro retorno do MCP\./, 'explains an empty preview');
assert.match(editor, /Estrutura detectada/, 'renders the schema inspector');
assert.match(editor, /dynamicChoiceVariables/, 'registers result object fields with autocomplete');
assert.match(editor, /Detectamos que o MCP retorna uma lista/, 'offers MCP one-click configuration');
assert.match(editor, /onChange=\{e => onDraftChange\(\{ label_field:/, 'keeps mappings manually editable');
assert.match(editor, /Opções \{displayMode === 'buttons'/, 'keeps fixed choices on their existing path');
assert.match(canvas, /title=\{nodeData\.options_mode === 'dynamic' \? 'Escolha Dinâmica'/, 'enhances only the dynamic canvas card');

console.log('dynamic choice low-code regression: ok');
