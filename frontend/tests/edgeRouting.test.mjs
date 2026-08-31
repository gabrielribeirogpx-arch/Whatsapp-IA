import assert from 'node:assert/strict';
import { externalRouteCandidates, graphBoundingBox, localFeedbackRouteCandidates, parallelEdgeLaneIndex, routeIntersectsNodes, selectEdgeRoutingMode } from '../lib/edgeRouting.ts';

const box = (id, x, y, width = 120, height = 80) => ({ id, x, y, width, height });
const decide = (sourceNode, targetNode, extras = [], edge = { id: `${sourceNode.id}-${targetNode.id}`, source: sourceNode.id, target: targetNode.id }, allEdges = []) =>
  selectEdgeRoutingMode({ sourceNode, targetNode, allNodes: [sourceNode, targetNode, ...extras], edge, allEdges });

const a = box('a', 0, 0), b = box('b', 260, 0), c = box('c', 520, 0);
assert.equal(decide(a, b).mode, 'simple', '1: adjacent clear cards stay simple');
assert.equal(decide(a, c, [b]).mode, 'orthogonal', '2: an obstacle selects orthogonal');
assert.equal(decide(c, a, [b]).mode, 'feedback_local', '3: a short return uses a local feedback route');

const feedbackStart = { x: c.x + c.width, y: c.y + 40 }, feedbackEnd = { x: b.x, y: b.y + 40 };
const local = localFeedbackRouteCandidates(feedbackStart, feedbackEnd, c, b, [a, b, c], new Set(['b', 'c']), { id: 'return-1', source: 'c', target: 'b' })[0];
const localBounds = graphBoundingBox(local.points.map((point, index) => ({ id: String(index), ...point, width: 1, height: 1 })));
assert.ok(localBounds.minX >= b.x - 28 && localBounds.maxX <= c.x + c.width + 29, '4: feedback bounding box stays by its endpoints, not the canvas perimeter');
assert.equal(routeIntersectsNodes(local.points, [b, c], 0, new Set(['b', 'c'])).length, 0, '5: endpoint cards are deliberately approached only through their handles');
assert.deepEqual(local.points[0], feedbackStart, '6: source handle is preserved');
assert.deepEqual(local.points.at(-1), feedbackEnd, '6: target handle is preserved');
assert.ok(local.points.some(point => point.y < b.y), '7: label has a clear horizontal local corridor');
const localSecond = localFeedbackRouteCandidates(feedbackStart, feedbackEnd, c, b, [a, b, c], new Set(['b', 'c']), { id: 'return-2', source: 'c', target: 'b' }, [], 1)[0];
assert.notDeepEqual(local.points, localSecond.points, '8: nearby feedback edges use distinct local lanes');
const moved = box('c', 600, 180);
const movedRoute = localFeedbackRouteCandidates({ x: 720, y: 220 }, feedbackEnd, moved, b, [a, b, moved], new Set(['b', 'c']), { source: 'c', target: 'b' })[0];
assert.notDeepEqual(local.points, movedRoute.points, '9: moving an endpoint recomputes feedback waypoints');

// Regression: a reciprocal feedback edge must not turn the forward edge into a loop
// or share its lane group. Handles are part of the directed grouping identity.
const choice = box('choice', 0, 120), confirmation = box('confirmation', 300, 120);
const selected = { id: 'selected-edge', source: 'choice', target: 'confirmation', sourceHandle: 'selected', targetHandle: 'input' };
const chooseAnother = { id: 'choose-another-edge', source: 'confirmation', target: 'choice', sourceHandle: 'choose_another_time', targetHandle: 'input' };
const reciprocalEdges = [selected, chooseAnother];
assert.equal(decide(choice, confirmation, [], selected, reciprocalEdges).mode, 'simple', '10: reciprocal feedback does not reclassify a clear forward edge');
assert.equal(decide(confirmation, choice, [], chooseAnother, reciprocalEdges).mode, 'feedback_local', '11: reciprocal backwards edge remains local feedback');
assert.equal(parallelEdgeLaneIndex(selected, reciprocalEdges), 0, '12: forward direction has its own lane group');
assert.equal(parallelEdgeLaneIndex(chooseAnother, reciprocalEdges), 0, '12: reverse direction has its own lane group');

const forwardStart = { x: choice.x + choice.width, y: choice.y + 40 }, forwardEnd = { x: confirmation.x, y: confirmation.y + 40 };
const forwardBounds = graphBoundingBox([forwardStart, forwardEnd].map((point, index) => ({ id: `forward-${index}`, ...point, width: 1, height: 1 })));
assert.ok(forwardBounds.minX >= choice.x && forwardBounds.maxX <= confirmation.x + 1, '13: direct forward route stays inside the endpoint corridor');
const reverseRoute = localFeedbackRouteCandidates(forwardEnd, forwardStart, confirmation, choice, [choice, confirmation], new Set(['choice', 'confirmation']), chooseAnother, reciprocalEdges, 0)[0];
assert.ok(reverseRoute.points.some(point => point.y < choice.y || point.y > choice.y + choice.height), '14: reverse route loops above or below the adjacent nodes');
assert.notEqual(reverseRoute.lane, 'right', '15: local feedback does not receive a forward/external corridor');
assert.deepEqual([selected.source, selected.target, selected.sourceHandle, selected.targetHandle], ['choice', 'confirmation', 'selected', 'input'], '16: forward direction and handles are preserved');
assert.deepEqual([chooseAnother.source, chooseAnother.target, chooseAnother.sourceHandle, chooseAnother.targetHandle], ['confirmation', 'choice', 'choose_another_time', 'input'], '16: feedback direction and handles are preserved');

const movedChoice = box('choice', 40, 220), movedConfirmation = box('confirmation', 380, 260);
assert.equal(decide(movedChoice, movedConfirmation, [], selected, reciprocalEdges).mode, 'simple', '17: moving nodes recalculates and preserves the forward route mode');
const movedReciprocal = localFeedbackRouteCandidates({ x: movedConfirmation.x, y: 300 }, { x: movedChoice.x + movedChoice.width, y: 260 }, movedConfirmation, movedChoice, [movedChoice, movedConfirmation], new Set(['choice', 'confirmation']), chooseAnother, reciprocalEdges, 0)[0];
assert.notDeepEqual(reverseRoute.points, movedReciprocal.points, '17: moving nodes recalculates the reciprocal feedback geometry');

const secondFeedback = { ...chooseAnother, id: 'choose-another-edge-2' };
assert.equal(parallelEdgeLaneIndex(secondFeedback, [...reciprocalEdges, secondFeedback]), 1, '18: truly parallel feedback edges retain separate lanes');
const differentHandle = { ...chooseAnother, id: 'different-handle', sourceHandle: 'cancel' };
assert.equal(parallelEdgeLaneIndex(differentHandle, [...reciprocalEdges, differentHandle]), 0, '19: a different handle starts a separate directed lane group');

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
