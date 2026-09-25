import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const hook = readFileSync(new URL('../hooks/useDashboardAnalytics.ts', import.meta.url), 'utf8');
const page = readFileSync(new URL('../app/dashboard/page.tsx', import.meta.url), 'utf8');

test('zero-valued dashboard metrics use nullish rather than truthy fallbacks', () => {
  assert.match(hook, /messages_today: Number\(kpis\.messages_today \?\?/);
  assert.match(page, /messagesToday: Number\(\(kpis as any\)\?\.messages_today \?\?/);
});

test('message card uses the backend delta and renders null as unavailable', () => {
  assert.match(page, /item\.key === 'messagesToday'.*messages_delta/);
  assert.match(page, /typeof delta === 'number'.*'—'/);
  assert.doesNotMatch(page, /function getDeltaPercent/);
});

test('message card keeps the selected-range total and label', () => {
  assert.match(page, /label: 'Mensagens'/);
  assert.match(hook, /messages_sent_current/);
  assert.match(hook, /messages_received_current/);
});

test('preset and custom query parameters remain supported', () => {
  assert.match(hook, /period: period\.preset/);
  assert.match(hook, /start_date: period\.startDate, end_date: period\.endDate/);
});
