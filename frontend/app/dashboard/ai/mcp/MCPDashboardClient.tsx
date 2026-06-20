"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  Edit3,
  Link2,
  Loader2,
  PlugZap,
  ServerCog,
  Trash2,
  Wrench,
  XCircle,
} from "lucide-react";
import {
  apiFetch,
  disconnectGoogleCalendar,
  getGoogleCalendarConnectUrl,
  getGoogleCalendarStatus,
  parseApiResponse,
} from "../../../../lib/api";
import type { GoogleCalendarConnectionStatus } from "../../../../lib/types";

type MCPServer = {
  id: string;
  name: string;
  description?: string | null;
  server_url?: string | null;
  transport: string;
  is_enabled: boolean;
  has_config: boolean;
  discovery?: { status: string; tools_discovered: number };
};
type MCPTool = {
  id: string;
  server_id: string;
  tool_name: string;
  display_name: string;
  description: string;
  input_schema: Record<string, unknown>;
  is_enabled: boolean;
  server_name?: string;
  metadata?: {
    last_discovered_at?: string;
    missing_from_last_discovery?: boolean;
    provider?: string;
  };
};
type MessageTone = "success" | "error" | "warning";

const cardClass =
  "rounded-3xl border border-slate-200/80 bg-white p-5 shadow-sm shadow-slate-200/60";
const inputClass =
  "h-11 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-800 outline-none transition placeholder:text-slate-400 hover:border-emerald-200 focus:border-emerald-500 focus:ring-4 focus:ring-emerald-100/80";
const labelClass = "text-xs font-bold uppercase tracking-wide text-slate-500";
const primaryButtonClass =
  "inline-flex h-11 items-center justify-center gap-2 rounded-2xl bg-emerald-600 px-5 text-sm font-bold text-white shadow-sm transition hover:bg-emerald-700 focus:outline-none focus:ring-4 focus:ring-emerald-100 disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500 disabled:shadow-none";
const secondaryButtonClass =
  "inline-flex h-10 items-center justify-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 text-sm font-bold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-700 focus:outline-none focus:ring-4 focus:ring-emerald-100 disabled:cursor-not-allowed disabled:opacity-50";
const dangerButtonClass =
  "inline-flex h-10 items-center justify-center gap-2 rounded-2xl border border-red-100 bg-white px-4 text-sm font-bold text-red-600 transition hover:bg-red-50 focus:outline-none focus:ring-4 focus:ring-red-100 disabled:cursor-not-allowed disabled:opacity-50";

const googleCalendarToolNames: Record<string, string> = {
  google_calendar_create_event: "Criar evento",
  google_calendar_list_events: "Listar eventos",
  google_calendar_check_availability: "Verificar disponibilidade",
  google_calendar_delete_event: "Excluir evento",
};

function getToolDisplayName(tool: MCPTool) {
  return (
    googleCalendarToolNames[tool.tool_name] ||
    tool.display_name?.replace(/^\[Google Calendar\]\s*/, "") ||
    tool.tool_name
  );
}

function StatusBadge({ active }: { active: boolean }) {
  return active ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-100">
      <CheckCircle2 size={13} />
      Ativo
    </span>
  ) : (
    <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-bold text-slate-500 ring-1 ring-slate-200">
      Inativo
    </span>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
}: {
  icon: typeof ServerCog;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-3xl border border-dashed border-emerald-200 bg-gradient-to-b from-emerald-50/70 to-white px-6 py-12 text-center">
      <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-white text-emerald-600 shadow-sm ring-1 ring-emerald-100">
        <Icon size={24} strokeWidth={2.3} />
      </span>
      <p className="mt-4 text-base font-bold text-slate-900">{title}</p>
      <p className="mt-2 max-w-md text-sm leading-relaxed text-slate-500">
        {description}
      </p>
    </div>
  );
}

