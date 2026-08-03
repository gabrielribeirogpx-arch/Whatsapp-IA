import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const component = readFileSync(new URL('../components/InteractiveMessageBubble.tsx', import.meta.url), 'utf8');
const bubble = readFileSync(new URL('../components/MessageBubble.tsx', import.meta.url), 'utf8');
const sidebar = readFileSync(new URL('../components/Sidebar.tsx', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

assert.match(component, /button_reply: \{ icon: '🤖', label: 'Resposta interativa' \}/, 'identifies button replies');
assert.match(component, /list_reply: \{ icon: '📋', label: 'Resposta da lista' \}/, 'identifies list replies');
assert.match(component, /interactive: \{ icon: '🖱️', label: 'Resposta interativa' \}/, 'supports generic interactive messages');
assert.match(component, /<details className="wa-interactive-message-details">/, 'keeps technical data collapsed natively');
assert.match(component, /developerMode && technicalFields\.length > 0/, 'hides technical data unless developer mode is active');
assert.match(component, /<summary>🔧 Detalhes técnicos<\/summary>/, 'labels the affordance for developers');
assert.doesNotMatch(component, /Ver detalhes|Payload interno/, 'does not expose the old operator-facing details copy');
assert.match(component, /\['Flow', details\.flow\]/, 'supports optional flow metadata');
assert.match(component, /\['Node', details\.node\]/, 'supports optional node metadata');
assert.match(bubble, /interactiveType \|\| message\.technicalPayload/, 'recognizes current and legacy interactive messages');
assert.match(bubble, /title=\{visibleText\}/, 'preserves the existing title fallback');
assert.match(sidebar, /variant="preview"/, 'reuses the interactive component in conversation history');
assert.match(sidebar, /title=\{contact\.lastMessage \|\| contact\.lastMessagePayload/, 'never promotes payload over a known title');
assert.match(sidebar, /contact\.lastMessageFromMe \? '🤖' : '⌨️'/, 'labels automatic and regular text previews');
assert.match(styles, /\.wa-message-bubble:has\(\.wa-interactive-message\)[\s\S]*?border:/, 'adds the distinct WhatsApp-like bubble border');
assert.match(styles, /min-width: min\(290px, 78vw\)/, 'keeps the interactive bubble responsive');

console.log('Interactive message presentation contract passed');
