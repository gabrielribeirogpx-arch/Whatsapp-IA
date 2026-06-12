import assert from 'node:assert/strict';
import test from 'node:test';

const { parseApiResponse } = await import('./api.ts');

test('parseApiResponse returns undefined for 204 responses', async () => {
  const result = await parseApiResponse(new Response(null, { status: 204 }));
  assert.equal(result, undefined);
});

test('parseApiResponse returns undefined for successful empty responses', async () => {
  const result = await parseApiResponse(new Response('', { status: 200 }));
  assert.equal(result, undefined);
});

test('parseApiResponse parses JSON bodies when present', async () => {
  const result = await parseApiResponse(new Response(JSON.stringify({ ok: true }), { status: 200 }));
  assert.deepEqual(result, { ok: true });
});
