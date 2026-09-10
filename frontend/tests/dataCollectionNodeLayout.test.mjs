import assert from 'node:assert/strict';
import fs from 'node:fs';

const node = fs.readFileSync(new URL('../components/flow/nodes/DataCollectionNode.tsx', import.meta.url), 'utf8');
const editor = fs.readFileSync(new URL('../app/dashboard/flow-builder/FlowBuilderClient.tsx', import.meta.url), 'utf8');
const types = fs.readFileSync(new URL('../lib/dataCollectionTypes.ts', import.meta.url), 'utf8');
const css = fs.readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');

function declarationsFor(selector) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = css.match(new RegExp(`${escapedSelector}\\s*\\{([^}]+)\\}`));
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

const sharedScrollArea = declarationsFor('.flow-node-editor-content');
const dataCollectionEditor = declarationsFor('.data-collection-editor');

assert.match(node, /variableName \|\| 'Variável não definida'/);
assert.ok(!node.includes('summary={`{{'), 'must not format the variable as a technical placeholder');
assert.match(types, /value: 'choice', label: 'Escolha'/);
assert.match(node, /DATA_COLLECTION_HANDLES\.map\(\(id\)/, 'React Flow handles must be derived from the canonical contract');
assert.ok(!node.includes("const CANONICAL_HANDLE_IDS"), 'the renderer must not maintain a second handle list');
assert.match(node, /selected=\{selected\}/);
assert.match(node, /hasValidationError=\{nodeData\.hasValidationError\}/);
assert.match(node, /structuralSignature/);
assert.match(node, /updateNodeInternals\(id\)/);
assert.match(node, /choiceLayout/);
assert.match(css, /text-overflow: ellipsis/);
assert.match(editor, /1\. Variável[\s\S]*2\. Tipo de dado[\s\S]*3\. Validação[\s\S]*4\. Tentativas e timeout[\s\S]*5\. Persistência[\s\S]*6\. Saídas/);

assert.match(editor, /<div className="flow-node-editor-content">[\s\S]*?kind === 'data_collection'[\s\S]*?<div className="data-collection-editor">/, 'Data Collection renders inside the shared scroll area');
assert.equal(sharedScrollArea['overflow-y'], 'auto', 'the sidebar owns vertical scrolling');
assert.equal(dataCollectionEditor.width, '100%', 'the editor fills the shared scroll area');
assert.equal(dataCollectionEditor['max-width'], '100%', 'the editor cannot widen the sidebar');
assert.equal(dataCollectionEditor['min-width'], '0', 'the editor can shrink as a grid child');
assert.equal(dataCollectionEditor['min-height'], '0', 'the editor does not impose an intrinsic minimum height');
assert.equal(dataCollectionEditor['overflow-x'], 'hidden', 'horizontal overflow remains clipped');
assert.equal(dataCollectionEditor['overflow-y'], 'visible', 'the inner wrapper does not clip or own vertical scrolling');
assert.equal(dataCollectionEditor.overflow, undefined, 'the inner wrapper does not use an overflow shorthand that can block the Y axis');
assert.doesNotMatch(editor, /data-collection-editor"[^>]*onWheel=/, 'Data Collection does not intercept mouse-wheel events');
assert.match(editor, /<div className="data-collection-editor">[\s\S]*?<h4>6\. Saídas<\/h4>[\s\S]*?<\/div>/, 'the complete long form, including its last section, remains in the shared scroll flow');
assert.match(editor, /\(kind === 'choice' \|\| kind === 'choice_dynamic'\)[\s\S]*?flow-editor-choice-dynamic/, 'Choice continues to use the shared editor structure');
assert.match(editor, /kind === 'mcp_tool' \? <MCPToolEditor[^>]+\/>/, 'MCP Tool continues to render in the shared editor structure');

console.log('Data collection node layout regression checks passed.');
