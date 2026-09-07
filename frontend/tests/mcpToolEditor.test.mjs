import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const editor = readFileSync(new URL('../components/flow/MCPToolEditor.tsx', import.meta.url), 'utf8');

assert.doesNotMatch(editor, /href="\/dashboard\/integrations"/);
assert.match(editor, /href="\/dashboard\/ai\/mcp" target="_blank">Conectar integração/);
assert.match(editor, /Object\.entries\(schema\.properties \|\| \{\}\)/);
assert.doesNotMatch(editor, /google_calendar/i);
