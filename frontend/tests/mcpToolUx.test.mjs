import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const editor = readFileSync(new URL('../components/flow/MCPToolEditor.tsx', import.meta.url), 'utf8');
const node = readFileSync(new URL('../components/flow/nodes/MCPToolNode.tsx', import.meta.url), 'utf8');
const runtimeFiles = ['../../backend/app/services/flow_runtime.py', '../../backend/app/services/flow_runtime_v2.py'];

assert.match(editor, /Selecionar conexão/);
assert.match(editor, /Testar conexão/);
assert.match(editor, /input_schema|inputSchema|input_schema/);
assert.match(editor, /Modo JSON/);
assert.match(editor, /Salvar resultado em/);
assert.match(editor, /Backoff exponencial/);
assert.match(node, /'DELETE'/);
assert.match(node, /'WRITE'/);
assert.match(node, /'READ'/);
assert.match(node, /Configure uma conexão MCP/);
assert.match(node, /mcp-node-details/);
assert.match(node, /Variável de saída/);
assert.ok(runtimeFiles.every((path) => !editor.includes(path)), 'UI must not couple to runtime modules');
console.log('MCP Tool UX regression checks passed.');
