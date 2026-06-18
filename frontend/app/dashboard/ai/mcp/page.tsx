'use client';

import { useEffect, useState } from 'react';
import { apiFetch, parseApiResponse } from '../../../../lib/api';

type MCPServer = { id: string; name: string; description?: string | null; server_url?: string | null; transport: string; is_enabled: boolean; has_config: boolean };
type MCPTool = { id: string; server_id: string; tool_name: string; display_name: string; description: string; input_schema: Record<string, unknown>; is_enabled: boolean };

export default function MCPDashboardPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [name, setName] = useState('');
  const [serverUrl, setServerUrl] = useState('');
  const [bearerToken, setBearerToken] = useState('');
  const [message, setMessage] = useState('');

  async function load() {
    const [serverRows, toolRows] = await Promise.all([
      parseApiResponse<MCPServer[]>(await apiFetch('/api/mcp/servers')),
      parseApiResponse<MCPTool[]>(await apiFetch('/api/mcp/tools'))
    ]);
    setServers(serverRows);
    setTools(toolRows);
  }

  useEffect(() => {
    load().catch((error) => setMessage(error instanceof Error ? error.message : 'Falha ao carregar MCP.'));
  }, []);

  async function createServer() {
    setMessage('');
    await parseApiResponse<MCPServer>(await apiFetch('/api/mcp/servers', {
      method: 'POST',
      body: JSON.stringify({
        name,
        server_url: serverUrl,
        transport: 'http',
        config: bearerToken ? { bearer_token: bearerToken } : undefined,
        is_enabled: true
      })
    }));
    setName('');
    setServerUrl('');
    setBearerToken('');
    setMessage('Servidor MCP cadastrado. Secrets foram enviados apenas para criptografia.');
    await load();
  }

  async function discover(serverId: string) {
    setMessage('Descobrindo ferramentas...');
    await parseApiResponse<MCPTool[]>(await apiFetch(`/api/mcp/servers/${serverId}/discover`, { method: 'POST' }));
    setMessage('Descoberta concluída.');
    await load();
  }

  async function toggleTool(tool: MCPTool) {
    await parseApiResponse<MCPTool>(await apiFetch(`/api/mcp/tools/${tool.id}`, {
      method: 'PUT',
      body: JSON.stringify({ is_enabled: !tool.is_enabled })
    }));
    await load();
  }

  return (
    <section className="w-full min-w-0 space-y-6 p-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-wide text-blue-600">Dashboard → IA → MCP</p>
        <h1 className="text-2xl font-bold text-slate-900">MCP / Integrações</h1>
        <p className="text-sm text-slate-600">Conecte servidores MCP por workspace. URLs livres, localhost e secrets no frontend são bloqueados pelo backend.</p>
      </div>

      <section className="rounded-xl border bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Adicionar servidor</h2>
        <div className="mt-3 grid gap-3 md:grid-cols-3">
          <input className="rounded border px-3 py-2" placeholder="Nome" value={name} onChange={(event) => setName(event.target.value)} />
          <input className="rounded border px-3 py-2" placeholder="https://mcp.exemplo.com" value={serverUrl} onChange={(event) => setServerUrl(event.target.value)} />
          <input className="rounded border px-3 py-2" placeholder="Bearer token (opcional, nunca exibido)" type="password" value={bearerToken} onChange={(event) => setBearerToken(event.target.value)} />
        </div>
        <button className="mt-3 rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50" disabled={!name || !serverUrl} onClick={() => createServer().catch((error) => setMessage(error instanceof Error ? error.message : 'Falha ao criar servidor.'))}>Salvar servidor</button>
      </section>

      {message && <div className="rounded border border-blue-200 bg-blue-50 p-3 text-sm text-blue-900">{message}</div>}

      <section className="rounded-xl border bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Servidores MCP</h2>
        <div className="mt-3 space-y-3">
          {servers.map((server) => (
            <div key={server.id} className="rounded-lg border p-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="font-medium">{server.name}</p>
                  <p className="text-xs text-slate-500">{server.server_url} · {server.transport} · {server.has_config ? 'config protegida' : 'sem secrets'}</p>
                </div>
                <button className="rounded border px-3 py-1 text-sm" onClick={() => discover(server.id).catch((error) => setMessage(error instanceof Error ? error.message : 'Falha na descoberta.'))}>Descobrir ferramentas</button>
              </div>
            </div>
          ))}
          {servers.length === 0 && <p className="text-sm text-slate-500">Nenhum servidor MCP cadastrado.</p>}
        </div>
      </section>

      <section className="rounded-xl border bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Ferramentas disponíveis</h2>
        <div className="mt-3 space-y-3">
          {tools.map((tool) => (
            <div key={tool.id} className="rounded-lg border p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-medium">{tool.display_name}</p>
                  <p className="text-sm text-slate-600">{tool.description || tool.tool_name}</p>
                  <pre className="mt-2 max-h-40 overflow-auto rounded bg-slate-950 p-2 text-xs text-slate-100">{JSON.stringify(tool.input_schema, null, 2)}</pre>
                </div>
                <button className="rounded border px-3 py-1 text-sm" onClick={() => toggleTool(tool).catch((error) => setMessage(error instanceof Error ? error.message : 'Falha ao alternar ferramenta.'))}>{tool.is_enabled ? 'Desabilitar' : 'Habilitar'}</button>
              </div>
            </div>
          ))}
          {tools.length === 0 && <p className="text-sm text-slate-500">Descubra ferramentas em um servidor para exibí-las aqui.</p>}
        </div>
      </section>
    </section>
  );
}
