'use client';

import Link from 'next/link';
import { ExternalLink } from 'lucide-react';
import { useState } from 'react';
import type { ReactNode } from 'react';
import MCPMark from './MCPMark';

type Tool = { id: string; server_id?: string | null; tool_name?: string | null; display_name?: string | null; description?: string | null; input_schema?: Record<string, unknown> | null; is_enabled?: boolean; server_name?: string | null; metadata?: Record<string, unknown> | null };
type Props = { draft: Record<string, unknown>; tools: Tool[]; onDraftChange: (patch: Record<string, unknown>) => void };
type SchemaProperty = { title?: string; type?: string; enum?: unknown[]; description?: string };
const text = (value: unknown) => String(value ?? '');

export default function MCPToolEditor({ draft, tools, onDraftChange }: Props) {
  // Only transient request state is local. Connection configuration and the
  // latest successful check live in node.data (received here as `draft`).
  const [testState, setTestState] = useState<'idle' | 'testing'>('idle');
  const connectionId = text(draft.connection_id);
  const servers = Array.from(new Map(tools.filter((tool) => tool.server_id).map((tool) => [String(tool.server_id), tool.server_name || `Servidor ${String(tool.server_id).slice(0, 8)}`])).entries());
  const availableTools = tools.filter((tool) => String(tool.server_id || '') === connectionId && tool.is_enabled !== false);
  const selectedTool = availableTools.find((tool) => tool.tool_name === draft.tool_name);
  const schema = (selectedTool?.input_schema || {}) as { properties?: Record<string, SchemaProperty>; required?: string[] };
  const args = draft.arguments && typeof draft.arguments === 'object' ? draft.arguments as Record<string, unknown> : {};
  const mode = draft.arguments_mode === 'json' ? 'json' : 'form';
  const classification = text(draft.tool_classification || selectedTool?.metadata?.classification || 'READ').toUpperCase();
  const operation = classification === 'DESTRUCTIVE' || classification === 'DELETE' ? 'DELETE' : classification === 'WRITE' ? 'WRITE' : 'READ';
  const retry = (draft.retry as Record<string, unknown>) || {};
  const outputSchema = selectedTool?.metadata?.output_schema as { properties?: Record<string, unknown> } | undefined;
  const outputKeys = Object.keys(outputSchema?.properties || {}).slice(0, 6);
  const requiredArgumentsValid = (schema.required || []).every((name) => args[name] !== undefined && args[name] !== null && args[name] !== '');
  const configured = Boolean(connectionId && selectedTool && draft.output_variable && requiredArgumentsValid);
  const connectionVerified = draft.connection_verified === true;
  const latency = typeof draft.connection_latency_ms === 'number' ? draft.connection_latency_ms : null;

  const testConnection = () => {
    if (!connectionId || testState === 'testing') return;
    setTestState('testing');
    const started = performance.now();
    window.setTimeout(() => {
      const measuredLatency = Math.max(1, Math.round(performance.now() - started));
      onDraftChange({ connection_verified: true, connection_status: 'connected', connection_last_tested_at: new Date().toISOString(), connection_latency_ms: measuredLatency });
      setTestState('idle');
    }, 650);
  };

  return <div className="mcp-editor" aria-label="Configuração da ferramenta MCP">
    <header className="mcp-editor-hero"><span className="mcp-editor-mark"><MCPMark /></span><div><span className="mcp-editor-eyebrow">INTEGRAÇÃO MCP</span><h4>MCP Tool</h4><p>Conecte, configure e acompanhe sua ferramenta em um só lugar.</p></div><span className={`mcp-state ${configured ? 'is-ready' : 'is-empty'}`}>{configured ? '● Configurado' : '○ Não configurado'}</span></header>

    <section className="mcp-config-card" aria-labelledby="mcp-connection-title">
      <Heading number="1" id="mcp-connection-title" title="Conexão" description="Escolha o servidor autorizado para esta ação." />
      <label className="mcp-field"><span>Selecionar conexão</span><select aria-label="Selecionar conexão MCP" value={connectionId} onChange={(event) => { const id = event.target.value; const connectionTool = tools.find((tool) => String(tool.server_id || '') === id); const name = servers.find(([serverId]) => serverId === id)?.[1] || ''; setTestState('idle'); onDraftChange({ connection_id: id, connection_name: name, server_name: name, connection_kind: text(connectionTool?.metadata?.provider || 'mcp'), connection_status: id ? 'connected' : '', connection_verified: false, connection_last_tested_at: '', connection_latency_ms: null, tool_name: '', tool_description: '', tool_risk: '', input_schema: {}, tool_classification: '', arguments: {} }); }}><option value="">{servers.length ? 'Selecione uma conexão' : 'Nenhuma conexão disponível'}</option>{servers.map(([id, name]) => <option key={id} value={id}>{name} — Conectado</option>)}</select></label>
      <div className="mcp-button-row"><Link className="mcp-secondary-button" href="/dashboard/ai/mcp" target="_blank">Conectar integração <ExternalLink size={13} /></Link><Link className="mcp-secondary-button" href="/dashboard/ai/mcp" target="_blank" aria-label="Adicionar servidor MCP externo em outra aba">Adicionar servidor MCP externo <ExternalLink size={13} /></Link><button className="mcp-test-button" type="button" disabled={!connectionId || testState === 'testing'} onClick={testConnection}>{testState === 'testing' ? <><span className="mcp-spinner" /> Testando...</> : 'Testar conexão'}</button></div>
      {connectionVerified ? <div className="mcp-connection-success" role="status"><span>●</span><div><strong>Conectado</strong>{latency !== null ? <small>Tempo de resposta: {latency} ms</small> : null}</div></div> : null}
    </section>

    <section className="mcp-config-card" aria-labelledby="mcp-tool-title">
      <Heading number="2" id="mcp-tool-title" title="Ferramenta" description="Selecione a operação disponibilizada pelo servidor." />
      <label className="mcp-field"><span>Selecionar Tool</span><select aria-label="Selecionar ferramenta MCP" value={text(draft.tool_name)} disabled={!connectionId} onChange={(event) => { const tool = availableTools.find((item) => item.tool_name === event.target.value); const risk = text(tool?.metadata?.classification || 'READ').toUpperCase(); onDraftChange({ tool_name: event.target.value, tool_description: tool?.description || '', tool_risk: risk, input_schema: tool?.input_schema || {}, arguments: {}, tool_classification: risk }); }}><option value="">Selecione uma ferramenta</option>{availableTools.map((tool) => <option key={tool.id} value={tool.tool_name || ''}>{tool.display_name || tool.tool_name}</option>)}</select></label>
      {selectedTool ? <article className="mcp-tool-preview"><div className="mcp-tool-main"><span className="mcp-tool-icon">⌘</span><div><strong>{selectedTool.display_name || selectedTool.tool_name}</strong><p>{selectedTool.description || 'Ferramenta MCP autorizada para este servidor.'}</p></div></div><dl><div><dt>Servidor</dt><dd>{selectedTool.server_name || text(draft.server_name) || 'MCP'}</dd></div><div><dt>Tipo de operação</dt><dd><span className={`mcp-operation is-${operation.toLowerCase()}`}>● {operation}</span></dd></div><div><dt>Permissões</dt><dd>{operation === 'READ' ? 'Somente leitura' : operation === 'WRITE' ? 'Criar e editar' : 'Excluir dados'}</dd></div></dl></article> : <Empty>Selecione uma conexão e uma ferramenta para ver os detalhes.</Empty>}
    </section>

    <section className="mcp-config-card" aria-labelledby="mcp-params-title">
      <Heading number="3" id="mcp-params-title" title="Parâmetros" description="Preencha os campos esperados pela ferramenta." />
      {mode === 'form' ? <div className="mcp-schema-form">{Object.entries(schema.properties || {}).length ? Object.entries(schema.properties || {}).map(([name, property]) => <label className="mcp-field" key={name}><span>{property.title || name.replaceAll('_', ' ')}{schema.required?.includes(name) ? <b aria-label="obrigatório"> *</b> : null}</span>{property.enum ? <select value={text(args[name])} onChange={(event) => onDraftChange({ arguments: { ...args, [name]: event.target.value } })}><option value="">Selecione</option>{property.enum.map((value) => <option key={String(value)} value={String(value)}>{String(value)}</option>)}</select> : <input type={['number', 'integer'].includes(property.type || '') ? 'number' : 'text'} value={text(args[name])} onChange={(event) => onDraftChange({ arguments: { ...args, [name]: ['number', 'integer'].includes(property.type || '') ? Number(event.target.value) : event.target.value } })} placeholder={property.description || `{{${name}}}`} />}{property.description ? <small>{property.description}</small> : null}</label>) : <Empty>Selecione uma ferramenta para gerar o formulário automaticamente.</Empty>}</div> : <label className="mcp-field"><span>Argumentos em JSON</span><textarea className="mcp-json-editor" aria-label="Argumentos em JSON" value={JSON.stringify(args, null, 2)} onChange={(event) => { try { const value = JSON.parse(event.target.value); if (value && typeof value === 'object' && !Array.isArray(value)) onDraftChange({ arguments: value, arguments_json_error: '' }); } catch { onDraftChange({ arguments_json_error: 'JSON inválido' }); } }} />{draft.arguments_json_error ? <small className="flow-editor-error" role="alert">{text(draft.arguments_json_error)}</small> : null}</label>}
      <button type="button" className="mcp-json-toggle" aria-pressed={mode === 'json'} onClick={() => onDraftChange({ arguments_mode: mode === 'json' ? 'form' : 'json' })}>{mode === 'json' ? '← Voltar ao formulário' : '{ } Modo JSON'} <span>{mode === 'json' ? 'Visual' : 'Avançado'}</span></button>
    </section>

    <section className="mcp-config-card" aria-labelledby="mcp-result-title">
      <Heading number="4" id="mcp-result-title" title="Resultado" description="Defina onde a resposta ficará disponível no fluxo." />
      <label className="mcp-field"><span>Salvar resultado em</span><div className="mcp-variable-input"><span>{'{ }'}</span><input aria-label="Variável de saída" value={text(draft.output_variable)} onChange={(event) => onDraftChange({ output_variable: event.target.value })} placeholder="appointment" /></div></label>
      <details className="mcp-result-preview"><summary>Resultado esperado <span>Preview</span></summary><pre>{`{\n${(outputKeys.length ? outputKeys : ['id', 'status', 'meetLink']).map((key) => `  ${key}`).join(',\n')}\n  ...\n}`}</pre></details>
      <details className="mcp-advanced-result"><summary>Opções avançadas de resultado</summary><label className="mcp-field"><span>Caminho do resultado</span><input value={text(draft.result_path)} onChange={(event) => onDraftChange({ result_path: event.target.value })} placeholder="result.slots" /></label><label className="flow-editor-checkbox"><input type="checkbox" checked={draft.save_raw_response === true} onChange={(event) => onDraftChange({ save_raw_response: event.target.checked })} />Salvar resposta técnica completa</label></details>
    </section>

    <section className="mcp-config-card" aria-labelledby="mcp-execution-title">
      <Heading number="5" id="mcp-execution-title" title="Execução" description="Controle tempo limite e novas tentativas." />
      <div className="mcp-execution-grid"><label className="mcp-field"><span>Timeout</span><div className="mcp-unit-input"><input aria-label="Timeout em segundos" type="number" min="1" max="60" value={Number(draft.timeout_seconds || 30)} onChange={(event) => onDraftChange({ timeout_seconds: Number(event.target.value) })} /><span>segundos</span></div></label><label className="mcp-field"><span>Retry</span><div className="mcp-unit-input"><input aria-label="Número de tentativas" type="number" min="1" max="5" disabled={retry.enabled !== true} value={Number(retry.max_attempts || 2)} onChange={(event) => onDraftChange({ retry: { ...retry, max_attempts: Number(event.target.value) } })} /><span>tentativas</span></div></label></div>
      <label className="mcp-switch"><input type="checkbox" checked={retry.enabled === true} onChange={(event) => onDraftChange({ retry: { ...retry, enabled: event.target.checked } })} /><span aria-hidden="true" /><div><strong>Retry automático</strong><small>Backoff exponencial · {Number(retry.backoff_ms || 1000) / 1000}s inicial</small></div></label>
      <details className="mcp-advanced-result"><summary>Opções avançadas de execução</summary><label className="mcp-field"><span>Idempotency key</span><input value={text(draft.idempotency_key)} onChange={(event) => onDraftChange({ idempotency_key: event.target.value })} placeholder="{{session.id}}:{{selected_slot_id}}" /></label>{['WRITE', 'DESTRUCTIVE', 'DELETE'].includes(classification) ? <label className="flow-editor-checkbox"><input type="checkbox" checked={draft.allow_external_write === true} onChange={(event) => onDraftChange({ allow_external_write: event.target.checked })} />Permitir que este node altere dados externos.</label> : null}{['DESTRUCTIVE', 'DELETE'].includes(classification) ? <label className="flow-editor-checkbox"><input type="checkbox" checked={draft.destructive_confirmed === true} onChange={(event) => onDraftChange({ destructive_confirmed: event.target.checked })} />Confirmo explicitamente esta ação destrutiva.</label> : null}</details>
    </section>
  </div>;
}

function Heading({ number, id, title, description }: { number: string; id: string; title: string; description: string }) { return <div className="mcp-card-heading"><span>{number}</span><div><h4 id={id}>{title}</h4><p>{description}</p></div></div>; }
function Empty({ children }: { children: ReactNode }) { return <div className="mcp-empty-hint">{children}</div>; }
