import assert from 'node:assert/strict';
import fs from 'node:fs';

const builder = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const edge = fs.readFileSync(new URL('../components/flow/SmartOrthogonalEdge.tsx', import.meta.url), 'utf8');

for (const contract of ['auto_retry_invalid', 'attempts_exceeded_behavior', 'Repetir automaticamente quando inválido', 'Seguir pela saída Inválido']) {
  assert.ok(builder.includes(contract), `${contract} is exposed by the data collection editor`);
}
assert.match(builder, /type: 'smart'/);
assert.match(builder, /defaultEdgeOptions=\{\{ type: 'smart' \}\}/);
assert.match(builder, /type: 'default',[\s\S]{0,160}data: \{[\s\S]{0,80}sourceHandle/, 'new edges keep their persisted type and handles');
assert.match(builder, /__routingPreference: edgeRoutingPreference/, 'routing preference is injected only into decorated render data');
assert.match(edge, /selectEdgeRoutingMode/);
assert.match(edge, /getBezierPath/);
