import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('./api.ts', import.meta.url), 'utf8');
const fn = source.match(/export function getGmailConnectUrl\(\): string \{[\s\S]*?\n\}/)?.[0] || '';

assert.match(fn, /\/api\/integrations\/gmail\/connect-url\?tenant_slug=/);
assert.doesNotMatch(fn, /getGoogleCalendarConnectUrl/);
assert.doesNotMatch(fn, /google-calendar\/connect/);
