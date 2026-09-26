import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const api = readFileSync(new URL('../lib/api.ts', import.meta.url), 'utf8');
const builder = readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');

test('Flow Builder exposes export separately from snapshot and activation', () => {
  assert.match(builder, />\s*Exportar fluxo\s*</);
  assert.match(builder, /onClick=\{\(\) => void handleExportFlow\(\)\}/);
  const handler = builder.slice(builder.indexOf('const handleExportFlow'), builder.indexOf('const handleExportFlow') + 500);
  assert.match(handler, /exportFlow\(selectedFlowId\)/);
  assert.doesNotMatch(handler, /publish|activate|snapshot|handleSaveFlow/i);
  assert.match(handler, /Não foi possível exportar o fluxo/);
});

test('export API uses authenticated wrapper and starts a browser download', () => {
  const helper = api.slice(api.indexOf('export async function exportFlow'), api.indexOf('export async function exportFlow') + 1400);
  assert.match(helper, /apiFetch\(`\/api\/flows\/\$\{encodeURIComponent\(flowId\)\}\/export`/);
  assert.match(helper, /response\.blob\(\)/);
  assert.match(helper, /anchor\.download = filename/);
  assert.match(helper, /anchor\.click\(\)/);
  assert.match(helper, /URL\.revokeObjectURL/);
});
