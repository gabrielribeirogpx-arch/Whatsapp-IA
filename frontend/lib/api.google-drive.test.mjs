import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('./api.ts', import.meta.url), 'utf8');

const connectFn = source.match(/export function getGoogleDriveConnectUrl\(\): string \{[\s\S]*?\n\}/)?.[0] || '';
const statusFn = source.match(/export async function getGoogleDriveStatus\(\): Promise<GoogleCalendarConnectionStatus> \{[\s\S]*?\n\}/)?.[0] || '';
const disconnectFn = source.match(/export async function disconnectGoogleDrive\(\): Promise<GoogleCalendarConnectionStatus> \{[\s\S]*?\n\}/)?.[0] || '';

assert.match(connectFn, /\/api\/integrations\/google-drive\/connect-url\?tenant_slug=/);
assert.doesNotMatch(connectFn, /google_drive\/connect-url/);
assert.doesNotMatch(connectFn, /google-calendar/);
assert.match(statusFn, /\/api\/integrations\/google-drive\/status/);
assert.match(disconnectFn, /\/api\/integrations\/google-drive\/disconnect/);
assert.match(disconnectFn, /method: ["']POST["']/);
