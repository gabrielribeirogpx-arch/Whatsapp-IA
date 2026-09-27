import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const client = readFileSync(new URL('../app/dashboard/assistants/appointments/[installationId]/AppointmentConfiguratorClient.tsx', import.meta.url), 'utf8');
const api = readFileSync(new URL('../lib/api.ts', import.meta.url), 'utf8');
const helpers = readFileSync(new URL('../lib/appointment-configurator.ts', import.meta.url), 'utf8');

test('configurator uses only consolidated read, update and activation contracts', () => {
  assert.match(api, /\/configurator`/);
  assert.match(api, /\/configuration`/);
  assert.match(api, /\/activate`/);
  assert.doesNotMatch(client, /\/materialize/);
  assert.match(client, /expected_configuration_version: snapshot\.concurrency\.configuration_version/);
  assert.match(client, /expected_managed_flow_version_id: snapshot\.concurrency\.managed_flow_version_id/);
});

test('save is explicit and activation is blocked by unsaved changes', () => {
  assert.match(client, /Salvar alterações/);
  assert.match(client, /disabled=\{dirty \|\| !snapshot\.actions\.can_activate/);
  assert.doesNotMatch(client, /setInterval|debounce/);
  assert.match(client, /Esta configuração foi alterada em outra sessão/);
});

test('calendar selection is explicit, tenant options come from read model and never autosave', () => {
  assert.match(api, /available_connections: Array/);
  assert.match(client, /snapshot\.calendar\.available_connections\.map/);
  assert.match(client, /Agenda do Google/);
  assert.match(client, /getGoogleCalendarConnectUrl\(`\/dashboard\/assistants\/appointments\/\$\{installationId\}`\)/);
  assert.match(helpers, /available_connections\.length === 1/);
  assert.match(client, /setDirty\(locallyPreselected\)/);
  assert.doesNotMatch(client, /onChange=\{[^}]*updateAppointmentConfiguration/);
});

test('configured calendar wins over local single-option preselection', () => {
  const precedence = helpers.indexOf('snapshot.calendar.connection_id\n    ||');
  const single = helpers.indexOf('snapshot.calendar.available_connections.length === 1');
  assert.ok(precedence >= 0 && precedence < single);
});

test('service identity is retained while labels are edited', () => {
  assert.match(client, /\{ \.\.\.item, label: e\.target\.value \}/);
  assert.match(client, /serviceId\('Novo serviço', form\.services\)/);
  assert.match(helpers, /replace\(\/\[\^a-z0-9\]\+\/g, '_'/);
  assert.match(client, /disabled=\{readOnly \|\| form\.services\.length === 1\}/);
});

test('permissions come exclusively from backend actions', () => {
  assert.match(client, /!snapshot\.actions\.can_edit/);
  assert.match(client, /snapshot\.actions\.can_activate/);
  assert.match(client, /snapshot\.actions\.can_open_builder/);
  assert.doesNotMatch(client, /role\s*===|role\s*!==/);
});

test('replacement requires an explicit accessible confirmation', () => {
  assert.match(client, /assistant_activation_would_replace_active_flow/);
  assert.match(client, /confirm_replace_active_flow: confirmed/);
  assert.match(client, /role="dialog" aria-modal="true"/);
  assert.match(client, /Ativar mesmo assim/);
});
