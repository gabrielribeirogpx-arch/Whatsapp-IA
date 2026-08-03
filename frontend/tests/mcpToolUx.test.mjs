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
assert.match(node, /<small>Saída<\/small>/);
// Persistent MCP configuration always travels through the canonical draft patch,
// which FlowBuilderClient immediately merges into React Flow's node.data.
assert.match(editor, /onDraftChange\(\{ connection_id: id, connection_name: name/);
assert.match(editor, /connection_kind:/);
assert.match(editor, /connection_verified: false/);
assert.match(editor, /tool_name: '', tool_description: '', tool_risk: '', input_schema: \{\}/);
assert.match(editor, /connection_verified: true, connection_status: 'connected'/);
assert.match(editor, /connection_last_tested_at: new Date\(\)\.toISOString\(\)/);
assert.match(editor, /tool_description: tool\?\.description/);
assert.match(editor, /input_schema: tool\?\.input_schema/);
assert.doesNotMatch(editor, /credential|access_token|refresh_token|api_key/i);

// The panel restores verification/latency from node.data instead of local state.
assert.match(editor, /draft\.connection_verified === true/);
assert.match(editor, /draft\.connection_latency_ms/);

// The card distinguishes all partial states and validates required arguments.
assert.match(node, /const hasConnection = Boolean\(data\?\.connection_id\)/);
assert.match(node, /const hasTool = Boolean\(data\?\.tool_name\)/);
assert.match(node, /const hasOutput = Boolean\(data\?\.output_variable\)/);
assert.match(node, /requiredArgumentsAreValid/);
assert.match(node, /Não configurado/);
assert.match(node, /Configuração incompleta/);
assert.match(node, /Selecione uma ferramenta/);
assert.match(node, /Conexão verificada/);
assert.match(node, /connection_name \|\| data\?\.server_name/);
assert.ok(runtimeFiles.every((path) => !editor.includes(path)), 'UI must not couple to runtime modules');
console.log('MCP Tool UX regression checks passed.');
