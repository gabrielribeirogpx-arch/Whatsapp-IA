import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';

const parserSource = fs.readFileSync(new URL('../lib/simulatorError.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(parserSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const module = { exports: {} };
vm.runInNewContext(compiled, { module, exports: module.exports, TypeError });
const { parseSimulatorError } = module.exports;

const structured = parseSimulatorError({
  response: { data: { detail: { errors: [{ code: 'NODE_WITHOUT_OUTPUT', node_id: 'handoff', message: 'Conecte este node a outro ou marque-o como final.' }] } } },
});
assert.equal(structured.title, 'Não foi possível iniciar a simulação');
assert.equal(structured.errors[0].node_id, 'handoff');
assert.doesNotMatch(JSON.stringify(structured), /\[object Object\]|HTTPException/);

const network = parseSimulatorError(new TypeError('Failed to fetch'));
assert.equal(network.retryable, true);
assert.match(network.message, /conexão/i);

const builder = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
assert.match(builder, />Localizar no fluxo</);
assert.match(builder, /setCenter\(/);
assert.match(builder, /setSelectedNodeId\(nodeId\)/);
assert.match(builder, />Tentar novamente</);
assert.doesNotMatch(builder, /\[HTTP \$\{response\.status\}\]/);

console.log('simulator error and navigation UX checks passed');
