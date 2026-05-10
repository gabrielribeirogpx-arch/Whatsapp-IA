import assert from 'node:assert/strict';
import test from 'node:test';

const UUID_LIKE_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const TEMP_PREFIXES = ['template-', 'temp-', 'mock-'];

type GraphNode = { id: string };
type GraphEdge = { id: string; source: string; target: string };

function hasTempPrefix(value: string): boolean {
  return TEMP_PREFIXES.some((prefix) => value.startsWith(prefix));
}

function buildSimpleTemplateGraph() {
  const startId = crypto.randomUUID();
  const conditionId = crypto.randomUUID();
  const yesId = crypto.randomUUID();
  const noId = crypto.randomUUID();

  const nodes: GraphNode[] = [
    { id: startId },
    { id: conditionId },
    { id: yesId },
    { id: noId },
  ];

  const edges: GraphEdge[] = [
    { id: crypto.randomUUID(), source: startId, target: conditionId },
    { id: crypto.randomUUID(), source: conditionId, target: yesId },
    { id: crypto.randomUUID(), source: conditionId, target: noId },
  ];

  return { nodes, edges };
}

test('template graph uses real UUID ids', () => {
  const graph = buildSimpleTemplateGraph();

  for (const node of graph.nodes) {
    assert.equal(hasTempPrefix(node.id), false);
    assert.equal(UUID_LIKE_REGEX.test(node.id), true);
  }

  for (const edge of graph.edges) {
    assert.equal(hasTempPrefix(edge.id), false);
    assert.equal(hasTempPrefix(edge.source), false);
    assert.equal(hasTempPrefix(edge.target), false);
    assert.equal(UUID_LIKE_REGEX.test(edge.id), true);
    assert.equal(UUID_LIKE_REGEX.test(edge.source), true);
    assert.equal(UUID_LIKE_REGEX.test(edge.target), true);
  }
});
