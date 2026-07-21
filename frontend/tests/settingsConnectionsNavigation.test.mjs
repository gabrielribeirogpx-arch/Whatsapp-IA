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
assert.match(onboarding, /currentStep: number/);
assert.match(onboarding, /missionStatus: Record<string, MissionStatus>/);
assert.match(onboarding, /missionStatus: \{ \.\.\.old\.missionStatus, \[id\]:[^}]*'active'/);
assert.match(onboarding, /currentStep: stepIndex >= 0 \? Math\.min\(stepIndex \+ 1/);
assert.match(onboarding, /listWhatsAppProviders/);
assert.match(onboarding, /provider\.is_active \|\|[\s\S]*provider\.connection_status === 'connected'/);
assert.match(onboarding, /complete\('whatsapp'\)/);
assert.match(onboarding, /wazza:whatsapp-connection-changed/);
assert.match(settingsContent, /window\.dispatchEvent\(new Event\("wazza:whatsapp-connection-changed"\)\)/);
assert.match(academy, /const \{state,complete,activate,progress,reset,startTour\}=useOnboarding\(\)/);
assert.match(academy, /isActive\?<small>Em andamento<\/small>:null/);
assert.match(academy, /if\(step\.id==='whatsapp'\)activate\(step\.id\)/);
