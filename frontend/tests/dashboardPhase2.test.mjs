import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const hook = readFileSync(new URL('../hooks/useDashboardAnalytics.ts', import.meta.url), 'utf8');
const page = readFileSync(new URL('../app/dashboard/page.tsx', import.meta.url), 'utf8');

test('stock and unavailable KPIs do not fabricate comparisons or values', () => {
  assert.match(page, /label: 'Leads ativos'/);
  assert.match(page, /item\.key === 'responseRate'.*response_rate_delta/s);
  assert.match(page, /isUnavailable \? '—'/);
  assert.doesNotMatch(page, /item\.key === 'activeLeads'.*delta/s);
  assert.match(hook, /response_rate: null/);
});

test('labels expose the supported semantics', () => {
  assert.match(page, /label: 'Conversas movimentadas'/);
  assert.match(page, /label: 'Sessões concluídas'/);
  assert.doesNotMatch(page, /label: 'Resolvidas'/);
});

test('top flows show counts and normalize bar width against the leader', () => {
  assert.match(page, /maxCount = Math\.max/);
  assert.match(page, /flow\.value \/ maxCount/);
  assert.match(page, /\{flow\.value\} conversas/);
  assert.doesNotMatch(page, /\{pct\}%/);
});

test('channels use counts for chart and the API total in the centre', () => {
  assert.match(page, /dataKey="count"/);
  assert.match(page, /channelConversationsTotal/);
  assert.match(page, /\{totalChannels\}/);
  assert.doesNotMatch(page, />Ativo<\/span>/);
});

test('null and zero remain distinct', () => {
  assert.match(page, /kpis\?\.response_rate === null \? null/);
  assert.match(page, /abandonmentRate === null \? '—'/);
  assert.match(hook, /response_rate_current \?\? kpis\.response_rate \?\? null/);
});
