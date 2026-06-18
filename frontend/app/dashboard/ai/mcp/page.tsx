'use client';

import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, ServerCog, Wrench } from 'lucide-react';
import { apiFetch, parseApiResponse } from '../../../../lib/api';

type MCPServer = { id: string; name: string; description?: string | null; server_url?: string | null; transport: string; is_enabled: boolean; has_config: boolean };
type MCPTool = { id: string; server_id: string; tool_name: string; display_name: string; description: string; input_schema: Record<string, unknown>; is_enabled: boolean };
type MessageTone = 'success' | 'error' | 'warning';

const cardClass = 'rounded-2xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.05)]';
const inputClass = 'h-11 w-full rounded-xl border border-slate-200 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 hover:border-emerald-200 focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100';
const secondaryButtonClass = 'inline-flex h-10 items-center justify-center rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50/40 disabled:cursor-not-allowed disabled:opacity-50';
const primaryButtonClass = 'inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-emerald-600 px-5 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(16,185,129,0.22)] transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 disabled:shadow-none';

function EmptyState({ icon: Icon, title, description }: { icon: typeof ServerCog; title: string; description: string }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-slate-200 bg-slate-50/80 px-6 py-10 text-center">
      <span className="inline-flex h-12 w-12 items-center justify-center rounded-2xl border border-emerald-100 bg-emerald-50 text-emerald-600 shadow-sm">
        <Icon size={22} strokeWidth={2.3} />
      </span>
      <p className="mt-4 text-sm font-bold text-slate-900">{title}</p>
      <p className="mt-1 max-w-md text-sm leading-relaxed text-slate-500">{description}</p>
    </div>
  );
}

