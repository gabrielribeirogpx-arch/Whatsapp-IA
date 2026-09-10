import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const editor = readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

function declarationsFor(selector) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = styles.match(new RegExp(`${escapedSelector}\\s*\\{([^}]+)\\}`));
  assert.ok(match, `missing CSS rule for ${selector}`);
  return Object.fromEntries(
    match[1]
      .split(';')
      .map((declaration) => declaration.trim())
      .filter(Boolean)
      .map((declaration) => {
        const separator = declaration.indexOf(':');
        return [declaration.slice(0, separator).trim(), declaration.slice(separator + 1).trim()];
      }),
  );
}

const panel = declarationsFor('.flow-node-editor-panel');
const header = declarationsFor('.flow-node-editor-header');
const content = declarationsFor('.flow-node-editor-content');

assert.equal(panel.display, 'flex', 'the editor sidebar establishes a flex layout');
assert.equal(panel['flex-direction'], 'column', 'the editor sidebar stacks its fixed header and scroll area');
assert.equal(panel.height, '100%', 'the editor sidebar remains viewport-bound');
assert.equal(panel.width, '420px', 'the editor sidebar retains its fixed desktop width');
assert.equal(panel.overflow, 'hidden', 'the editor sidebar clips horizontal spill instead of exposing a scrollbar');
assert.equal(header.flex, '0 0 auto', 'the header does not consume the scroll area height');
assert.equal(content.flex, '1 1 auto', 'the shared content wrapper receives the remaining sidebar height');
assert.equal(content['min-height'], '0', 'the flex child can shrink below its intrinsic content height');
assert.equal(content['overflow-x'], 'hidden', 'horizontal overflow stays hidden');
assert.equal(content['overflow-y'], 'auto', 'short forms do not force a scrollbar and long forms scroll natively');
assert.equal(content['overscroll-behavior-y'], 'contain', 'wheel scrolling remains contained in the sidebar');

assert.match(editor, /<aside className="flow-node-editor-panel">[\s\S]*?<div className="flow-node-editor-content">/, 'every node editor uses the shared scroll area');
assert.doesNotMatch(editor, /flow-node-editor-(?:panel|content)"[^>]*onWheel=/, 'native wheel scrolling is not intercepted');
assert.match(editor, /draft\.options_mode === 'dynamic' \? <div className="flow-editor-repeatable flow-editor-choice-dynamic"/, 'dynamic Choice remains in its width-constrained wrapper');
assert.match(editor, /: <div className="flow-editor-repeatable">[\s\S]*?Opções \{displayMode/, 'fixed Choice remains in the same shared scroll area');

console.log('flow node editor vertical scroll regression: ok');
