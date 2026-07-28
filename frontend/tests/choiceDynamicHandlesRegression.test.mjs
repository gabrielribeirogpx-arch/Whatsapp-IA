import assert from 'node:assert/strict';
import fs from 'node:fs';

const editorSource = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const choiceNodeSource = fs.readFileSync(new URL('../components/flow/nodes/ChoiceNode.tsx', import.meta.url), 'utf8');
const compactNodeSource = fs.readFileSync(new URL('../components/flow/nodes/CompactFlowNode.tsx', import.meta.url), 'utf8');

// Keep this behavior model aligned with the editor contract while also checking
// the production source below, so this regression test can run without a DOM.
let sequence = 0;
const createChoiceButton = (nodeId, ordinal) => {
  const identity = `stable-${++sequence}`;
  return {
    id: `${nodeId}-button-${identity}`,
    label: `Opção ${ordinal}`,
    handleId: `choice_${identity.replace(/[^a-z0-9]/g, '')}`,
  };
};

const initial = [
  { id: 'choice-1', label: 'Quero planos', handleId: 'quero_planos' },
  { id: 'choice-2', label: 'Falar com humano', handleId: 'falar_com_humano' },
];
const option3 = createChoiceButton('choice-node', 3);
const buttons = [...initial, option3];

assert.equal(buttons.length, 3);
assert.ok(option3.id);
assert.ok(option3.handleId);
assert.equal(new Set(buttons.map((button) => button.handleId)).size, 3);

const edge = {
  id: 'choice-node-message-3',
  source: 'choice-node',
  sourceHandle: option3.handleId,
  target: 'message-3',
  targetHandle: 'default',
  data: { sourceHandle: option3.handleId },
};
assert.equal(edge.sourceHandle, option3.handleId);
assert.equal(edge.data.sourceHandle, option3.handleId);
assert.equal(edge.target, 'message-3');

const afterRemoval = buttons.filter((button) => button.id !== 'choice-2');
assert.equal(afterRemoval.find((button) => button.id === option3.id)?.handleId, option3.handleId);
const reordered = [option3, initial[0]];
assert.equal(reordered[0].handleId, option3.handleId);

const snapshot = JSON.parse(JSON.stringify({ nodes: [{ id: 'choice-node', data: { buttons } }], edges: [edge] }));
assert.equal(snapshot.nodes[0].data.buttons[2].handleId, option3.handleId);
assert.equal(snapshot.edges[0].sourceHandle, option3.handleId);
assert.equal(snapshot.edges[0].data.sourceHandle, option3.handleId);
assert.equal(snapshot.edges.find((item) => item.sourceHandle === option3.handleId)?.target, 'message-3');

assert.match(editorSource, /createChoiceButton\(node\.id, nextIndex\)/);
assert.match(editorSource, /next\[index\] = \{ \.\.\.next\[index\], label \}/);
assert.match(editorSource, /key=\{button\.id \|\| button\.handleId\}/);
assert.match(editorSource, /data:\s*\{\s*sourceHandle: sourceHandle \|\| undefined,/s);
assert.match(choiceNodeSource, /useUpdateNodeInternals/);
assert.match(choiceNodeSource, /requestAnimationFrame\(\(\) => updateNodeInternals\(id\)\)/);
assert.match(choiceNodeSource, /sourceHandles=\{buttons\.map/);
assert.match(compactNodeSource, /id=\{handle\.id\}[\s\S]*?type="source"/);
assert.match(compactNodeSource, /pointerEvents: isConnectable \? 'auto' : 'none'/);

console.log('choice dynamic handles regression: ok');