export default function MCPDashboardPage() {
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [name, setName] = useState('');
  const [serverUrl, setServerUrl] = useState('');
  const [bearerToken, setBearerToken] = useState('');
  const [message, setMessage] = useState('');
  const [messageTone, setMessageTone] = useState<MessageTone>('success');
  const [creating, setCreating] = useState(false);
  const [discoveringServerId, setDiscoveringServerId] = useState<string | null>(null);
  const [togglingToolId, setTogglingToolId] = useState<string | null>(null);

  async function load() {
    const [serverRows, toolRows] = await Promise.all([
      parseApiResponse<MCPServer[]>(await apiFetch('/api/mcp/servers')),
      parseApiResponse<MCPTool[]>(await apiFetch('/api/mcp/tools'))
    ]);
    setServers(serverRows);
    setTools(toolRows);
  }

  useEffect(() => {
    load().catch((error) => {
      setMessageTone('error');
      setMessage(error instanceof Error ? error.message : 'Falha ao carregar MCP.');
    });
  }, []);

  async function createServer() {
    setCreating(true);
    setMessage('');
    try {
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
      setMessageTone('success');
      setMessage('Servidor MCP cadastrado. Secrets foram enviados apenas para criptografia.');
      await load();
    } finally {
      setCreating(false);
    }
  }

  async function discover(serverId: string) {
    setDiscoveringServerId(serverId);
    setMessageTone('warning');
    setMessage('Descobrindo ferramentas...');
    try {
      await parseApiResponse<MCPTool[]>(await apiFetch(`/api/mcp/servers/${serverId}/discover`, { method: 'POST' }));
      setMessageTone('success');
      setMessage('Descoberta concluída.');
      await load();
    } finally {
      setDiscoveringServerId(null);
    }
  }

  async function toggleTool(tool: MCPTool) {
    setTogglingToolId(tool.id);
    try {
      await parseApiResponse<MCPTool>(await apiFetch(`/api/mcp/tools/${tool.id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_enabled: !tool.is_enabled })
      }));
      await load();
    } finally {
      setTogglingToolId(null);
    }
  }

  const messageClass = messageTone === 'error'
    ? 'border-red-100 bg-red-50 text-red-700'
    : messageTone === 'warning'
      ? 'border-orange-100 bg-orange-50 text-orange-700'
      : 'border-emerald-100 bg-emerald-50/70 text-emerald-800';

  return (
    <main className="min-h-screen w-full min-w-0 bg-slate-50 px-5 py-6 text-slate-900 lg:px-6">
      <div className="w-full min-w-0 space-y-5">
        <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <nav className="mb-2 flex items-center gap-2 text-xs font-medium text-slate-400" aria-label="Breadcrumb">
              <span>Dashboard</span><span className="text-slate-300">&gt;</span><span>IA</span><span className="text-slate-300">&gt;</span><span className="text-emerald-600">MCP</span>
            </nav>
            <h1 className="text-xl font-semibold leading-tight text-gray-900 md:text-2xl">MCP / Integrações</h1>
            <p className="mt-1 text-sm text-gray-500">Conecte servidores MCP por workspace. URLs livres, localhost e secrets no frontend são bloqueados pelo backend.</p>
          </div>
        </header>

        <section className={cardClass}>
          <div className="mb-5">
            <h2 className="text-base font-bold text-slate-900">Adicionar servidor</h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">Cadastre um endpoint MCP seguro para disponibilizar novas ferramentas ao workspace.</p>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <input className={inputClass} placeholder="Nome" value={name} onChange={(event) => setName(event.target.value)} />
            <input className={inputClass} placeholder="https://mcp.exemplo.com" value={serverUrl} onChange={(event) => setServerUrl(event.target.value)} />
            <input className={inputClass} placeholder="Bearer token (opcional, nunca exibido)" type="password" value={bearerToken} onChange={(event) => setBearerToken(event.target.value)} />
          </div>
          <button className="mt-4 inline-flex h-11 items-center justify-center gap-2 rounded-xl bg-emerald-600 px-5 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(16,185,129,0.22)] transition hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 disabled:shadow-none" disabled={!name || !serverUrl || creating} onClick={() => createServer().catch((error) => { setMessageTone('error'); setMessage(error instanceof Error ? error.message : 'Falha ao criar servidor.'); })}>{creating ? <Loader2 className="animate-spin text-emerald-700" size={16} /> : null}{creating ? 'Salvando...' : 'Salvar servidor'}</button>
        </section>

        {message && <div className={`rounded-2xl border p-4 text-sm font-medium shadow-[0_12px_30px_rgba(15,23,42,0.04)] ${messageClass}`}>{message}</div>}

        <section className={cardClass}>
          <div className="mb-5"><h2 className="text-base font-bold text-slate-900">Servidores MCP</h2><p className="mt-1 text-xs leading-relaxed text-slate-500">Gerencie os servidores conectados e descubra as ferramentas disponíveis.</p></div>
          <div className="space-y-3">
            {servers.map((server) => (
              <div key={server.id} className="rounded-2xl border border-slate-100 bg-slate-50/70 p-4 transition hover:border-emerald-100 hover:bg-emerald-50/40">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold text-slate-900">{server.name}</p>
                    <p className="mt-1 text-xs text-slate-500">{server.server_url} · {server.transport} · {server.has_config ? 'config protegida' : 'sem secrets'}</p>
                  </div>
                  <button className={secondaryButtonClass} onClick={() => discover(server.id).catch((error) => { setMessageTone('error'); setMessage(error instanceof Error ? error.message : 'Falha na descoberta.'); })} disabled={discoveringServerId === server.id}>{discoveringServerId === server.id ? <Loader2 className="mr-2 animate-spin text-emerald-600" size={15} /> : null}{discoveringServerId === server.id ? 'Descobrindo...' : 'Descobrir ferramentas'}</button>
                </div>
              </div>
            ))}
            {servers.length === 0 && <EmptyState icon={ServerCog} title="Nenhum servidor MCP cadastrado." description="Adicione um servidor para conectar integrações e descobrir ferramentas disponíveis neste workspace." />}
          </div>
        </section>

        <section className={cardClass}>
          <div className="mb-5"><h2 className="text-base font-bold text-slate-900">Ferramentas disponíveis</h2><p className="mt-1 text-xs leading-relaxed text-slate-500">Habilite, desabilite e valide ferramentas descobertas nos servidores MCP.</p></div>
          <div className="grid gap-3 lg:grid-cols-2">
            {tools.map((tool) => (
              <div key={tool.id} className="rounded-2xl border border-slate-100 bg-white p-4 shadow-sm transition hover:border-emerald-100 hover:bg-emerald-50/30">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2"><p className="font-semibold text-slate-900">{tool.display_name}</p>{tool.is_enabled ? <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700"><CheckCircle2 size={13} />Ativo</span> : <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-500">Inativo</span>}</div>
                    <p className="mt-2 text-sm leading-relaxed text-slate-600">{tool.description || tool.tool_name}</p>
                    <pre className="mt-3 max-h-40 overflow-auto rounded-xl bg-slate-900 p-3 text-xs text-slate-100">{JSON.stringify(tool.input_schema, null, 2)}</pre>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap justify-end gap-2"><button className={secondaryButtonClass} onClick={() => toggleTool(tool).catch((error) => { setMessageTone('error'); setMessage(error instanceof Error ? error.message : 'Falha ao alternar ferramenta.'); })} disabled={togglingToolId === tool.id}>{togglingToolId === tool.id ? <Loader2 className="mr-2 animate-spin text-emerald-600" size={15} /> : null}{tool.is_enabled ? 'Desabilitar' : 'Habilitar'}</button><button className={primaryButtonClass} disabled type="button">Testar</button></div>
              </div>
            ))}
            {tools.length === 0 && <div className="lg:col-span-2"><EmptyState icon={Wrench} title="Nenhuma ferramenta disponível." description="Descubra ferramentas em um servidor MCP para exibí-las aqui com ações de ativação e teste." /></div>}
          </div>
        </section>
      </div>
    </main>
  );
}
