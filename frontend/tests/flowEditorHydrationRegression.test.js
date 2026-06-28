const assert = require('assert');

const internalTypes = new Set(['ai_dispatcher', 'ai_greeting', 'ai_calendar_agent', 'ai_safe_fallback', 'ai_agent']);
const expandedOriginalTypes = new Set(['ai_dispatcher', 'ai_greeting', 'ai_calendar_agent', 'ai_safe_fallback']);

function isRuntimeExpandedAiAgent(node) {
  const data = node.data || {};
  const hasRuntimeParent = Boolean(data.parent_system_id || data.system_id || data.ai_system_parent_id || data.parentSystemId || data.runtime_generated === true);
  const isExpandedAgent = String(node.type || '') === 'ai_agent' && expandedOriginalTypes.has(String(data.original_type || ''));
  return (internalTypes.has(String(node.type || '')) && hasRuntimeParent) || isExpandedAgent;
}

function hydrateEditorGraph(payload) {
  const graph = payload.editor_graph && Array.isArray(payload.editor_graph.nodes)
    ? payload.editor_graph
    : { nodes: [], edges: [] };
  if (graph.nodes.some(isRuntimeExpandedAiAgent)) throw new Error('runtime graph blocked');
  return graph;
}

function serializeEditorSave(nodes, edges) {
  const blocked = new Set(nodes.filter(isRuntimeExpandedAiAgent).map((node) => String(node.id)));
  const cleanNodes = nodes.filter((node) => !blocked.has(String(node.id)));
  const cleanIds = new Set(cleanNodes.map((node) => String(node.id)));
  const cleanEdges = edges.filter((edge) => !blocked.has(String(edge.source)) && !blocked.has(String(edge.target)) && cleanIds.has(String(edge.source)) && cleanIds.has(String(edge.target)));
  return { nodes: cleanNodes, edges: cleanEdges };
}

const editorGraph = {
  nodes: [{ id: 'agenda', type: 'ai_system', data: { name: 'Agenda Inteligente', internal_nodes: [{ id: 'agent-1', type: 'ai_agent' }] } }],
  edges: [],
};
const runtimeGraph = {
  nodes: [
    { id: 'dispatcher', type: 'ai_agent', data: { parent_system_id: 'agenda', original_type: 'ai_dispatcher', runtime_generated: true } },
    { id: 'calendar', type: 'ai_agent', data: { parent_system_id: 'agenda', original_type: 'ai_calendar_agent', runtime_generated: true } },
    { id: 'fallback', type: 'ai_agent', data: { parent_system_id: 'agenda', original_type: 'ai_safe_fallback', runtime_generated: true } },
  ],
  edges: [{ id: 'e1', source: 'dispatcher', target: 'calendar' }],
};

const hydrated = hydrateEditorGraph({ editor_graph: editorGraph, published_snapshot_graph: runtimeGraph, runtime_graph: runtimeGraph });
assert.deepStrictEqual(hydrated.nodes.map((node) => node.type), ['ai_system']);
assert.strictEqual(hydrated.nodes[0].data.name, 'Agenda Inteligente');

const saved = serializeEditorSave([...editorGraph.nodes, ...runtimeGraph.nodes], runtimeGraph.edges);
assert.deepStrictEqual(saved.nodes.map((node) => node.type), ['ai_system']);
assert.strictEqual(saved.edges.length, 0);
assert.strictEqual(saved.nodes.some(isRuntimeExpandedAiAgent), false);
