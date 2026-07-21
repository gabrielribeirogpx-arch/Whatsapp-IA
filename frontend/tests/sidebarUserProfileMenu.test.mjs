import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const profile = readFileSync(new URL('../components/SidebarUserProfile.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

assert.match(profile, /onClick=\{handleTriggerClick\}/);
assert.match(profile, /setOpen\(\(current\) => !current\)/);
assert.match(profile, /createPortal\(/);
assert.match(profile, /document\.body/);
assert.match(profile, /event\.key === "Escape"/);
assert.match(profile, /firstMenuItemRef\.current\?\.focus\(\)/);
assert.match(profile, /aria-controls=\{open \? menuId : undefined\}/);
assert.match(styles, /\.sidebar-account-backdrop \{[\s\S]*?pointer-events: none;/);
assert.match(styles, /\.sidebar-account-backdrop\.is-mobile \{[\s\S]*?pointer-events: auto;/);
