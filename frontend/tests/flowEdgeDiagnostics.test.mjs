import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const validator = readFileSync(new URL('../lib/flowEdgeDiagnostics.ts', import.meta.url), 'utf8');
const builder = readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');

for (const reason of ['source_not_found', 'target_not_found', 'source_handle_not_found', 'target_handle_not_found', 'duplicate_edge']) {
  assert.match(validator, new RegExp(`'${reason}'`), `diagnostic includes ${reason}`);
}
assert.match(validator, /edges\.flatMap/, 'every persisted edge is traversed');
assert.match(builder, />\s*Diagnosticar fluxo\s*</, 'toolbar exposes the diagnostic action');
assert.match(builder, /stroke: '#dc2626'/, 'invalid edges are decorated in red');
assert.match(builder, /rfInstance\?\.setCenter/, 'the canvas centers the invalid edge');
assert.match(builder, /<strong>Edge inválida<\/strong>[\s\S]*source: \{issue\.source\}[\s\S]*target: \{issue\.target\}[\s\S]*handle: \{issue\.handle\}[\s\S]*motivo: \{issue\.reason\}/, 'the detailed error follows the required format');
assert.match(builder, /const structuralIssues = diagnoseFlowEdges\(currentNodes, currentEdges\)/, 'publishing is blocked by structural diagnostics');
console.log('flow edge diagnostic regression checks passed');
