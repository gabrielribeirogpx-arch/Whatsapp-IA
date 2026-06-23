"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  AlertCircle,
  CalendarDays,
  FolderOpen,
  KeyRound,
  Mail,
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
  connectSuitable,
  disconnectGoogle,
  disconnectGoogleCalendar,
  disconnectGmail,
  disconnectGoogleDrive,
  disconnectGoogleSheets,
  disconnectSuitable,
  getGmailConnectUrl,
  getGmailStatus,
  getGoogleDriveConnectUrl,
  getGoogleDriveStatus,
  getGoogleSheetsConnectUrl,
  getGoogleSheetsStatus,
  getGoogleCalendarConnectUrl,
  getGoogleCalendarStatus,
  getSuitableStatus,
  parseApiResponse,
} from "../../../../lib/api";
import {
  ENABLE_GMAIL_INTEGRATION,
  ENABLE_GOOGLE_SHEETS_INTEGRATION,
} from "../../../../lib/features";
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
const gmailToolNames: Record<string, string> = {
  gmail_list_messages: "Listar e-mails",
  gmail_search_messages: "Buscar e-mails",
  gmail_read_message: "Ler e-mail",
  gmail_create_draft: "Criar rascunho",
  gmail_send_email: "Enviar e-mail",
};
const googleDriveToolNames: Record<string, string> = {
  google_drive_list_files: "Listar arquivos",
  google_drive_search_files: "Buscar arquivos",
  google_drive_read_file: "Ler arquivo",
  google_drive_create_document: "Criar documento",
  google_drive_create_folder: "Criar pasta",
};
const googleSheetsToolNames: Record<string, string> = {
  google_sheets_list_spreadsheets: "Listar planilhas",
  google_sheets_read_sheet: "Ler planilha",
  google_sheets_append_row: "Adicionar linha",
  google_sheets_update_row: "Atualizar linha",
  google_sheets_create_spreadsheet: "Criar planilha",
};
const suitableToolNames: Record<string, string> = {
  suitable_check_key: "Validar API Key",
  suitable_create_order: "Criar pedido",
};

function isGmailTool(tool: MCPTool) {
  const provider = String(tool.metadata?.provider || "").toLowerCase();
  const toolName = String(tool.tool_name || "").toLowerCase();
  const displayName = String(tool.display_name || "").toLowerCase();
  const name = String((tool as { name?: string }).name || "").toLowerCase();

  return (
    provider === "gmail" ||
    toolName.startsWith("gmail_") ||
    [displayName, name].some((value) =>
      /(^|\[|\s)(gmail|gmail send|gmail draft|gmail read|gmail search|gmail labels|gmail threads|gmail attachments)(\]|\s|$)/i.test(
        value,
      ),
    )
  );
}

function isGoogleSheetsTool(tool: MCPTool) {
  const provider = String(tool.metadata?.provider || "").toLowerCase();
  const toolName = String(tool.tool_name || "").toLowerCase();
  const displayName = String(tool.display_name || "").toLowerCase();
  const name = String((tool as { name?: string }).name || "").toLowerCase();

  return (
    provider === "google_sheets" ||
    toolName.startsWith("google_sheets_") ||
    [displayName, name].some((value) =>
      /(^|\[|\s)(google sheets|sheets)(\]|\s|$)/i.test(value),
    )
  );
}

function getPresentationTools(tools: MCPTool[]) {
  return tools.filter(
    (tool) =>
      (ENABLE_GMAIL_INTEGRATION || !isGmailTool(tool)) &&
      (ENABLE_GOOGLE_SHEETS_INTEGRATION || !isGoogleSheetsTool(tool)),
  );
}

