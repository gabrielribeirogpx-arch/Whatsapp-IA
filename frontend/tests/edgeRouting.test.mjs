import assert from 'node:assert/strict';
import { externalRouteCandidates, routeIntersectsNodes, selectEdgeRoutingMode } from '../lib/edgeRouting.ts';

const box = (id, x, y, width = 120, height = 80) => ({ id, x, y, width, height });
const decide = (sourceNode, targetNode, extras = [], edge = { id: `${sourceNode.id}-${targetNode.id}`, source: sourceNode.id, target: targetNode.id }, allEdges = []) =>
  selectEdgeRoutingMode({ sourceNode, targetNode, allNodes: [sourceNode, targetNode, ...extras], edge, allEdges });

const a = box('a', 0, 0), b = box('b', 260, 0), c = box('c', 520, 0);
assert.equal(decide(a, b).mode, 'simple', '1: adjacent clear cards stay simple');
assert.equal(decide(a, c, [b]).mode, 'orthogonal', '2: an obstacle selects orthogonal');
assert.equal(decide(c, a, [b]).mode, 'loop_external', '3: a short return is a loop, not convergence');

const source = box('lower-branch', 1100, 720), target = box('shared', 100, 40);
const centerNodes = [box('middle-1', 420, 260, 180, 120), box('middle-2', 700, 450, 180, 120)];
const sharedEdge = { id: 'existing', source: 'other', target: 'shared' };
assert.equal(decide(source, target, centerNodes, { id: 'converge', source: source.id, target: target.id }, [sharedEdge]).mode, 'convergence_external', '4: a distant lower branch converges externally');

const nodes = [source, target, ...centerNodes];
const first = externalRouteCandidates({ x: 1100, y: 760 }, { x: 220, y: 80 }, nodes, new Set([source.id, target.id]), { id: 'one', source: source.id, target: target.id }, [], 0, 'right', 'left')[0];
const second = externalRouteCandidates({ x: 1100, y: 760 }, { x: 220, y: 80 }, nodes, new Set([source.id, target.id]), { id: 'two', source: source.id, target: target.id }, [], 1, 'right', 'left')[0];
assert.equal(first.nodeIntersections, 0, '5/6: chosen external route clears every card');
assert.notDeepEqual(first.points, second.points, '5: parallel convergence edges receive distinct lanes');
assert.equal(routeIntersectsNodes(first.points, nodes, 28, new Set([source.id, target.id])).length, 0);
assert.deepEqual(first.points.at(-1), { x: 220, y: 80 }, '10: target endpoint is preserved');
assert.equal(first.points.at(-2).y, 80, '10: a left target handle is approached horizontally');

const movedAway = box('obstacle', 260, 300), movedInside = box('obstacle', 260, 0);
assert.equal(decide(a, c, [movedAway]).mode, 'simple', '7: freeing the corridor recalculates to simple');
assert.equal(decide(a, c, [movedInside]).mode, 'orthogonal', '8: blocking it recalculates to orthogonal');
assert.equal(selectEdgeRoutingMode({ sourceNode: c, targetNode: a, allNodes: [a, b, c], edge: { source: 'c', target: 'a' }, preference: 'curved' }).mode, 'simple');
assert.equal(selectEdgeRoutingMode({ sourceNode: a, targetNode: b, allNodes: [a, b], edge: { source: 'a', target: 'b' }, preference: 'orthogonal' }).mode, 'orthogonal');
console.log('Adaptive edge routing scenarios passed.');
