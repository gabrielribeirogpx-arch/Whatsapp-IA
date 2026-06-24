import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const source = readFileSync(new URL("./api.ts", import.meta.url), "utf8");
const settingsSource = readFileSync(
  new URL("../components/settings/SettingsContent.tsx", import.meta.url),
  "utf8",
);
const mcpDashboardSource = readFileSync(
  new URL("../app/dashboard/ai/mcp/MCPDashboardClient.tsx", import.meta.url),
  "utf8",
);
const featuresSource = readFileSync(
  new URL("./features.ts", import.meta.url),
  "utf8",
);

const connectFn =
  source.match(
    /export function getGoogleSheetsConnectUrl\(\): string \{[\s\S]*?\n\}/,
  )?.[0] || "";
const statusFn =
  source.match(
    /export async function getGoogleSheetsStatus\(\): Promise<GoogleCalendarConnectionStatus> \{[\s\S]*?\n\}/,
  )?.[0] || "";
const disconnectFn =
  source.match(
    /export async function disconnectGoogleSheets\(\): Promise<GoogleCalendarConnectionStatus> \{[\s\S]*?\n\}/,
  )?.[0] || "";

assert.match(
  connectFn,
  /\/api\/integrations\/google-sheets\/connect-url\?tenant_slug=/,
);
assert.match(statusFn, /\/api\/integrations\/google-sheets\/status/);
assert.match(disconnectFn, /\/api\/integrations\/google-sheets\/disconnect/);
assert.match(disconnectFn, /method: ["']POST["']/);

assert.match(featuresSource, /ENABLE_GOOGLE_SHEETS_INTEGRATION = true/);
assert.match(settingsSource, /Apps conectados ao Wazza/);
assert.match(settingsSource, /ENABLE_GOOGLE_SHEETS_INTEGRATION \? \(/);
assert.match(settingsSource, /<h4[^>]*>[\s\S]*?Google Sheets[\s\S]*?<\/h4>/);
assert.match(
  settingsSource,
  /Permita que a IA liste, leia, crie e atualize planilhas\./,
);
assert.match(settingsSource, /Conectar Google Sheets/);
assert.match(settingsSource, /Desconectar/);
assert.match(settingsSource, /Atualizar status/);
assert.match(settingsSource, /google_sheets_list_spreadsheets/);
assert.match(settingsSource, /google_sheets_read_sheet/);
assert.match(settingsSource, /google_sheets_append_row/);
assert.match(settingsSource, /google_sheets_update_row/);
assert.match(settingsSource, /google_sheets_create_spreadsheet/);

assert.match(mcpDashboardSource, /Apps conectados ao Wazza/);
assert.match(mcpDashboardSource, /ENABLE_GOOGLE_SHEETS_INTEGRATION \? \(/);
assert.match(
  mcpDashboardSource,
  /<h3[^>]*>[\s\S]*?Google Sheets[\s\S]*?<\/h3>/,
);
assert.match(mcpDashboardSource, /getGoogleSheetsStatus/);
assert.match(mcpDashboardSource, /getGoogleSheetsConnectUrl/);
assert.match(mcpDashboardSource, /disconnectGoogleSheets/);
assert.match(
  mcpDashboardSource,
  /metadata\?\.provider === ["']google_sheets["']/,
);
assert.match(mcpDashboardSource, /integration === ["']google_sheets["']/);
assert.match(mcpDashboardSource, /getPresentationTools/);
assert.match(mcpDashboardSource, /isGoogleSheetsTool/);
assert.match(mcpDashboardSource, /!isGoogleSheetsTool\(tool\)/);
assert.match(mcpDashboardSource, /presentationTools\.filter/);
assert.doesNotMatch(
  mcpDashboardSource,
  /!\["google_calendar", "gmail", "google_drive", "google_sheets", "suitable"\]/,
);
