import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const editor = readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

assert.match(editor, /draft\.options_mode === 'dynamic' \? <div className="flow-editor-repeatable flow-editor-choice-dynamic"/, 'dynamic Choice renders in its constrained layout wrapper');
assert.match(editor, /: <div className="flow-editor-repeatable">[\s\S]*?Opções \{displayMode/, 'fixed Choice keeps rendering through its existing editor');

assert.match(styles, /\.flow-node-editor-panel \{[\s\S]*?width: 420px;[\s\S]*?max-width: min\(420px, 100vw\);[\s\S]*?min-width: 0;[\s\S]*?overflow: hidden;/, 'the sidebar remains fixed and clips horizontal overflow');
assert.match(styles, /\.flow-node-editor-content \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0;[\s\S]*?overflow-x: hidden;[\s\S]*?overflow-y: auto;/, 'editor content only scrolls vertically');
assert.match(styles, /\.flow-editor-field,[\s\S]*?\.flow-editor-repeatable \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0;/, 'editor grid wrappers cannot exceed the sidebar');
assert.match(styles, /\.flow-editor-field input,[\s\S]*?\.flow-editor-field textarea,[\s\S]*?\.flow-editor-row input \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0;[\s\S]*?box-sizing: border-box;/, 'dynamic text controls fit their available width');
assert.match(styles, /\.flow-editor-field select,[\s\S]*?\.flow-editor-row select \{[\s\S]*?width: 100%;[\s\S]*?max-width: 100%;[\s\S]*?min-width: 0;[\s\S]*?box-sizing: border-box;/, 'dynamic selects fit their available width');
assert.match(styles, /grid-template-columns: minmax\(0, 1fr\) auto;/, 'grid children may shrink instead of imposing their intrinsic width');
assert.match(styles, /\.flow-editor-choice-dynamic pre \{[\s\S]*?white-space: pre-wrap;/, 'long dynamic preview content wraps without being hidden');
assert.match(styles, /@media \(max-width: 900px\) \{[\s\S]*?\.flow-node-editor-panel \{[\s\S]*?width: min\(420px, 100vw\);[\s\S]*?height: 100%;/, 'responsive sidebar remains viewport-bound');

console.log('dynamic choice layout regression: ok');
