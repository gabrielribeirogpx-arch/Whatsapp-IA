import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const adapter = readFileSync(new URL('../components/ai-store/dynamicCatalog.ts', import.meta.url), 'utf8');
const builder = readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const api = readFileSync(new URL('../lib/api.ts', import.meta.url), 'utf8');

test('dynamic catalog has a typed adapter and deterministic identity merge', () => {
  assert.match(api, /Promise<MarketplaceCatalogItem\[\]>/);
  assert.match(adapter, /item\.source === 'official' && item\.status === 'published'/);
  assert.match(adapter, /\[item\.key, item\.slug\]/);
  assert.doesNotMatch(adapter, /Clinicas - Agenda Automática/);
});

test('marketplace remains usable while dynamic loading fails', () => {
  assert.match(builder, /mergeMarketplaceCatalog\(MARKETPLACE_CATALOG, dynamicCatalog\)/);
  assert.match(builder, /setCatalogLoadFailed\(true\)/);
  assert.doesNotMatch(builder, /setDynamicCatalog\(\[\]\).*catch/s);
});

test('official install sends the selected catalog version and follows backend route', () => {
  assert.match(builder, /installOfficialMarketplaceTemplate\(marketplaceCard\.slug, marketplaceCard\.templateVersionId\)/);
  assert.match(builder, /router\.push\(installed\.post_install_route\)/);
  assert.match(builder, /onPublished=.*refreshMarketplaceCatalog/s);
});
