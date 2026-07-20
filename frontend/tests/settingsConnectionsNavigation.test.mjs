import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const pageClient = readFileSync(new URL('../components/settings/SettingsPageClient.tsx', import.meta.url), 'utf8');
const settingsContent = readFileSync(new URL('../components/settings/SettingsContent.tsx', import.meta.url), 'utf8');
const onboarding = readFileSync(new URL('../components/onboarding/OnboardingProvider.tsx', import.meta.url), 'utf8');
const academy = readFileSync(new URL('../app/dashboard/academy/page.tsx', import.meta.url), 'utf8');

assert.match(onboarding, /href: '\/dashboard\/settings\?tab=whatsapp-business&section=connections'/);
assert.match(pageClient, /const whatsappSections = \['overview', 'connections', 'templates', 'api-keys', 'webhooks'\]/);
assert.match(pageClient, /requestedSection = searchParams\.get\('section'\)/);
assert.match(pageClient, /nextParams\.set\('section', section\)/);
assert.match(settingsContent, /connections: "connection"/);
assert.match(settingsContent, /connection: "connections"/);
assert.match(settingsContent, /role="tablist"/);
assert.doesNotMatch(onboarding, /onClick=\{\(\) => complete\(next\.id\)\}/);
assert.match(academy, /if\(step\.id!==['"]whatsapp['"]\)complete\(step\.id\)/);