function getToolDisplayName(tool: MCPTool) {
  return (
    googleCalendarToolNames[tool.tool_name] ||
    gmailToolNames[tool.tool_name] ||
    googleDriveToolNames[tool.tool_name] ||
    googleSheetsToolNames[tool.tool_name] ||
    suitableToolNames[tool.tool_name] ||
    tool.display_name?.replace(
      /^\[(Google Calendar|Gmail|Google Drive|Google Sheets|Suitable)\]\s*/,
      "",
    ) ||
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
  const [gmailStatus, setGmailStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingGmail, setLoadingGmail] = useState(true);
  const [gmailActionLoading, setGmailActionLoading] = useState(false);
  const [gmailError, setGmailError] = useState("");
  const [driveStatus, setDriveStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingDrive, setLoadingDrive] = useState(true);
  const [driveActionLoading, setDriveActionLoading] = useState(false);
  const [driveError, setDriveError] = useState("");
  const [sheetsStatus, setSheetsStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingSheets, setLoadingSheets] = useState(true);
  const [sheetsActionLoading, setSheetsActionLoading] = useState(false);
  const [sheetsError, setSheetsError] = useState("");
  const [suitableStatus, setSuitableStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingSuitable, setLoadingSuitable] = useState(true);
  const [suitableActionLoading, setSuitableActionLoading] = useState(false);
  const [suitableError, setSuitableError] = useState("");
  const [suitableApiKey, setSuitableApiKey] = useState("");
  const [showSuitableKeyField, setShowSuitableKeyField] = useState(false);

  const presentationTools = useMemo(() => getPresentationTools(tools), [tools]);

  const mcpTools = useMemo(
    () =>
      presentationTools.filter(
        (tool) =>
          ![
            "google_calendar",
            "google_drive",
            "google_sheets",
            "suitable",
          ].includes(String(tool.metadata?.provider || "")),
      ),
    [presentationTools],
  );
  const googleCalendarTools = useMemo(
    () =>
      presentationTools.filter(
        (tool) => tool.metadata?.provider === "google_calendar",
      ),
    [presentationTools],
  );
  const gmailTools = useMemo(
    () =>
      ENABLE_GMAIL_INTEGRATION
        ? presentationTools.filter(
            (tool) => tool.metadata?.provider === "gmail",
          )
        : [],
    [presentationTools],
  );
  const googleDriveTools = useMemo(
    () =>
      presentationTools.filter(
        (tool) => tool.metadata?.provider === "google_drive",
      ),
    [presentationTools],
  );
  const googleSheetsTools = useMemo(
    () =>
      presentationTools.filter(
        (tool) => tool.metadata?.provider === "google_sheets",
      ),
    [presentationTools],
  );
  const suitableTools = useMemo(
    () =>
      presentationTools.filter(
        (tool) => tool.metadata?.provider === "suitable",
      ),
    [presentationTools],
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

  async function refreshGmailStatus(successMessage?: string) {
    setLoadingGmail(true);
    setGmailError("");
    try {
      const status = await getGmailStatus();
      setGmailStatus(status);
      if (successMessage) {
        setMessageTone("success");
        setMessage(successMessage);
      }
    } catch {
      setGmailError("Falha ao carregar status do Gmail.");
    } finally {
      setLoadingGmail(false);
    }
  }

  async function refreshDriveStatus(successMessage?: string) {
    setLoadingDrive(true);
    setDriveError("");
    try {
      const status = await getGoogleDriveStatus();
      setDriveStatus(status);
      if (successMessage) {
        setMessageTone("success");
        setMessage(successMessage);
      }
    } catch {
      setDriveError("Falha ao carregar status do Google Drive.");
    } finally {
      setLoadingDrive(false);
    }
  }

  async function refreshSheetsStatus(successMessage?: string) {
    setLoadingSheets(true);
    setSheetsError("");
    try {
      const status = await getGoogleSheetsStatus();
      setSheetsStatus(status);
      if (successMessage) {
        setMessageTone("success");
        setMessage(successMessage);
      }
    } catch {
      setSheetsError("Falha ao carregar status do Google Sheets.");
    } finally {
      setLoadingSheets(false);
    }
  }

  async function refreshSuitableStatus(successMessage?: string) {
    setLoadingSuitable(true);
    setSuitableError("");
    try {
      const status = await getSuitableStatus();
      setSuitableStatus(status);
      if (successMessage) {
        setMessageTone("success");
        setMessage(successMessage);
      }
    } catch {
      setSuitableError("Falha ao carregar status da Suitable.");
    } finally {
      setLoadingSuitable(false);
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
    const isGmailReturn = ENABLE_GMAIL_INTEGRATION && integration === "gmail";
    const isGoogleDriveReturn = integration === "google_drive";
    const isGoogleSheetsReturn =
      ENABLE_GOOGLE_SHEETS_INTEGRATION && integration === "google_sheets";

    if (isGoogleCalendarReturn && status === "connected") {
      refreshCalendarStatus("Google Calendar conectado com sucesso.");
    } else if (isGoogleCalendarReturn && status === "error") {
      refreshCalendarStatus();
      setCalendarError("Falha ao conectar Google Calendar.");
    } else if (isGmailReturn && status === "connected") {
      if (ENABLE_GMAIL_INTEGRATION)
        refreshGmailStatus("Gmail conectado com sucesso.");
      refreshCalendarStatus();
    } else if (isGmailReturn && status === "error") {
      if (ENABLE_GMAIL_INTEGRATION) refreshGmailStatus();
      refreshCalendarStatus();
      if (ENABLE_GMAIL_INTEGRATION) setGmailError("Falha ao conectar Gmail.");
    } else if (isGoogleDriveReturn && status === "connected") {
      refreshDriveStatus("Google Drive conectado com sucesso.");
      refreshCalendarStatus();
      if (ENABLE_GMAIL_INTEGRATION) refreshGmailStatus();
    } else if (isGoogleDriveReturn && status === "error") {
      refreshDriveStatus();
      refreshCalendarStatus();
      if (ENABLE_GMAIL_INTEGRATION) refreshGmailStatus();
      setDriveError("Falha ao conectar Google Drive.");
    } else if (isGoogleSheetsReturn && status === "connected") {
      if (ENABLE_GOOGLE_SHEETS_INTEGRATION)
        refreshSheetsStatus("Google Sheets conectado com sucesso.");
      refreshCalendarStatus();
      if (ENABLE_GMAIL_INTEGRATION) refreshGmailStatus();
      refreshDriveStatus();
    } else if (isGoogleSheetsReturn && status === "error") {
      if (ENABLE_GOOGLE_SHEETS_INTEGRATION) refreshSheetsStatus();
      refreshCalendarStatus();
      if (ENABLE_GMAIL_INTEGRATION) refreshGmailStatus();
      refreshDriveStatus();
      if (ENABLE_GOOGLE_SHEETS_INTEGRATION)
        setSheetsError("Falha ao conectar Google Sheets.");
    } else {
      refreshCalendarStatus();
      if (ENABLE_GMAIL_INTEGRATION) refreshGmailStatus();
      refreshDriveStatus();
      if (ENABLE_GOOGLE_SHEETS_INTEGRATION) refreshSheetsStatus();
      refreshSuitableStatus();
    }

    if (
      isGoogleCalendarReturn ||
      isGmailReturn ||
      isGoogleDriveReturn ||
      isGoogleSheetsReturn
    ) {
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
  function connectGmail() {
    setGmailError("");
    try {
      window.location.href = getGmailConnectUrl();
    } catch {
      if (ENABLE_GMAIL_INTEGRATION) setGmailError("Falha ao conectar Gmail.");
    }
  }

  async function disconnectGmailAccount() {
    setGmailActionLoading(true);
    setGmailError("");
    try {
      const status = await disconnectGmail();
      setGmailStatus(status);
      setMessageTone("success");
      setMessage("Gmail desconectado.");
      await load();
    } catch {
      setGmailError("Falha ao desconectar Gmail.");
    } finally {
      setGmailActionLoading(false);
    }
  }

  function connectDrive() {
    setDriveError("");
    try {
      window.location.href = getGoogleDriveConnectUrl();
    } catch {
      setDriveError("Falha ao conectar Google Drive.");
    }
  }

  async function disconnectDriveAccount() {
    setDriveActionLoading(true);
    setDriveError("");
    try {
      const status = await disconnectGoogleDrive();
      setDriveStatus(status);
      setMessageTone("success");
      setMessage("Google Drive desconectado.");
      await load();
    } catch {
      setDriveError("Falha ao desconectar Google Drive.");
    } finally {
      setDriveActionLoading(false);
    }
  }

  function connectSheets() {
    setSheetsError("");
    try {
      window.location.href = getGoogleSheetsConnectUrl();
    } catch {
      if (ENABLE_GOOGLE_SHEETS_INTEGRATION)
        setSheetsError("Falha ao conectar Google Sheets.");
    }
  }

  async function disconnectSheetsAccount() {
    setSheetsActionLoading(true);
    setSheetsError("");
    try {
      const status = await disconnectGoogleSheets();
      setSheetsStatus(status);
      setMessageTone("success");
      setMessage("Google Sheets desconectado.");
      await load();
    } catch {
      setSheetsError("Falha ao desconectar Google Sheets.");
    } finally {
      setSheetsActionLoading(false);
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

  async function disconnectGoogleAccount() {
    setCalendarActionLoading(true);
    setGmailActionLoading(true);
    setDriveActionLoading(true);
    setSheetsActionLoading(true);
    setCalendarError("");
    setGmailError("");
    setDriveError("");
    setSheetsError("");
    try {
      await disconnectGoogle();
      await Promise.all([
        refreshCalendarStatus(),
        refreshGmailStatus(),
        refreshDriveStatus(),
        refreshSheetsStatus(),
      ]);
      setMessageTone("success");
      setMessage("Conta Google desconectada de Calendar, Drive, Sheets e Gmail.");
      await load();
    } catch {
      setCalendarError("Falha ao desconectar a conta Google.");
    } finally {
      setCalendarActionLoading(false);
      setGmailActionLoading(false);
      setDriveActionLoading(false);
      setSheetsActionLoading(false);
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

  async function connectSuitableAccount() {
    if (!suitableApiKey.trim()) {
      setSuitableError("Informe a SUITABLE_API_KEY do tenant.");
      setShowSuitableKeyField(true);
      return;
    }
    setSuitableActionLoading(true);
    setSuitableError("");
    try {
      const status = await connectSuitable(suitableApiKey.trim());
      setSuitableStatus(status);
      setSuitableApiKey("");
      setShowSuitableKeyField(false);
      setMessageTone("success");
      setMessage("Suitable conectada com API Key.");
      await load();
    } catch {
      setSuitableError("Falha ao conectar Suitable com a API Key informada.");
    } finally {
      setSuitableActionLoading(false);
    }
  }

  async function disconnectSuitableAccount() {
    setSuitableActionLoading(true);
    setSuitableError("");
    try {
      const status = await disconnectSuitable();
      setSuitableStatus(status);
      setMessageTone("success");
      setMessage("Suitable desconectada.");
      await load();
    } catch {
      setSuitableError("Falha ao desconectar Suitable.");
    } finally {
      setSuitableActionLoading(false);
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

  const isDriveConnected = driveStatus?.connected === true;
  const driveAccountEmail =
    typeof driveStatus?.metadata?.account_email === "string"
      ? driveStatus.metadata.account_email
      : "Nenhuma conta conectada";
  const isGmailConnected =
    ENABLE_GMAIL_INTEGRATION && gmailStatus?.connected === true;
  const gmailAccountEmail =
    typeof gmailStatus?.metadata?.account_email === "string"
      ? gmailStatus.metadata.account_email
      : "Nenhuma conta conectada";
  const isSheetsConnected =
    ENABLE_GOOGLE_SHEETS_INTEGRATION && sheetsStatus?.connected === true;
  const sheetsAccountEmail =
    typeof sheetsStatus?.metadata?.account_email === "string"
      ? sheetsStatus.metadata.account_email
      : "Nenhuma conta conectada";
  const isCalendarConnected = calendarStatus?.connected === true;
  const calendarAccountEmail =
    typeof calendarStatus?.metadata?.account_email === "string"
      ? calendarStatus.metadata.account_email
      : "Nenhuma conta conectada";

  const isSuitableConnected = suitableStatus?.connected === true;

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
                <button
                  type="button"
                  disabled={
                    calendarActionLoading ||
                    gmailActionLoading ||
                    driveActionLoading ||
                    sheetsActionLoading
                  }
                  onClick={() => disconnectGoogleAccount()}
                  className={dangerButtonClass}
                >
                  <XCircle size={16} /> Desconectar Google
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
          {ENABLE_GMAIL_INTEGRATION ? (
            <article className="mt-4 rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-sky-50/40 p-5 shadow-sm">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex gap-4">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-sky-100 text-sky-700">
                    <Mail size={22} />
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-slate-950">Gmail</h3>
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold ${isGmailConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                      >
                        {loadingGmail ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : isGmailConnected ? (
                          <CheckCircle2 size={12} />
                        ) : (
                          <XCircle size={12} />
                        )}
                        {loadingGmail
                          ? "Carregando..."
                          : isGmailConnected
                            ? "Conectado"
                            : "Não conectado"}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-slate-600">
                      Permita que a IA liste, busque, leia, crie rascunhos e
                      prepare envios de e-mail com confirmação obrigatória.
                    </p>
                    <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                      <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                        <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                          Provider
                        </b>
                        {gmailStatus?.provider || "gmail"}
                      </p>
                      <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                        <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                          Conta
                        </b>
                        {loadingGmail
                          ? "Consultando status..."
                          : gmailAccountEmail}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-56">
                  {isGmailConnected ? (
                    <button
                      type="button"
                      disabled={gmailActionLoading || loadingGmail}
                      onClick={() => disconnectGmailAccount()}
                      className={dangerButtonClass}
                    >
                      {gmailActionLoading ? (
                        <Loader2 size={16} className="animate-spin" />
                      ) : (
                        <XCircle size={16} />
                      )}{" "}
                      Desconectar
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={loadingGmail}
                      onClick={connectGmail}
                      className={primaryButtonClass}
                    >
                      <Mail size={16} /> Conectar Gmail
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={loadingGmail}
                    onClick={() => refreshGmailStatus()}
                    className={secondaryButtonClass}
                  >
                    Atualizar status
                  </button>
                </div>
              </div>
              <div className="mt-5 border-t border-sky-100 pt-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-slate-950">
                      Ferramentas disponíveis
                    </h4>
                    <p className="mt-1 text-xs font-semibold text-slate-500">
                      Origem: Gmail conectado
                    </p>
                  </div>
                  <span className="rounded-full bg-sky-50 px-3 py-1 text-xs font-bold text-sky-700 ring-1 ring-sky-100">
                    {gmailTools.length} ferramentas
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                  {gmailTools.map((tool) => (
                    <div
                      key={tool.id}
                      className="rounded-2xl border border-sky-100 bg-white/85 p-4 shadow-sm"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="text-sm font-bold text-slate-950">
                          {getToolDisplayName(tool)}
                        </p>
                        <StatusBadge active={tool.is_enabled} />
                      </div>
                      <p className="mt-3 text-xs font-semibold text-slate-500">
                        Origem: Gmail conectado
                      </p>
                      <p
                        className="mt-1 truncate font-mono text-[11px] text-slate-400"
                        title={tool.tool_name}
                      >
                        {tool.tool_name}
                      </p>
                    </div>
                  ))}
                  {gmailTools.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-sky-200 bg-white/70 px-4 py-5 text-sm font-semibold text-slate-500 sm:col-span-2 xl:col-span-5">
                      Conecte o Gmail para exibir as ferramentas oficiais de
                      e-mail.
                    </div>
                  ) : null}
                </div>
              </div>
              {gmailError ? (
                <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                  <AlertCircle size={16} /> {gmailError}
                </p>
              ) : null}
            </article>
          ) : null}
          <article className="mt-4 rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-blue-50/40 p-5 shadow-sm">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex gap-4">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-blue-100 text-blue-700">
                  <FolderOpen size={22} />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-bold text-slate-950">Google Drive</h3>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold ${isDriveConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                    >
                      {loadingDrive ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : isDriveConnected ? (
                        <CheckCircle2 size={12} />
                      ) : (
                        <XCircle size={12} />
                      )}
                      {loadingDrive
                        ? "Carregando..."
                        : isDriveConnected
                          ? "Conectado"
                          : "Não conectado"}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">
                    Permita que a IA liste, busque, leia e crie
                    arquivos/documentos no Drive.
                  </p>
                  <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                    <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                      <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                        Provider
                      </b>
                      {driveStatus?.provider || "google_drive"}
                    </p>
                    <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                      <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                        Conta
                      </b>
                      {loadingDrive
                        ? "Consultando status..."
                        : driveAccountEmail}
                    </p>
                  </div>
                </div>
              </div>
              <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-56">
                {isDriveConnected ? (
                  <button
                    type="button"
                    disabled={driveActionLoading || loadingDrive}
                    onClick={() => disconnectDriveAccount()}
                    className={dangerButtonClass}
                  >
                    {driveActionLoading ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <XCircle size={16} />
                    )}{" "}
                    Desconectar
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={loadingDrive}
                    onClick={connectDrive}
                    className={primaryButtonClass}
                  >
                    <FolderOpen size={16} /> Conectar Google Drive
                  </button>
                )}
                <button
                  type="button"
                  disabled={loadingDrive}
                  onClick={() => refreshDriveStatus()}
                  className={secondaryButtonClass}
                >
                  Atualizar status
                </button>
              </div>
            </div>
            <div className="mt-5 border-t border-blue-100 pt-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h4 className="text-sm font-bold text-slate-950">
                    Ferramentas disponíveis
                  </h4>
                  <p className="mt-1 text-xs font-semibold text-slate-500">
                    Origem: Google Drive conectado
                  </p>
                </div>
                <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-bold text-blue-700 ring-1 ring-blue-100">
                  {googleDriveTools.length} ferramentas
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                {googleDriveTools.map((tool) => (
                  <div
                    key={tool.id}
                    className="rounded-2xl border border-blue-100 bg-white/85 p-4 shadow-sm"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="text-sm font-bold text-slate-950">
                        {getToolDisplayName(tool)}
                      </p>
                      <StatusBadge active={tool.is_enabled} />
                    </div>
                    <p className="mt-3 text-xs font-semibold text-slate-500">
                      Origem: Google Drive conectado
                    </p>
                    <p
                      className="mt-1 truncate font-mono text-[11px] text-slate-400"
                      title={tool.tool_name}
                    >
                      {tool.tool_name}
                    </p>
                  </div>
                ))}
                {googleDriveTools.length === 0 ? (
                  <div className="rounded-2xl border border-dashed border-blue-200 bg-white/70 px-4 py-5 text-sm font-semibold text-slate-500 sm:col-span-2 xl:col-span-5">
                    Conecte o Google Drive para exibir as ferramentas oficiais:
                    google_drive_list_files, google_drive_search_files,
                    google_drive_read_file, google_drive_create_document e
                    google_drive_create_folder.
                  </div>
                ) : null}
              </div>
            </div>
            {driveError ? (
              <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                <AlertCircle size={16} /> {driveError}
              </p>
            ) : null}
          </article>
          {ENABLE_GOOGLE_SHEETS_INTEGRATION ? (
            <article className="mt-4 rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-green-50/40 p-5 shadow-sm">
              <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex gap-4">
                  <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-green-100 text-green-700">
                    <FolderOpen size={22} />
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-bold text-slate-950">
                        Google Sheets
                      </h3>
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold ${isSheetsConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                      >
                        {loadingSheets ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : isSheetsConnected ? (
                          <CheckCircle2 size={12} />
                        ) : (
                          <XCircle size={12} />
                        )}
                        {loadingSheets
                          ? "Carregando..."
                          : isSheetsConnected
                            ? "Conectado"
                            : "Não conectado"}
                      </span>
                    </div>
                    <p className="mt-2 text-sm leading-relaxed text-slate-600">
                      Permita que a IA liste, leia, crie e atualize planilhas
                      oficiais do Google Sheets.
                    </p>
                    <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                      <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                        <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                          Provider
                        </b>
                        {sheetsStatus?.provider || "google_sheets"}
                      </p>
                      <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                        <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                          Conta
                        </b>
                        {loadingSheets
                          ? "Consultando status..."
                          : sheetsAccountEmail}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-56">
                  {isSheetsConnected ? (
                    <button
                      type="button"
                      disabled={sheetsActionLoading || loadingSheets}
                      onClick={() => disconnectSheetsAccount()}
                      className={dangerButtonClass}
                    >
                      {sheetsActionLoading ? (
                        <Loader2 size={16} className="animate-spin" />
                      ) : (
                        <XCircle size={16} />
                      )}{" "}
                      Desconectar
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={loadingSheets}
                      onClick={connectSheets}
                      className={primaryButtonClass}
                    >
                      <FolderOpen size={16} /> Conectar Google Sheets
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={loadingSheets}
                    onClick={() => refreshSheetsStatus()}
                    className={secondaryButtonClass}
                  >
                    Atualizar status
                  </button>
                </div>
              </div>
              <div className="mt-5 border-t border-green-100 pt-5">
                <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-slate-950">
                      Ferramentas disponíveis
                    </h4>
                    <p className="mt-1 text-xs font-semibold text-slate-500">
                      Origem: Google Sheets conectado
                    </p>
                  </div>
                  <span className="rounded-full bg-green-50 px-3 py-1 text-xs font-bold text-green-700 ring-1 ring-green-100">
                    {googleSheetsTools.length} ferramentas
                  </span>
                </div>
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                  {googleSheetsTools.map((tool) => (
                    <div
                      key={tool.id}
                      className="rounded-2xl border border-green-100 bg-white/85 p-4 shadow-sm"
                    >
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <p className="text-sm font-bold text-slate-950">
                          {getToolDisplayName(tool)}
                        </p>
                        <StatusBadge active={tool.is_enabled} />
                      </div>
                      <p className="mt-3 text-xs font-semibold text-slate-500">
                        Origem: Google Sheets conectado
                      </p>
                      <p
                        className="mt-1 truncate font-mono text-[11px] text-slate-400"
                        title={tool.tool_name}
                      >
                        {tool.tool_name}
                      </p>
                    </div>
                  ))}
                  {googleSheetsTools.length === 0 ? (
                    <div className="rounded-2xl border border-dashed border-green-200 bg-white/70 px-4 py-5 text-sm font-semibold text-slate-500 sm:col-span-2 xl:col-span-5">
                      Conecte o Google Sheets para exibir as ferramentas
                      oficiais: google_sheets_list_spreadsheets,
                      google_sheets_read_sheet, google_sheets_append_row,
                      google_sheets_update_row e
                      google_sheets_create_spreadsheet.
                    </div>
                  ) : null}
                </div>
              </div>
              {sheetsError ? (
                <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                  <AlertCircle size={16} /> {sheetsError}
                </p>
              ) : null}
            </article>
          ) : null}
          <article className="mt-4 rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-purple-50/40 p-5 shadow-sm">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex gap-4">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-purple-100 text-purple-700">
                  <KeyRound size={22} />
                </span>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="font-bold text-slate-950">Suitable</h3>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-bold ${isSuitableConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                    >
                      {loadingSuitable ? (
                        <Loader2 size={12} className="animate-spin" />
                      ) : isSuitableConnected ? (
                        <CheckCircle2 size={12} />
                      ) : (
                        <XCircle size={12} />
                      )}
                      {loadingSuitable
                        ? "Carregando..."
                        : isSuitableConnected
                          ? "Conectado"
                          : "Não conectado"}
                    </span>
                  </div>
                  <p className="mt-2 text-sm leading-relaxed text-slate-600">
                    Permita que a IA valide a API Key e crie pedidos na
                    Suitable.
                  </p>
                  <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
                    <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                      <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                        Provider
                      </b>
                      {suitableStatus?.provider || "suitable"}
                    </p>
                    <p className="rounded-2xl bg-white/80 px-4 py-3 text-slate-600">
                      <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                        Autenticação
                      </b>
                      API Key manual
                    </p>
                  </div>
                  {!isSuitableConnected && showSuitableKeyField ? (
                    <div className="mt-4 space-y-2">
                      <span className={labelClass}>
                        SUITABLE_API_KEY do tenant
                      </span>
                      <input
                        className={inputClass}
                        type="password"
                        placeholder="Cole a API Key da Suitable"
                        value={suitableApiKey}
                        onChange={(event) =>
                          setSuitableApiKey(event.target.value)
                        }
                      />
                    </div>
                  ) : null}
                </div>
              </div>
              <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-56">
                {isSuitableConnected ? (
                  <button
                    type="button"
                    disabled={suitableActionLoading || loadingSuitable}
                    onClick={() => disconnectSuitableAccount()}
                    className={dangerButtonClass}
                  >
                    {suitableActionLoading ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <XCircle size={16} />
                    )}{" "}
                    Desconectar
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={loadingSuitable || suitableActionLoading}
                    onClick={() =>
                      showSuitableKeyField
                        ? connectSuitableAccount()
                        : setShowSuitableKeyField(true)
                    }
                    className={primaryButtonClass}
                  >
                    {suitableActionLoading ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <KeyRound size={16} />
                    )}{" "}
                    Conectar Suitable
                  </button>
                )}
                <button
                  type="button"
                  disabled={loadingSuitable}
                  onClick={() => refreshSuitableStatus()}
                  className={secondaryButtonClass}
                >
                  Atualizar status
                </button>
              </div>
            </div>
            <div className="mt-5 border-t border-purple-100 pt-5">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h4 className="text-sm font-bold text-slate-950">
                    Ferramentas disponíveis
                  </h4>
                  <p className="mt-1 text-xs font-semibold text-slate-500">
                    Origem: Suitable conectado
                  </p>
                </div>
                <span className="rounded-full bg-purple-50 px-3 py-1 text-xs font-bold text-purple-700 ring-1 ring-purple-100">
                  {suitableTools.length} ferramentas
                </span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                {(suitableTools.length
                  ? suitableTools
                  : [
                      {
                        id: "suitable_check_key",
                        tool_name: "suitable_check_key",
                        display_name: "Validar API Key",
                        description: "",
                        input_schema: {},
                        is_enabled: false,
                        server_id: "",
                        metadata: { provider: "suitable" },
                      },
                      {
                        id: "suitable_create_order",
                        tool_name: "suitable_create_order",
                        display_name: "Criar pedido",
                        description: "",
                        input_schema: {},
                        is_enabled: false,
                        server_id: "",
                        metadata: { provider: "suitable" },
                      },
                    ]
                ).map((tool) => (
                  <div
                    key={tool.id}
                    className="rounded-2xl border border-purple-100 bg-white/85 p-4 shadow-sm"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="text-sm font-bold text-slate-950">
                        {getToolDisplayName(tool)}
                      </p>
                      <StatusBadge active={tool.is_enabled} />
                    </div>
                    <p className="mt-3 text-xs font-semibold text-slate-500">
                      Origem: Suitable conectado
                    </p>
                    <p
                      className="mt-1 truncate font-mono text-[11px] text-slate-400"
                      title={tool.tool_name}
                    >
                      {tool.tool_name}
                    </p>
                  </div>
                ))}
              </div>
            </div>
            {suitableError ? (
              <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                <AlertCircle size={16} /> {suitableError}
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
