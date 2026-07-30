import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const builder = readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

assert.match(builder, /className="dash-sidebar-scroll-area flow-builder-sidebar-scroll-area"/);
assert.match(builder, /dash-sidebar-logo[\s\S]*dash-sidebar-scroll-area flow-builder-sidebar-scroll-area/);
assert.match(styles, /\.flow-builder-page \.flow-builder-sidebar \{[\s\S]*?height: 100vh;[\s\S]*?overflow: hidden;/);
assert.match(styles, /\.dash-sidebar-scroll-area \{[\s\S]*?overflow-y: auto;[\s\S]*?scrollbar-width: none;[\s\S]*?-ms-overflow-style: none;/);
assert.match(styles, /\.dash-sidebar-scroll-area::\-webkit-scrollbar \{[\s\S]*?display: none;/);
assert.match(styles, /\.flow-builder-sidebar-scroll-area \{[\s\S]*?scroll-behavior: smooth;[\s\S]*?-webkit-overflow-scrolling: touch;/);
