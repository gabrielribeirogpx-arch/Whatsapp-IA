import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../components/layout/ResponsiveDataView.tsx', import.meta.url), 'utf8');

assert.match(source, /matchMedia\('\(max-width: 1023px\)'\)/, 'uses the AppShell compact breakpoint');
assert.match(source, /if \(loading\)/, 'handles loading before rendering either view');
assert.match(source, /if \(error\)/, 'handles errors before rendering either view');
assert.match(source, /isCompact \? <div className="responsive-data-mobile">\{data\.map\(mobileView\)\}<\/div> : desktopView/, 'selects a single view from shared data');

console.log('ResponsiveDataView contract passed');
