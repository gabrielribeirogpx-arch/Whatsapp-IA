import assert from 'node:assert/strict';
import { readFile, readdir } from 'node:fs/promises';
import { extname, join } from 'node:path';

const root = new URL('..', import.meta.url);
const modal = await readFile(new URL('../components/ai-store/AIStoreModal.tsx', import.meta.url), 'utf8');
const card = await readFile(new URL('../components/ai-store/AIStoreCard.tsx', import.meta.url), 'utf8');
const css = await readFile(new URL('../app/globals.css', import.meta.url), 'utf8');
const forbiddenLabel = ['Minimi', 'zar'].join('');

async function applicationSources(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    if (entry.name === 'node_modules' || entry.name === 'tests' || entry.name === '.next') return [];
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return applicationSources(path);
    return ['.ts', '.tsx', '.js', '.jsx', '.css', '.html'].includes(extname(path)) ? [path] : [];
  }));
  return files.flat();
}

for (const path of await applicationSources(root.pathname)) {
  const source = await readFile(path, 'utf8');
  assert.equal(source.includes(forbiddenLabel), false, `${forbiddenLabel} must not exist in the application DOM sources: ${path}`);
}

assert.match(modal, /aria-label="Fechar Marketplace"/, 'close button has the requested accessible name');
assert.doesNotMatch(modal, /title="[^"]*"/, 'modal controls do not create native title tooltips');
assert.match(modal, /event\.key === 'Escape'\) onClose\(\)/, 'Escape closes the marketplace');
assert.match(modal, /event\.key === 'Tab'/, 'keyboard focus is trapped in the dialog');
assert.match(modal, /previous\?\.focus\(\)/, 'focus returns to the opener when the dialog unmounts');
assert.match(modal, /className="ai-store-modal-body"/, 'catalog has a dedicated scrolling region');
assert.match(card, />Visualizar e aprender</, 'details CTA remains in every card');
assert.match(card, />Instalar</, 'install CTA remains in every card');

assert.match(css, /height:min\(90dvh,860px\);max-height:calc\(100dvh - 32px\)/, 'desktop dialog uses the viewport-safe height contract');
assert.match(css, /\.ai-store-modal-body\{[^}]*min-height:0;[^}]*flex:1;[^}]*overflow-y:auto;[^}]*padding:[^}]*32px/, 'only the catalog grows and scrolls, with safe bottom padding');
assert.match(css, /\.ai-store-close-button\{position:absolute;top:16px;right:16px;width:40px;[^}]*height:40px/, 'close button is top-right with a 40px target');
assert.match(css, /repeat\(auto-fit,minmax\(230px,1fr\)\)/, 'desktop columns adapt to real card width');
assert.match(css, /@media\(max-width:1023px\)[^{]*\{[^}]*\.ai-store-grid\{grid-template-columns:repeat\(2/, 'tablet uses two columns');
assert.match(css, /@media\(max-width:600px\)[^{]*\{[^}]*[\s\S]*?\.ai-store-grid\{grid-template-columns:1fr\}/, 'mobile uses one column');

console.log('Marketplace modal accessibility and responsive layout contracts passed');
