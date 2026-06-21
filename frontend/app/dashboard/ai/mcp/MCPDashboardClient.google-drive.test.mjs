import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';

const source = readFileSync(new URL('./MCPDashboardClient.tsx', import.meta.url), 'utf8');

assert.match(source, /<h3 className="font-bold text-slate-950">Google Drive<\/h3>/);
assert.match(source, /driveStatus\?\.provider \|\| "google_drive"/);
assert.match(source, /Conectar Google Drive/);
assert.match(source, /Desconectar/);
assert.match(source, /Atualizar status/);
assert.match(source.replace(/\s+/g, ' '), /Permita que a IA liste, busque, leia e crie arquivos\/documentos no Drive\./);
for (const tool of [
  'google_drive_list_files',
  'google_drive_search_files',
  'google_drive_read_file',
  'google_drive_create_document',
  'google_drive_create_folder',
]) {
  assert.match(source, new RegExp(tool));
}
