import assert from 'node:assert/strict';
import { selectEdgeRoutingMode } from '../lib/edgeRouting.ts';

const box = (id, x, y, width = 120, height = 80) => ({ id, x, y, width, height });
const decide = (sourceNode, targetNode, extras = [], edge = { id: `${sourceNode.id}-${targetNode.id}`, source: sourceNode.id, target: targetNode.id }) =>
  selectEdgeRoutingMode({ sourceNode, targetNode, allNodes: [sourceNode, targetNode, ...extras], edge });

const a = box('a', 0, 0);
const b = box('b', 260, 0);
assert.equal(decide(a, b).mode, 'simple', '1: adjacent cards with a clear corridor stay simple');

const c = box('c', 520, 0);
assert.equal(decide(a, c, [b]).mode, 'orthogonal', '2: a card in the candidate route selects orthogonal');
assert.equal(decide(c, a, [b]).mode, 'loop_external', '3: a backward connection uses the external loop lane');

const distant = box('distant', 1600, 500);
assert.equal(decide(a, distant).mode, 'simple', '4: distance alone never forces orthogonal routing');

const closeTarget = box('close-target', 240, 120);
const closeObstacle = box('close-obstacle', 120, 60, 70, 70);
assert.equal(decide(a, closeTarget, [closeObstacle]).mode, 'orthogonal', '5: even a short edge routes around an obstacle');

assert.equal(decide(a, a, [], { id: 'self', source: 'a', target: 'a' }).mode, 'loop_external', '6: a self-loop is external');

const movedAway = box('obstacle', 260, 300);
assert.equal(decide(a, c, [movedAway]).mode, 'simple', '7: moving an obstacle out recalculates orthogonal to simple');

const movedInside = box('obstacle', 260, 0);
assert.equal(decide(a, c, [movedInside]).mode, 'orthogonal', '8: moving a card into the corridor recalculates simple to orthogonal');

assert.equal(selectEdgeRoutingMode({ sourceNode: c, targetNode: a, allNodes: [a, b, c], edge: { source: 'c', target: 'a' }, preference: 'curved' }).mode, 'simple', 'Curvo is an explicit visual override');
assert.equal(selectEdgeRoutingMode({ sourceNode: a, targetNode: b, allNodes: [a, b], edge: { source: 'a', target: 'b' }, preference: 'orthogonal' }).mode, 'orthogonal', 'Ortogonal is an explicit visual override');

console.log('Adaptive edge routing scenarios passed.');
