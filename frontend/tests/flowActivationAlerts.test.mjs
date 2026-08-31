import assert from 'node:assert/strict';
import fs from 'node:fs';

const builder = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

assert.match(builder, /createPortal\([\s\S]*document\.body/, 'alerts use the unclipped global portal');
assert.match(builder, /flowHeaderRef[\s\S]*getBoundingClientRect\(\)\.bottom \+ 12/, 'alert offset tracks the real responsive header height');
assert.match(builder, /ResizeObserver/, 'header wrapping updates the alert offset');
assert.match(builder, /role="alert" aria-live="assertive"/, 'activation errors are announced');
assert.match(builder, /validationErrors\.map/, 'all errors remain present and vertically stackable');
assert.match(builder, /aria-label="Fechar alertas"/, 'alerts can be dismissed');
assert.match(css, /\.flow-activation-alerts\s*\{[\s\S]*position: fixed;[\s\S]*flex-direction: column;[\s\S]*gap: 10px;/, 'global alert stack is fixed and spaced');
assert.match(css, /width: min\(440px, calc\(100vw - 48px\)\)/, 'desktop alerts respect viewport margins');
assert.match(css, /@media \(max-width: 900px\)[\s\S]*\.flow-activation-alerts \{ right: 12px; width: calc\(100vw - 24px\); \}/, 'mobile alerts use available width');
assert.doesNotMatch(css.match(/\.flow-activation-alerts\s*\{[\s\S]*?\}/)?.[0] || '', /overflow:\s*hidden/, 'alert stack is never clipped');

console.log('flow activation alert regression: ok');
