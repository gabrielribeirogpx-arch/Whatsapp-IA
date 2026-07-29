import assert from 'node:assert/strict';
import fs from 'node:fs';

const builder = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const edge = fs.readFileSync(new URL('../components/flow/SmartOrthogonalEdge.tsx', import.meta.url), 'utf8');

for (const contract of ['auto_retry_invalid', 'attempts_exceeded_behavior', 'Repetir automaticamente quando inválido', 'Seguir pela saída Inválido']) {
  assert.ok(builder.includes(contract), `${contract} is exposed by the data collection editor`);
}
assert.match(builder, /type: 'smart'/);
assert.match(builder, /defaultEdgeOptions=\{\{ type: 'smart' \}\}/);
assert.match(edge, /getSmoothStepPath/);
assert.match(edge, /const isReturn/);
