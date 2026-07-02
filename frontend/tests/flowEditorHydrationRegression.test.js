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
  const internalToSystem = new Map();
  nodes.forEach((node) => {
    if (node.type !== 'ai_system') return;
    const internalNodes = Array.isArray(node.data && node.data.internal_nodes) ? node.data.internal_nodes : [];
    internalNodes.forEach((internalNode) => internalToSystem.set(String(internalNode.id), String(node.id)));
  });
  const removedInternalEdgesBySystem = new Map();
  const cleanIds = new Set(nodes.filter((node) => !blocked.has(String(node.id))).map((node) => String(node.id)));
  const cleanEdges = edges.filter((edge) => {
    const source = String(edge.source);
    const target = String(edge.target);
    const systemId = internalToSystem.get(source) || internalToSystem.get(target) || (source.includes('__') ? source.split('__')[0] : null) || (target.includes('__') ? target.split('__')[0] : null);
    if (blocked.has(source) || blocked.has(target) || internalToSystem.has(source) || internalToSystem.has(target) || source.includes('__') || target.includes('__')) {
      if (systemId) removedInternalEdgesBySystem.set(systemId, [...(removedInternalEdgesBySystem.get(systemId) || []), edge]);
      return false;
    }
    return cleanIds.has(source) && cleanIds.has(target);
  });
  const cleanNodes = nodes.filter((node) => !blocked.has(String(node.id))).map((node) => {
    if (node.type !== 'ai_system') return node;
    return {
      ...node,
      data: {
        ...node.data,
        internal_edges: [
          ...(Array.isArray(node.data && node.data.internal_edges) ? node.data.internal_edges : []),
          ...(removedInternalEdgesBySystem.get(String(node.id)) || []),
        ],
      },
    };
  });
  return { nodes: cleanNodes, edges: cleanEdges };
}

const editorGraph = {
  nodes: [{ id: 'AI_SYSTEM', type: 'ai_system', data: { name: 'Agenda Inteligente', internal_nodes: [{ id: 'AI_SYSTEM__calendar_create', type: 'ai_agent' }, { id: 'AI_SYSTEM__conversation', type: 'ai_agent' }], internal_edges: [] } }],
  edges: [],
};
const runtimeGraph = {
  nodes: [
    { id: 'dispatcher', type: 'ai_agent', data: { parent_system_id: 'agenda', original_type: 'ai_dispatcher', runtime_generated: true } },
    { id: 'calendar', type: 'ai_agent', data: { parent_system_id: 'agenda', original_type: 'ai_calendar_agent', runtime_generated: true } },
    { id: 'fallback', type: 'ai_agent', data: { parent_system_id: 'agenda', original_type: 'ai_safe_fallback', runtime_generated: true } },
  ],
  edges: [
    { id: 'e1', source: 'dispatcher', target: 'calendar' },
    { id: 'internal-calendar', source: 'AI_SYSTEM__conversation', target: 'AI_SYSTEM__calendar_create', sourceHandle: 'calendar_create' },
  ],
};

const hydrated = hydrateEditorGraph({ editor_graph: editorGraph, published_snapshot_graph: runtimeGraph, runtime_graph: runtimeGraph });
assert.deepStrictEqual(hydrated.nodes.map((node) => node.type), ['ai_system']);
assert.strictEqual(hydrated.nodes[0].data.name, 'Agenda Inteligente');

const saved = serializeEditorSave([...editorGraph.nodes, ...runtimeGraph.nodes], runtimeGraph.edges);
assert.deepStrictEqual(saved.nodes.map((node) => node.type), ['ai_system']);
assert.strictEqual(saved.nodes.length, 1);
assert.strictEqual(saved.edges.length, 0);
assert.strictEqual(saved.nodes[0].data.internal_nodes.length, 2);
assert.strictEqual(saved.nodes[0].data.internal_edges.length, 1);
assert.strictEqual(saved.edges.some((edge) => String(edge.source).includes('__') || String(edge.target).includes('__')), false);
assert.strictEqual(saved.nodes.some(isRuntimeExpandedAiAgent), false);