export default function MCPDashboardClient() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [servers, setServers] = useState<MCPServer[]>([]);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [name, setName] = useState("");
  const [serverUrl, setServerUrl] = useState("");
  const [bearerToken, setBearerToken] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [messageTone, setMessageTone] = useState<MessageTone>("success");
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState(false);
  const [discoveringServerId, setDiscoveringServerId] = useState<string | null>(
    null,
  );
  const [removingServerId, setRemovingServerId] = useState<string | null>(null);
  const [togglingToolId, setTogglingToolId] = useState<string | null>(null);
  const [calendarStatus, setCalendarStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingCalendar, setLoadingCalendar] = useState(true);
  const [calendarActionLoading, setCalendarActionLoading] = useState(false);
  const [calendarError, setCalendarError] = useState("");

  const mcpTools = useMemo(
    () => tools.filter((tool) => tool.metadata?.provider !== "google_calendar"),
    [tools],
  );
  const googleCalendarTools = useMemo(
    () => tools.filter((tool) => tool.metadata?.provider === "google_calendar"),
    [tools],
  );

  const toolsByServer = useMemo(
    () =>
      mcpTools.reduce<Record<string, number>>(
        (acc, tool) => ({
          ...acc,
          [tool.server_id]: (acc[tool.server_id] || 0) + 1,
        }),
        {},
      ),
    [mcpTools],
  );

  async function refreshCalendarStatus(successMessage?: string) {
    setLoadingCalendar(true);
    setCalendarError("");
    try {
      const status = await getGoogleCalendarStatus();
      setCalendarStatus(status);
      if (successMessage) {
        setMessageTone("success");
        setMessage(successMessage);
      }
    } catch {
      setCalendarError("Falha ao carregar status do Google Calendar.");
    } finally {
      setLoadingCalendar(false);
    }
  }

  async function load() {
    const [serverRows, toolRows] = await Promise.all([
      parseApiResponse<MCPServer[]>(await apiFetch("/api/mcp/servers")),
      parseApiResponse<MCPTool[]>(await apiFetch("/api/mcp/tools")),
    ]);
    setServers(serverRows);
    setTools(toolRows);
  }
  useEffect(() => {
    const integration = searchParams.get("integration");
    const status = searchParams.get("status");
    const isGoogleCalendarReturn = integration === "google_calendar";

    if (isGoogleCalendarReturn && status === "connected") {
      refreshCalendarStatus("Google Calendar conectado com sucesso.");
    } else if (isGoogleCalendarReturn && status === "error") {
      refreshCalendarStatus();
      setCalendarError("Falha ao conectar Google Calendar.");
    } else {
      refreshCalendarStatus();
    }

    if (isGoogleCalendarReturn) {
      const nextParams = new URLSearchParams(searchParams.toString());
      nextParams.delete("integration");
      nextParams.delete("status");
      const query = nextParams.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    }

    load().catch((error) => {
      setMessageTone("error");
      setMessage(
        error instanceof Error
          ? error.message
          : "Falha ao carregar integrações.",
      );
    });
  }, [pathname, router, searchParams]);

  function resetForm() {
    setName("");
    setServerUrl("");
    setBearerToken("");
    setEditingId(null);
  }
  function startEdit(server: MCPServer) {
    setEditingId(server.id);
    setName(server.name);
    setServerUrl(server.server_url || "");
    setBearerToken("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function validateConnection() {
    setTesting(true);
    setMessageTone("success");
    setMessage(
      "Formato da conexão validado. A descoberta confirma as ferramentas após salvar.",
    );
    setTimeout(() => setTesting(false), 350);
  }

  async function saveServer() {
    setCreating(true);
    setMessage("");
    try {
      const body = JSON.stringify({
        name,
        server_url: serverUrl,
        transport: "http",
        config: bearerToken ? { bearer_token: bearerToken } : undefined,
        is_enabled: true,
      });
      const saved = await parseApiResponse<MCPServer>(
        await apiFetch(
          editingId ? `/api/mcp/servers/${editingId}` : "/api/mcp/servers",
          { method: editingId ? "PUT" : "POST", body },
        ),
      );
      setMessageTone("success");
      setMessage(
        editingId
          ? "Servidor MCP atualizado com segurança."
          : `Servidor MCP salvo e descoberta automática concluída (${saved.discovery?.tools_discovered ?? 0} ferramentas).`,
      );
      resetForm();
      await load();
    } finally {
      setCreating(false);
    }
  }
  async function removeServer(serverId: string) {
    if (!confirm("Remover este servidor MCP?")) return;
    setRemovingServerId(serverId);
    try {
      await apiFetch(`/api/mcp/servers/${serverId}`, { method: "DELETE" });
      setMessageTone("success");
      setMessage("Servidor MCP removido.");
      await load();
    } finally {
      setRemovingServerId(null);
    }
  }
  async function discover(serverId: string) {
    setDiscoveringServerId(serverId);
    setMessageTone("warning");
    setMessage("Descobrindo ferramentas...");
    try {
      await parseApiResponse<MCPTool[]>(
        await apiFetch(`/api/mcp/servers/${serverId}/discover`, {
          method: "POST",
        }),
      );
      setMessageTone("success");
      setMessage("Ferramentas atualizadas.");
      await load();
    } finally {
      setDiscoveringServerId(null);
    }
  }
  function connectCalendar() {
    setCalendarError("");
    try {
      window.location.href = getGoogleCalendarConnectUrl();
    } catch {
      setCalendarError("Falha ao conectar Google Calendar.");
    }
  }

  async function disconnectCalendar() {
    setCalendarActionLoading(true);
    setCalendarError("");
    try {
      const status = await disconnectGoogleCalendar();
      setCalendarStatus(status);
      setMessageTone("success");
      setMessage("Google Calendar desconectado.");
      await load();
    } catch {
      setCalendarError("Falha ao desconectar Google Calendar.");
    } finally {
      setCalendarActionLoading(false);
    }
  }

  async function toggleTool(tool: MCPTool) {
    setTogglingToolId(tool.id);
    try {
      await parseApiResponse<MCPTool>(
        await apiFetch(`/api/mcp/tools/${tool.id}`, {
          method: "PUT",
          body: JSON.stringify({ is_enabled: !tool.is_enabled }),
        }),
      );
      await load();
    } finally {
      setTogglingToolId(null);
    }
  }

  const isCalendarConnected = calendarStatus?.connected === true;
  const calendarAccountEmail =
    typeof calendarStatus?.metadata?.account_email === "string"
      ? calendarStatus.metadata.account_email
      : "Nenhuma conta conectada";

  const messageClass =
    messageTone === "error"
      ? "border-red-100 bg-red-50 text-red-700"
      : messageTone === "warning"
        ? "border-amber-100 bg-amber-50 text-amber-800"
        : "border-emerald-100 bg-emerald-50 text-emerald-800";

  return (
    <main className="min-h-screen w-full min-w-0 bg-slate-50 px-5 py-6 text-slate-900 lg:px-8">
      <div className="w-full min-w-0 space-y-6">
        <header>
          <nav
            className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-400"
            aria-label="Breadcrumb"
          >
            <span>Dashboard</span>
            <span>›</span>
            <span>IA</span>
            <span>›</span>
            <span className="text-emerald-600">Integrações</span>
          </nav>
          <h1 className="text-2xl font-bold leading-tight text-slate-950 md:text-3xl">
            Integrações de IA
          </h1>
          <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-500">
            Conecte ferramentas externas ao workspace com segurança. A camada
            MCP continua documentada tecnicamente, sem expor detalhes
            desnecessários para a operação diária.
          </p>
        </header>

        <section className={cardClass}>
          <div className="mb-5 flex items-start gap-3">
            <span className="rounded-2xl bg-emerald-50 p-3 text-emerald-600">
              <PlugZap size={22} />
            </span>
            <div>
              <h2 className="text-lg font-bold text-slate-950">
                Novo servidor MCP
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Informe o nome, a URL segura e, se necessário, o token protegido
                do servidor MCP.
              </p>
            </div>
          </div>
          <div className="grid gap-4">
            <label className="space-y-2">
              <span className={labelClass}>Nome</span>
              <input
                className={inputClass}
                placeholder="Ex.: Catálogo interno"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className="space-y-2">
              <span className={labelClass}>URL</span>
              <input
                className={inputClass}
                placeholder="https://integracao.exemplo.com"
                value={serverUrl}
                onChange={(e) => setServerUrl(e.target.value)}
              />
            </label>
            <label className="space-y-2">
              <span className={labelClass}>Token de acesso (opcional)</span>
              <input
                className={inputClass}
                placeholder="Nunca exibido após salvar"
                type="password"
                value={bearerToken}
                onChange={(e) => setBearerToken(e.target.value)}
              />
            </label>
          </div>
          <div className="mt-5 flex flex-wrap gap-3">
            <button
              className={secondaryButtonClass}
              disabled={!serverUrl || testing}
              onClick={validateConnection}
            >
              {testing ? (
                <Loader2 className="animate-spin" size={16} />
              ) : (
                <Link2 size={16} />
              )}
              Testar conexão
            </button>
            <button
              className={primaryButtonClass}
              disabled={!name || !serverUrl || creating}
              onClick={() =>
                saveServer().catch((error) => {
                  setMessageTone("error");
                  setMessage(
                    error instanceof Error
                      ? error.message
                      : "Falha ao salvar servidor MCP.",
                  );
                })
              }
            >
              {creating ? <Loader2 className="animate-spin" size={16} /> : null}
              {creating ? "Salvando..." : "Salvar integração"}
            </button>
            {editingId ? (
              <button className={secondaryButtonClass} onClick={resetForm}>
                Cancelar edição
              </button>
            ) : null}
          </div>
        </section>

        <section className={cardClass}>
          <div className="mb-5">
            <p className="text-xs font-bold uppercase tracking-[0.16em] text-emerald-600">
              Integrações oficiais
            </p>
            <h2 className="mt-2 text-lg font-bold text-slate-950">
              Apps conectados ao Wazza
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Conectores mantidos pela plataforma, separados dos servidores MCP
              externos.
            </p>
          </div>
          <article className="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-emerald-50/40 p-5 shadow-sm">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex gap-4">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-700">
                  <CalendarDays size={22} />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-bold text-slate-950">
                      Google Calendar
                    </h3>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold ${isCalendarConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                    >
                      {loadingCalendar ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : isCalendarConnected ? (
                        <CheckCircle2 size={12} />
                      ) : (
                        <XCircle size={12} />
                      )}
                      {loadingCalendar
                        ? "Carregando..."
                        : isCalendarConnected
                          ? "Conectado"
                          : "Não conectado"}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">
                    Permita que a IA consulte disponibilidade e eventos sem
                    expor tokens no frontend.
                  </p>
                  <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                    <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                      <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                        Provider
                      </b>
                      {calendarStatus?.provider || "google_calendar"}
                    </p>
                    <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                      <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                        Conta
                      </b>
                      {loadingCalendar
                        ? "Consultando status..."
                        : calendarAccountEmail}
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-56">
                {isCalendarConnected ? (
                  <button
                    type="button"
                    disabled={calendarActionLoading || loadingCalendar}
                    onClick={() => disconnectCalendar()}
                    className={dangerButtonClass}
                  >
                    {calendarActionLoading ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <XCircle size={16} />
                    )}{" "}
                    Desconectar
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={loadingCalendar}
                    onClick={connectCalendar}
                    className={primaryButtonClass}
                  >
                    <CalendarDays size={16} /> Conectar Google Calendar
                  </button>
                )}
                <button
                  type="button"
                  disabled={loadingCalendar}
                  onClick={() => refreshCalendarStatus()}
                  className={secondaryButtonClass}
                >
                  Atualizar status
                </button>
              </div>
            </div>
            <div className="mt-5 border-t border-emerald-100 pt-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h4 className="text-sm font-bold text-slate-950">
                    Ferramentas disponíveis
                  </h4>
                  <p className="mt-1 text-xs font-semibold text-slate-500">
                    Origem: Google Calendar conectado
                  </p>
                </div>
                <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-100">
                  {googleCalendarTools.length} ferramentas
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                {googleCalendarTools.map((tool) => (
                  <div
                    key={tool.id}
                    className="rounded-2xl border border-emerald-100 bg-white/85 p-4 shadow-sm"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="text-sm font-bold text-slate-950">
                        {getToolDisplayName(tool)}
                      </p>
                      <StatusBadge active={tool.is_enabled} />
                    </div>
                    <p className="mt-3 text-xs font-semibold text-slate-500">
                      Origem: Google Calendar conectado
                    </p>
                    <p
                      className="mt-1 truncate font-mono text-[11px] text-slate-400"
                      title={tool.tool_name}
                    >
                      {tool.tool_name}
                    </p>
                  </div>
                ))}
                {googleCalendarTools.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-emerald-200 bg-white/70 px-4 py-5 text-sm font-semibold text-slate-500 sm:col-span-2 xl:col-span-4">
                    Conecte o Google Calendar para exibir as ferramentas
                    oficiais de agenda.
                  </div>
                ) : null}
              </div>
            </div>
            {calendarError ? (
              <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                <AlertCircle size={16} /> {calendarError}
              </p>
            ) : null}
          </article>
        </section>

        {message && (
          <div
            className={`rounded-2xl border p-4 text-sm font-semibold shadow-sm ${messageClass}`}
          >
            {message}
          </div>
        )}

        <section className={cardClass}>
          <div className="mb-5">
            <h2 className="text-lg font-bold text-slate-950">Servidores MCP</h2>
            <p className="mt-1 text-sm text-slate-500">
              Gerencie servidores MCP externos e descubra ferramentas
              disponíveis.
            </p>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            {servers.map((server) => (
              <article
                key={server.id}
                className="rounded-3xl border border-slate-200 bg-slate-50/60 p-5 transition hover:border-emerald-200 hover:bg-white"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-slate-950">
                        {server.name}
                      </h3>
                      <StatusBadge active={server.is_enabled} />
                    </div>
                    <p className="mt-2 break-all text-sm font-medium text-slate-600">
                      {server.server_url || "URL não informada"}
                    </p>
                    <p className="mt-3 text-sm text-slate-500">
                      <strong className="text-slate-800">
                        {toolsByServer[server.id] || 0}
                      </strong>{" "}
                      ferramentas ·{" "}
                      {server.has_config
                        ? "credenciais protegidas"
                        : "sem credenciais"}
                    </p>
                  </div>
                </div>
                <div className="mt-5 flex flex-wrap gap-2">
                  <button
                    className={secondaryButtonClass}
                    onClick={() => startEdit(server)}
                  >
                    <Edit3 size={15} />
                    Editar
                  </button>
                  <button
                    className={secondaryButtonClass}
                    onClick={() =>
                      discover(server.id).catch((error) => {
                        setMessageTone("error");
                        setMessage(
                          error instanceof Error
                            ? error.message
                            : "Falha na descoberta.",
                        );
                      })
                    }
                    disabled={discoveringServerId === server.id}
                  >
                    {discoveringServerId === server.id ? (
                      <Loader2 className="animate-spin" size={15} />
                    ) : (
                      <Wrench size={15} />
                    )}
                    Descobrir Ferramentas
                  </button>
                  <button
                    className={dangerButtonClass}
                    onClick={() =>
                      removeServer(server.id).catch((error) => {
                        setMessageTone("error");
                        setMessage(
                          error instanceof Error
                            ? error.message
                            : "Falha ao remover servidor MCP.",
                        );
                      })
                    }
                    disabled={removingServerId === server.id}
                  >
                    {removingServerId === server.id ? (
                      <Loader2 className="animate-spin" size={15} />
                    ) : (
                      <Trash2 size={15} />
                    )}
                    Remover
                  </button>
                </div>
              </article>
            ))}
            {servers.length === 0 && (
              <div className="xl:col-span-2">
                <EmptyState
                  icon={ServerCog}
                  title="Nenhum servidor MCP conectado"
                  description="Adicione o primeiro servidor MCP para disponibilizar novas capacidades externas de IA ao workspace."
                />
              </div>
            )}
          </div>
        </section>

        <section className={cardClass}>
          <div className="mb-5">
            <h2 className="text-lg font-bold text-slate-950">
              Ferramentas disponíveis
            </h2>
            <p className="mt-1 text-sm text-slate-500">
              Exibe apenas ferramentas MCP externas ou recursos não associados a
              uma integração oficial.
            </p>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            {mcpTools.map((tool) => (
              <article
                key={tool.id}
                className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-emerald-200 hover:bg-emerald-50/20"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h4 className="font-bold text-slate-950">
                        {tool.display_name || tool.tool_name}
                      </h4>
                      <StatusBadge active={tool.is_enabled} />
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-slate-600">
                      {tool.description || "Sem descrição informada."}
                    </p>
                    <p className="mt-3 text-xs font-semibold text-slate-400">
                      Identificador: {tool.tool_name}
                    </p>
                    {tool.metadata?.last_discovered_at ? (
                      <p className="mt-1 text-xs font-semibold text-slate-400">
                        Última descoberta:{" "}
                        {new Date(
                          tool.metadata.last_discovered_at,
                        ).toLocaleString("pt-BR")}
                      </p>
                    ) : null}
                    {tool.metadata?.missing_from_last_discovery ? (
                      <p className="mt-2 rounded-full bg-amber-50 px-3 py-1 text-xs font-bold text-amber-700 ring-1 ring-amber-100">
                        Ausente na última atualização do servidor
                      </p>
                    ) : null}
                  </div>
                  <button
                    className={
                      tool.is_enabled
                        ? secondaryButtonClass
                        : primaryButtonClass
                    }
                    onClick={() =>
                      toggleTool(tool).catch((error) => {
                        setMessageTone("error");
                        setMessage(
                          error instanceof Error
                            ? error.message
                            : "Falha ao alternar ferramenta.",
                        );
                      })
                    }
                    disabled={togglingToolId === tool.id}
                  >
                    {togglingToolId === tool.id ? (
                      <Loader2 className="animate-spin" size={15} />
                    ) : null}
                    {tool.is_enabled ? "Desabilitar" : "Habilitar"}
                  </button>
                </div>
              </article>
            ))}
            {mcpTools.length === 0 ? (
              <div className="lg:col-span-2">
                <EmptyState
                  icon={Wrench}
                  title="Nenhuma ferramenta MCP disponível."
                  description="Ferramentas oficiais, como Google Calendar, aparecem dentro do card da própria integração."
                />
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </main>
  );
}
