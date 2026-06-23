"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  Bell,
  Building2,
  CalendarDays,
  CheckCircle2,
  FolderOpen,
  Clock3,
  CreditCard,
  Globe2,
  KeyRound,
  Layers3,
  Loader2,
  LockKeyhole,
  LogOut,
  Mail,
  MessageSquareText,
  Pencil,
  Plus,
  Save,
  ShieldCheck,
  Smartphone,
  User,
  UsersRound,
  XCircle,
} from "lucide-react";
import ProvidersTab from "@/components/settings/whatsapp-business/ProvidersTab";
import TemplatesTab from "@/components/settings/whatsapp-business/TemplatesTab";
import PipelineSettingsTab from "@/components/settings/PipelineSettingsTab";
import { ClientDateTime } from "@/components/settings/whatsapp-business/ui";
import {
  activateWhatsAppProvider,
  createTemplate,
  createWhatsAppProvider,
  deactivateWorkspaceUser,
  deleteWhatsAppProvider,
  disconnectGoogleCalendar,
  disconnectGoogleDrive,
  disconnectGoogleSheets,
  getAccountMe,
  getAccountSecurity,
  getGoogleCalendarConnectUrl,
  getGoogleCalendarStatus,
  getGoogleDriveConnectUrl,
  getGoogleDriveStatus,
  getGoogleSheetsConnectUrl,
  getGoogleSheetsStatus,
  getSystemSettings,
  inviteWorkspaceUser,
  listTemplates,
  listWhatsAppProviders,
  listWorkspaceUsers,
  revokeAccountSession,
  revokeOtherAccountSessions,
  submitTemplate,
  syncTemplates,
  testWhatsAppProvider,
  updateAccountPassword,
  updateAccountPreferences,
  updateAccountProfile,
  updateSystemSettings,
  updateWhatsAppProvider,
  updateWorkspaceUser,
} from "@/lib/api";
import { ENABLE_GOOGLE_SHEETS_INTEGRATION } from "@/lib/features";
import {
  AccountMe,
  AccountPreferences,
  AccountProfile,
  AccountSecurity,
  GoogleCalendarConnectionStatus,
  SystemSettingsPayload,
  WhatsAppProvider,
  WhatsAppTemplate,
  WorkspaceUser,
} from "@/lib/types";
import {
  friendlyToMeta,
  renderExample,
  validateMetaVariables,
} from "@/lib/templateVariableMapper";
import { SettingsTabId } from "./SettingsSidebar";
import { AccountTabId } from "@/components/account/AccountSidebar";

const INITIAL_FORM: SystemSettingsPayload = {
  token: "",
  phone_number_id: "",
  webhook_url: "",
  webhook_status: "inactive",
  system_name: "",
  language: "pt-BR",
  workspace_profile: "private_sales",
};
const baseProviderForm = {
  provider_type: "meta_cloud",
  display_name: "",
  waba_id: "",
  phone_number_id: "",
  business_id: "",
  access_token: "",
  api_key: "",
  connection_type: "cloud_api",
  coexistence_enabled: false,
};
const baseTemplateForm = {
  name: "",
  category: "utility",
  language: "pt_BR",
  provider_id: "",
  body_text: "",
  friendly_body_text: "",
  footer_text: "",
  variables_json: [] as any[],
};
const whatsappTabs = [
  { id: "overview", label: "Visão Geral", icon: Layers3 },
  { id: "connection", label: "Conexões", icon: Building2 },
  { id: "templates", label: "Templates", icon: MessageSquareText },
  { id: "api-keys", label: "API Keys", icon: KeyRound },
  { id: "webhooks", label: "Webhooks", icon: Globe2 },
] as const;
const roleLabels: Record<string, string> = {
  owner: "Administrador",
  admin: "Admin",
  member: "Membro",
  analyst: "Analista",
  viewer: "Leitura",
};

export default function SettingsContent({
  activeTab,
}: {
  activeTab: SettingsTabId | AccountTabId;
}) {
  if (activeTab === "whatsapp-business") return <WhatsAppBusinessConsole />;
  if (activeTab === "pipeline") return <PipelineSettingsTab />;
  if (activeTab === "profile") return <ProfileTab />;
  if (activeTab === "preferences") return <PreferencesTab />;
  if (activeTab === "security") return <SecurityTab />;
  if (activeTab === "users") return <UsersTab />;
  if (activeTab === "permissions") return <PermissionsTab />;
  if (activeTab === "billing") return <BillingTab />;
  if (activeTab === "integrations") return <IntegrationsTab />;
  return null;
}

function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-3xl border border-[color:var(--surface-border)] bg-white/95 shadow-[0_18px_44px_-34px_rgba(15,23,42,0.75)] ${className}`}
    >
      {children}
    </div>
  );
}

function HubHeader({
  icon: Icon,
  eyebrow,
  title,
  description,
}: {
  icon: any;
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="relative border-b border-slate-100 bg-gradient-to-br from-white via-slate-50 to-emerald-50/50 p-6 md:p-8">
      <div className="pointer-events-none absolute right-8 top-6 h-24 w-24 rounded-full bg-emerald-300/20 blur-2xl" />
      <p className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-white/80 px-3 py-1 text-xs font-semibold text-emerald-700 shadow-sm">
        <Icon size={14} /> {eyebrow}
      </p>
      <h2 className="mt-4 text-2xl font-semibold tracking-tight text-slate-950">
        {title}
      </h2>
      <p className="mt-2 max-w-3xl text-sm leading-relaxed text-slate-600">
        {description}
      </p>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
        {label}
      </span>
      <div className="mt-2">{children}</div>
    </label>
  );
}

function inputClass() {
  return "w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-emerald-400 focus:ring-4 focus:ring-emerald-100";
}
function fmtDate(value?: string | null) {
  return value
    ? new Date(value).toLocaleString("pt-BR")
    : "Ainda não registrado";
}

function passwordRules(value: string) {
  return [
    ["Mínimo 8 caracteres", value.length >= 8],
    ["Maiúscula", /[A-Z]/.test(value)],
    ["Minúscula", /[a-z]/.test(value)],
    ["Número", /\d/.test(value)],
    ["Especial", /[^A-Za-z0-9]/.test(value)],
  ] as const;
}

function PasswordChecklist({ value }: { value: string }) {
  return (
    <div className="grid gap-2 rounded-2xl border border-slate-200 bg-slate-50 p-3 text-xs sm:grid-cols-2">
      {passwordRules(value).map(([label, ok]) => (
        <span
          key={label}
          className={`inline-flex items-center gap-2 font-semibold ${ok ? "text-emerald-700" : "text-slate-500"}`}
        >
          {ok ? <CheckCircle2 size={14} /> : <XCircle size={14} />} {label}
        </span>
      ))}
    </div>
  );
}

function initials(name?: string) {
  return (name || "WA")
    .split(" ")
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function useAccountData() {
  const [data, setData] = useState<AccountMe | null>(null);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState("");
  const refresh = async () => {
    setLoading(true);
    try {
      setData(await getAccountMe());
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    refresh();
  }, []);
  return { data, setData, loading, toast, setToast, refresh };
}

function ProfileTab() {
  const { data, setData, loading, toast, setToast } = useAccountData();
  const [form, setForm] = useState<Partial<AccountProfile>>({});
  useEffect(() => {
    if (data?.profile) setForm(data.profile);
  }, [data]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const updated = await updateAccountProfile(form);
    setData(data ? { ...data, profile: updated } : data);
    setToast("Perfil atualizado com sucesso.");
    setTimeout(() => setToast(""), 3000);
  };
  return (
    <Card>
      <HubHeader
        icon={User}
        eyebrow="Identity Center"
        title="Meu Perfil"
        description="Atualize os dados que aparecem para o time, auditoria e atendimento do workspace."
      />
      <form
        onSubmit={save}
        className="grid gap-6 p-5 md:grid-cols-[220px_minmax(0,1fr)] md:p-6"
      >
        <div className="rounded-3xl border border-slate-200 bg-slate-50 p-5 text-center">
          <div className="mx-auto flex h-24 w-24 items-center justify-center overflow-hidden rounded-3xl bg-slate-950 text-2xl font-bold text-white">
            {form.avatar_url ? (
              <img
                src={form.avatar_url}
                alt=""
                className="h-full w-full object-cover"
              />
            ) : (
              initials(form.name)
            )}
          </div>
          <p className="mt-4 text-sm font-semibold text-slate-950">
            {form.name || "Carregando..."}
          </p>
          <p className="text-xs text-slate-500">
            {roleLabels[form.role || "owner"] || form.role}
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="Nome">
            <input
              className={inputClass()}
              value={form.name || ""}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </Field>
          <Field label="Email">
            <input
              className={inputClass()}
              type="email"
              value={form.email || ""}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              required
            />
          </Field>
          <Field label="Avatar URL">
            <input
              className={inputClass()}
              value={form.avatar_url || ""}
              onChange={(e) => setForm({ ...form, avatar_url: e.target.value })}
              placeholder="https://..."
            />
          </Field>
          <Field label="Empresa">
            <input
              className={inputClass()}
              value={form.company || ""}
              onChange={(e) => setForm({ ...form, company: e.target.value })}
            />
          </Field>
          <Field label="Cargo">
            <input
              className={inputClass()}
              value={form.job_title || ""}
              onChange={(e) => setForm({ ...form, job_title: e.target.value })}
              placeholder="Head de Operações"
            />
          </Field>
          <div className="flex items-end">
            <button
              disabled={loading}
              className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-slate-950/15"
            >
              <Save size={16} /> Salvar alterações
            </button>
          </div>
          {toast && (
            <p className="md:col-span-2 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">
              {toast}
            </p>
          )}
        </div>
      </form>
    </Card>
  );
}

function PreferencesTab() {
  const { data, setData, toast, setToast } = useAccountData();
  const [form, setForm] = useState<AccountPreferences>({
    language: "pt-BR",
    timezone: "America/Sao_Paulo",
    email_notifications: true,
    whatsapp_notifications: true,
  });
  useEffect(() => {
    if (data?.preferences) setForm(data.preferences);
  }, [data]);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    const updated = await updateAccountPreferences(form);
    setData(data ? { ...data, preferences: updated } : data);
    setToast("Preferências salvas.");
    setTimeout(() => setToast(""), 3000);
  };
  return (
    <Card>
      <HubHeader
        icon={Bell}
        eyebrow="Personalização"
        title="Preferências"
        description="Configure idioma, timezone e canais de notificação para sua operação diária."
      />
      <form onSubmit={save} className="grid gap-5 p-5 md:grid-cols-2 md:p-6">
        <Field label="Idioma">
          <select
            className={inputClass()}
            value={form.language}
            onChange={(e) => setForm({ ...form, language: e.target.value })}
          >
            <option value="pt-BR">Português (Brasil)</option>
            <option value="en-US">English (US)</option>
            <option value="es-ES">Español</option>
          </select>
        </Field>
        <Field label="Timezone">
          <select
            className={inputClass()}
            value={form.timezone}
            onChange={(e) => setForm({ ...form, timezone: e.target.value })}
          >
            <option value="America/Sao_Paulo">America/São Paulo</option>
            <option value="America/New_York">America/New York</option>
            <option value="Europe/Lisbon">Europe/Lisbon</option>
            <option value="UTC">UTC</option>
          </select>
        </Field>
        <Toggle
          icon={Mail}
          title="Notificações por email"
          desc="Alertas de convites, segurança e campanhas."
          checked={form.email_notifications}
          onChange={(v) => setForm({ ...form, email_notifications: v })}
        />
        <Toggle
          icon={Smartphone}
          title="Notificações WhatsApp"
          desc="Avisos operacionais e handoffs críticos."
          checked={form.whatsapp_notifications}
          onChange={(v) => setForm({ ...form, whatsapp_notifications: v })}
        />
        <button className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white">
          <Save size={16} /> Salvar preferências
        </button>
        {toast && (
          <p className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">
            {toast}
          </p>
        )}
      </form>
    </Card>
  );
}

function Toggle({
  icon: Icon,
  title,
  desc,
  checked,
  onChange,
}: {
  icon: any;
  title: string;
  desc: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`flex items-center justify-between gap-4 rounded-3xl border p-5 text-left ${checked ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-white"}`}
    >
      <span className="flex gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white text-emerald-600">
          <Icon size={18} />
        </span>
        <span>
          <span className="block text-sm font-semibold text-slate-950">
            {title}
          </span>
          <span className="text-sm text-slate-500">{desc}</span>
        </span>
      </span>
      <span
        className={`h-6 w-11 rounded-full p-1 transition ${checked ? "bg-emerald-500" : "bg-slate-300"}`}
      >
        <span
          className={`block h-4 w-4 rounded-full bg-white transition ${checked ? "translate-x-5" : ""}`}
        />
      </span>
    </button>
  );
}

function SecurityTab() {
  const [security, setSecurity] = useState<AccountSecurity | null>(null);
  const [toast, setToast] = useState("");
  const [password, setPassword] = useState({
    current_password: "",
    new_password: "",
    confirm_password: "",
  });
  const refresh = async () => setSecurity(await getAccountSecurity());
  useEffect(() => {
    refresh();
  }, []);
  const save = async (event: FormEvent) => {
    event.preventDefault();
    await updateAccountPassword(password);
    setPassword({
      current_password: "",
      new_password: "",
      confirm_password: "",
    });
    await refresh();
    setToast("Senha alterada com sucesso.");
    setTimeout(() => setToast(""), 3000);
  };
  const revoke = async (sessionId: string) => {
    await revokeAccountSession(sessionId);
    await refresh();
    setToast("Sessão encerrada.");
    setTimeout(() => setToast(""), 3000);
  };
  const revokeOthers = async () => {
    const result = await revokeOtherAccountSessions();
    await refresh();
    setToast(`${result.revoked_count} sessão(ões) encerrada(s).`);
    setTimeout(() => setToast(""), 3000);
  };
  const metrics = [
    ["Último login", fmtDate(security?.last_login_at), Clock3],
    ["IP do último login", security?.last_login_ip || "Sem registro", Globe2],
    [
      "Sessões ativas",
      String(security?.active_sessions_count ?? 0),
      Smartphone,
    ],
    [
      "Tentativas bloqueadas",
      String(security?.blocked_login_attempts ?? 0),
      ShieldCheck,
    ],
    ["Turnstile", security?.turnstile_status || "Ativo", CheckCircle2],
    ["Proteção", security?.protection_status || "Protegido", LockKeyhole],
  ];
  return (
    <Card>
      <HubHeader
        icon={LockKeyhole}
        eyebrow="Trust & Security"
        title="Segurança"
        description="Recursos enterprise reais: política forte de senha, sessões ativas revogáveis, Turnstile e trilha operacional."
      />
      <div className="grid gap-6 p-5 md:p-6">
        {toast && (
          <p className="rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm font-semibold text-emerald-700">
            {toast}
          </p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-slate-950">
              Dashboard de segurança
            </h3>
            <p className="text-sm text-slate-500">
              Indicadores operacionais atualizados a partir de sessões e
              auditoria.
            </p>
          </div>
          <Link
            href="/dashboard/security/audit"
            className="rounded-2xl border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
          >
            Abrir audit trail
          </Link>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {metrics.map(([label, value, Icon]: any) => (
            <div
              key={label}
              className="rounded-3xl border border-slate-200 bg-white p-5 shadow-sm"
            >
              <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
                <Icon size={14} /> {label}
              </p>
              <p className="mt-3 text-lg font-semibold text-slate-950">
                {value}
              </p>
            </div>
          ))}
        </div>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_420px]">
          <form
            onSubmit={save}
            className="rounded-3xl border border-slate-200 p-5"
          >
            <h3 className="flex items-center gap-2 text-lg font-semibold text-slate-950">
              <KeyRound size={18} /> Alterar senha
            </h3>
            <div className="mt-5 grid gap-4">
              <Field label="Senha atual">
                <input
                  className={inputClass()}
                  type="password"
                  value={password.current_password}
                  onChange={(e) =>
                    setPassword({
                      ...password,
                      current_password: e.target.value,
                    })
                  }
                />
              </Field>
              <Field label="Nova senha">
                <input
                  className={inputClass()}
                  type="password"
                  value={password.new_password}
                  onChange={(e) =>
                    setPassword({ ...password, new_password: e.target.value })
                  }
                />
              </Field>
              <PasswordChecklist value={password.new_password} />
              <Field label="Confirmar nova senha">
                <input
                  className={inputClass()}
                  type="password"
                  value={password.confirm_password}
                  onChange={(e) =>
                    setPassword({
                      ...password,
                      confirm_password: e.target.value,
                    })
                  }
                />
              </Field>
              <button className="rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white">
                Atualizar senha
              </button>
            </div>
          </form>
          <div className="rounded-3xl border border-slate-200 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="font-semibold text-slate-950">Sessões ativas</p>
                <p className="text-sm text-slate-500">
                  Encerre remotamente dispositivos que não reconhece.
                </p>
              </div>
              <button
                type="button"
                onClick={revokeOthers}
                className="rounded-2xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                Encerrar outras
              </button>
            </div>
            <div className="mt-4 space-y-3">
              {security?.active_sessions.map((s) => (
                <div key={s.id} className="rounded-2xl bg-slate-50 p-4 text-sm">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <b className="text-slate-950">{s.device}</b>
                      {s.is_current && (
                        <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                          Atual
                        </span>
                      )}
                      <p className="mt-1 text-slate-500">
                        IP {s.ip_address || "desconhecido"} · Última atividade{" "}
                        {fmtDate(s.last_seen_at)}
                      </p>
                    </div>
                    <button
                      type="button"
                      disabled={s.is_current}
                      onClick={() => revoke(s.id)}
                      className="inline-flex items-center gap-1 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <LogOut size={13} /> Encerrar
                    </button>
                  </div>
                </div>
              ))}
              {!security?.active_sessions.length && (
                <p className="rounded-2xl bg-slate-50 p-4 text-sm text-slate-500">
                  Nenhuma sessão ativa encontrada.
                </p>
              )}
            </div>
          </div>
        </div>
        <div className="rounded-3xl border border-slate-200 p-5">
          <p className="font-semibold text-slate-950">Histórico de segurança</p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {security?.history.map((item) => (
              <div key={item.event} className="rounded-2xl bg-slate-50 p-4">
                <p className="text-sm font-semibold text-slate-950">
                  {item.event}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {item.description}
                </p>
                <p className="mt-3 text-xs font-semibold text-slate-400">
                  {fmtDate(item.created_at)}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

function UsersTab() {
  const [users, setUsers] = useState<WorkspaceUser[]>([]);
  const [invite, setInvite] = useState({ name: "", email: "", role: "member" });
  const [toast, setToast] = useState("");
  const refresh = async () => setUsers(await listWorkspaceUsers());
  useEffect(() => {
    refresh();
  }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    await inviteWorkspaceUser(invite);
    setInvite({ name: "", email: "", role: "member" });
    await refresh();
    setToast("Convite criado com status pendente.");
    setTimeout(() => setToast(""), 3000);
  };
  const changeRole = async (user: WorkspaceUser, role: string) => {
    await updateWorkspaceUser(user.id, { role });
    await refresh();
  };
  const deactivate = async (user: WorkspaceUser) => {
    await deactivateWorkspaceUser(user.id);
    await refresh();
  };
  return (
    <Card>
      <HubHeader
        icon={UsersRound}
        eyebrow="Admin Console"
        title="Usuários"
        description="Tabela real do workspace com administrador atual, convites e ações de edição/desativação."
      />
      <div className="p-5 md:p-6">
        <form
          onSubmit={submit}
          className="grid gap-3 rounded-3xl border border-slate-200 bg-slate-50 p-4 md:grid-cols-[1fr_1fr_180px_auto]"
        >
          <input
            className={inputClass()}
            placeholder="Nome do usuário"
            value={invite.name}
            onChange={(e) => setInvite({ ...invite, name: e.target.value })}
          />
          <input
            className={inputClass()}
            placeholder="email@empresa.com"
            value={invite.email}
            onChange={(e) => setInvite({ ...invite, email: e.target.value })}
          />
          <select
            className={inputClass()}
            value={invite.role}
            onChange={(e) => setInvite({ ...invite, role: e.target.value })}
          >
            <option value="member">Membro</option>
            <option value="admin">Admin</option>
            <option value="analyst">Analista</option>
            <option value="viewer">Leitura</option>
          </select>
          <button className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white">
            <Plus size={16} /> Convidar usuário
          </button>
        </form>
        {toast && (
          <p className="mt-3 text-sm font-semibold text-emerald-700">{toast}</p>
        )}
        <div className="mt-5 overflow-hidden rounded-3xl border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase tracking-[0.14em] text-slate-500">
              <tr>
                <th className="p-4">Nome</th>
                <th>Email</th>
                <th>Função</th>
                <th>Status</th>
                <th>Último acesso</th>
                <th>Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users.map((user) => (
                <tr key={user.id} className="bg-white">
                  <td className="p-4 font-semibold text-slate-950">
                    {user.name}
                  </td>
                  <td className="text-slate-600">{user.email}</td>
                  <td>
                    <select
                      className="rounded-xl border border-slate-200 px-3 py-2 text-sm"
                      value={user.role}
                      onChange={(e) => changeRole(user, e.target.value)}
                    >
                      <option value="owner">Administrador</option>
                      <option value="admin">Admin</option>
                      <option value="member">Membro</option>
                      <option value="analyst">Analista</option>
                      <option value="viewer">Leitura</option>
                    </select>
                  </td>
                  <td>
                    <span
                      className={`rounded-full px-3 py-1 text-xs font-semibold ${user.status === "active" ? "bg-emerald-50 text-emerald-700" : user.status === "invited" ? "bg-blue-50 text-blue-700" : "bg-slate-100 text-slate-500"}`}
                    >
                      {user.status}
                    </span>
                  </td>
                  <td className="text-slate-500">
                    {fmtDate(user.last_access_at)}
                  </td>
                  <td>
                    <button
                      onClick={() => changeRole(user, user.role)}
                      className="mr-2 inline-flex items-center gap-1 text-xs font-semibold text-slate-700"
                    >
                      <Pencil size={13} /> Editar
                    </button>
                    <button
                      onClick={() => deactivate(user)}
                      className="text-xs font-semibold text-rose-600"
                    >
                      Desativar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Card>
  );
}

function PermissionsTab() {
  const roles = [
    {
      name: "Owner",
      desc: "Controle total do workspace, billing, integrações e RBAC.",
    },
    {
      name: "Admin",
      desc: "Gerencia usuários, fluxos, campanhas e configurações operacionais.",
    },
    {
      name: "Member",
      desc: "Opera inbox, CRM, campanhas e automações liberadas.",
    },
    {
      name: "Viewer",
      desc: "Acesso somente leitura para auditoria e liderança.",
    },
  ];
  return (
    <Card>
      <HubHeader
        icon={ShieldCheck}
        eyebrow="Governança"
        title="Permissões"
        description="RBAC permanece no roadmap, mas a política alvo já está clara: papéis por módulo, ações críticas e escopos de workspace."
      />
      <div className="grid gap-4 p-5 md:grid-cols-4 md:p-6">
        {roles.map((r) => (
          <div key={r.name} className="rounded-3xl border border-slate-200 p-5">
            <p className="text-lg font-semibold text-slate-950">{r.name}</p>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              {r.desc}
            </p>
          </div>
        ))}
      </div>
    </Card>
  );
}
function BillingTab() {
  const limits = [
    "1.000 mensagens/mês",
    "1 workspace",
    "Até 5 usuários",
    "WhatsApp Business básico",
  ];
  return (
    <Card>
      <HubHeader
        icon={CreditCard}
        eyebrow="Revenue Operations"
        title="Billing"
        description="Resumo financeiro sem integração de cobrança: plano atual, status e limites operacionais da POC."
      />
      <div className="grid gap-5 p-5 md:grid-cols-[320px_1fr] md:p-6">
        <div className="rounded-3xl bg-slate-950 p-6 text-white">
          <p className="text-sm text-emerald-200">Plano atual</p>
          <h3 className="mt-2 text-3xl font-bold">Starter POC</h3>
          <p className="mt-4 inline-flex rounded-full bg-emerald-400/15 px-3 py-1 text-sm font-semibold text-emerald-200">
            Status: Ativo
          </p>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {limits.map((limit) => (
            <div
              key={limit}
              className="flex items-center gap-3 rounded-2xl border border-slate-200 p-4"
            >
              <CheckCircle2 className="text-emerald-500" size={18} />
              <span className="text-sm font-semibold text-slate-700">
                {limit}
              </span>
            </div>
          ))}
        </div>
      </div>
    </Card>
  );
}
function IntegrationsTab() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const integrations = [
    {
      name: "WhatsApp Business",
      status: "Configurável",
      icon: Smartphone,
      desc: "Providers, tokens, WABA e templates oficiais.",
    },
    {
      name: "Webhooks",
      status: "Disponível",
      icon: Globe2,
      desc: "Eventos de entrada e callbacks para automações.",
    },
    {
      name: "APIs",
      status: "Operacional",
      icon: Layers3,
      desc: "Endpoints protegidos por tenant e token.",
    },
  ];
  const [calendarStatus, setCalendarStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingCalendar, setLoadingCalendar] = useState(true);
  const [calendarActionLoading, setCalendarActionLoading] = useState(false);
  const [calendarMessage, setCalendarMessage] = useState("");
  const [calendarError, setCalendarError] = useState("");
  const [driveStatus, setDriveStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingDrive, setLoadingDrive] = useState(true);
  const [driveActionLoading, setDriveActionLoading] = useState(false);
  const [driveMessage, setDriveMessage] = useState("");
  const [driveError, setDriveError] = useState("");
  const [sheetsStatus, setSheetsStatus] =
    useState<GoogleCalendarConnectionStatus | null>(null);
  const [loadingSheets, setLoadingSheets] = useState(true);
  const [sheetsActionLoading, setSheetsActionLoading] = useState(false);
  const [sheetsMessage, setSheetsMessage] = useState("");
  const [sheetsError, setSheetsError] = useState("");

  const refreshCalendarStatus = async (successMessage?: string) => {
    setLoadingCalendar(true);
    setCalendarError("");
    try {
      const status = await getGoogleCalendarStatus();
      setCalendarStatus(status);
      setCalendarMessage(successMessage || "");
    } catch {
      setCalendarError("Falha ao carregar status do Google Calendar.");
      setCalendarMessage("");
    } finally {
      setLoadingCalendar(false);
    }
  };

  useEffect(() => {
    const integration = searchParams.get("integration");
    const status = searchParams.get("status");
    const isGoogleCalendarReturn = integration === "google_calendar";
    const isGoogleDriveReturn = integration === "google_drive";
    const isGoogleSheetsReturn =
      ENABLE_GOOGLE_SHEETS_INTEGRATION && integration === "google_sheets";

    if (isGoogleCalendarReturn && status === "connected") {
      refreshCalendarStatus("Google Calendar conectado com sucesso.");
    } else if (isGoogleCalendarReturn && status === "error") {
      refreshCalendarStatus();
      setCalendarError("Falha ao conectar Google Calendar.");
      setCalendarMessage("");
    } else {
      refreshCalendarStatus();
    }
    if (isGoogleDriveReturn && status === "connected")
      refreshDriveStatus("Google Drive conectado com sucesso.");
    else if (isGoogleDriveReturn && status === "error") {
      refreshDriveStatus();
      setDriveError("Falha ao conectar Google Drive.");
      setDriveMessage("");
    } else refreshDriveStatus();
    if (isGoogleSheetsReturn && status === "connected")
      refreshSheetsStatus("Google Sheets conectado com sucesso.");
    else if (isGoogleSheetsReturn && status === "error") {
      refreshSheetsStatus();
      setSheetsError("Falha ao conectar Google Sheets.");
      setSheetsMessage("");
    } else if (ENABLE_GOOGLE_SHEETS_INTEGRATION) refreshSheetsStatus();

    if (isGoogleCalendarReturn || isGoogleDriveReturn || isGoogleSheetsReturn) {
      const nextParams = new URLSearchParams(searchParams.toString());
      nextParams.delete("integration");
      nextParams.delete("status");
      const query = nextParams.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, {
        scroll: false,
      });
    }
  }, [pathname, router, searchParams]);

  const connectCalendar = () => {
    setCalendarError("");
    try {
      window.location.href = getGoogleCalendarConnectUrl();
    } catch {
      setCalendarError("Falha ao conectar Google Calendar.");
    }
  };

  const disconnectCalendar = async () => {
    setCalendarActionLoading(true);
    setCalendarError("");
    try {
      const status = await disconnectGoogleCalendar();
      setCalendarStatus(status);
      setCalendarMessage("Não conectado");
    } catch {
      setCalendarError("Falha ao desconectar Google Calendar");
    } finally {
      setCalendarActionLoading(false);
    }
  };

  const refreshDriveStatus = async (successMessage?: string) => {
    setLoadingDrive(true);
    setDriveError("");
    try {
      const status = await getGoogleDriveStatus();
      setDriveStatus(status);
      setDriveMessage(successMessage || "");
    } catch {
      setDriveError("Falha ao carregar status do Google Drive.");
      setDriveMessage("");
    } finally {
      setLoadingDrive(false);
    }
  };

  const connectDrive = () => {
    setDriveError("");
    try {
      window.location.href = getGoogleDriveConnectUrl();
    } catch {
      setDriveError("Falha ao conectar Google Drive.");
    }
  };
  const disconnectDrive = async () => {
    setDriveActionLoading(true);
    setDriveError("");
    try {
      const status = await disconnectGoogleDrive();
      setDriveStatus(status);
      setDriveMessage("Não conectado");
    } catch {
      setDriveError("Falha ao desconectar Google Drive");
    } finally {
      setDriveActionLoading(false);
    }
  };
  const refreshSheetsStatus = async (successMessage?: string) => {
    setLoadingSheets(true);
    setSheetsError("");
    try {
      const status = await getGoogleSheetsStatus();
      setSheetsStatus(status);
      setSheetsMessage(successMessage || "");
    } catch {
      setSheetsError("Falha ao carregar status do Google Sheets.");
      setSheetsMessage("");
    } finally {
      setLoadingSheets(false);
    }
  };
  const connectSheets = () => {
    setSheetsError("");
    try {
      window.location.href = getGoogleSheetsConnectUrl();
    } catch {
      setSheetsError("Falha ao conectar Google Sheets.");
    }
  };
  const disconnectSheets = async () => {
    setSheetsActionLoading(true);
    setSheetsError("");
    try {
      const status = await disconnectGoogleSheets();
      setSheetsStatus(status);
      setSheetsMessage("Não conectado");
    } catch {
      setSheetsError("Falha ao desconectar Google Sheets");
    } finally {
      setSheetsActionLoading(false);
    }
  };

  const isConnected = calendarStatus?.connected === true;
  const isDriveConnected = driveStatus?.connected === true;
  const isSheetsConnected =
    ENABLE_GOOGLE_SHEETS_INTEGRATION && sheetsStatus?.connected === true;
  const sheetsAccountEmail =
    typeof sheetsStatus?.metadata?.account_email === "string"
      ? sheetsStatus.metadata.account_email
      : "Nenhuma conta conectada";
  const driveAccountEmail =
    typeof driveStatus?.metadata?.account_email === "string"
      ? driveStatus.metadata.account_email
      : "Nenhuma conta conectada";
  const accountEmail =
    typeof calendarStatus?.metadata?.account_email === "string"
      ? calendarStatus.metadata.account_email
      : "Nenhuma conta conectada";

  return (
    <Card>
      <HubHeader
        icon={Layers3}
        eyebrow="Integration Catalog"
        title="Integrações"
        description="Visão executiva dos conectores essenciais do workspace com status visual."
      />
      <div className="grid gap-4 p-5 md:grid-cols-3 md:p-6">
        {integrations.map((item) => (
          <div
            key={item.name}
            className="rounded-3xl border border-slate-200 p-5"
          >
            <div className="flex items-center justify-between">
              <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-600">
                <item.icon size={20} />
              </span>
              <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700">
                {item.status}
              </span>
            </div>
            <h3 className="mt-5 text-lg font-semibold text-slate-950">
              {item.name}
            </h3>
            <p className="mt-2 text-sm text-slate-600">{item.desc}</p>
          </div>
        ))}
      </div>
      <div className="border-t border-slate-100 p-5 md:p-6">
        <div className="mb-4">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">
            Apps conectados ao Wazza
          </p>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">
            Conecte apps ao workspace
          </h3>
        </div>
        <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-emerald-50/40 p-5 shadow-sm">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex gap-4">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-100 text-emerald-700">
                <CalendarDays size={22} />
              </span>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-base font-semibold text-slate-950">
                    Google Calendar
                  </h4>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${isConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
                  >
                    {loadingCalendar ? (
                      <Loader2 size={12} className="animate-spin" />
                    ) : isConnected ? (
                      <CheckCircle2 size={12} />
                    ) : (
                      <XCircle size={12} />
                    )}
                    {loadingCalendar
                      ? "Carregando..."
                      : isConnected
                        ? "Conectado"
                        : "Não conectado"}
                  </span>
                </div>
                <p className="mt-2 text-sm text-slate-600">
                  Permita que a IA consulte disponibilidade e eventos sem expor
                  tokens no frontend.
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
                    {loadingCalendar ? "Consultando status..." : accountEmail}
                  </p>
                </div>
              </div>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-56">
              {isConnected ? (
                <button
                  type="button"
                  disabled={calendarActionLoading || loadingCalendar}
                  onClick={disconnectCalendar}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-red-200 bg-white px-5 py-3 text-sm font-semibold text-red-600 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
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
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-slate-950/15 transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <CalendarDays size={16} /> Conectar Google Calendar
                </button>
              )}
              <button
                type="button"
                disabled={loadingCalendar}
                onClick={() => refreshCalendarStatus()}
                className="rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Atualizar status
              </button>
            </div>
          </div>
          {calendarMessage && (
            <p
              className={`mt-4 inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-sm font-semibold ${isConnected ? "border border-emerald-200 bg-emerald-50 text-emerald-700" : "border border-slate-200 bg-white text-slate-600"}`}
            >
              <CheckCircle2 size={16} /> {calendarMessage}
            </p>
          )}
          {calendarError && (
            <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              <AlertCircle size={16} /> {calendarError}
            </p>
          )}
        </div>
        <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-blue-50/40 p-5 shadow-sm">
          <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex gap-4">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-blue-100 text-blue-700">
                <FolderOpen size={22} />
              </span>
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h4 className="text-base font-semibold text-slate-950">
                    Google Drive
                  </h4>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${isDriveConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
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
                <p className="mt-2 text-sm text-slate-600">
                  Permita que a IA liste, busque, leia e crie arquivos sem expor
                  tokens no frontend.
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
                    {loadingDrive ? "Consultando status..." : driveAccountEmail}
                  </p>
                </div>
              </div>
            </div>
            <div className="flex w-full flex-col gap-2 sm:w-auto sm:min-w-56">
              {isDriveConnected ? (
                <button
                  type="button"
                  disabled={driveActionLoading || loadingDrive}
                  onClick={disconnectDrive}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-red-200 bg-white px-5 py-3 text-sm font-semibold text-red-600 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
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
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-slate-950/15 transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <FolderOpen size={16} /> Conectar Google Drive
                </button>
              )}
              <button
                type="button"
                disabled={loadingDrive}
                onClick={() => refreshDriveStatus()}
                className="rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
              >
                Atualizar status
              </button>
            </div>
          </div>
          {driveMessage && (
            <p
              className={`mt-4 inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-sm font-semibold ${isDriveConnected ? "border border-emerald-200 bg-emerald-50 text-emerald-700" : "border border-slate-200 bg-white text-slate-600"}`}
            >
              <CheckCircle2 size={16} /> {driveMessage}
            </p>
          )}
          {driveError && (
            <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
              <AlertCircle size={16} /> {driveError}
            </p>
          )}
        </div>
        {ENABLE_GOOGLE_SHEETS_INTEGRATION ? (
          <div className="rounded-3xl border border-slate-200 bg-gradient-to-br from-white via-slate-50 to-green-50/40 p-5 shadow-sm">
            <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
              <div className="flex gap-4">
                <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-green-100 text-green-700">
                  <FolderOpen size={22} />
                </span>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h4 className="text-base font-semibold text-slate-950">
                      Google Sheets
                    </h4>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-semibold ${isSheetsConnected ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-600"}`}
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
                  <p className="mt-2 text-sm text-slate-600">
                    Permita que a IA liste, leia, crie e atualize planilhas.
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
                <button
                  type="button"
                  disabled={loadingSheets || isSheetsConnected}
                  onClick={connectSheets}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-slate-950/15 transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  <FolderOpen size={16} /> Conectar Google Sheets
                </button>
                <button
                  type="button"
                  disabled={
                    sheetsActionLoading || loadingSheets || !isSheetsConnected
                  }
                  onClick={disconnectSheets}
                  className="inline-flex items-center justify-center gap-2 rounded-2xl border border-red-200 bg-white px-5 py-3 text-sm font-semibold text-red-600 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {sheetsActionLoading ? (
                    <Loader2 size={16} className="animate-spin" />
                  ) : (
                    <XCircle size={16} />
                  )}{" "}
                  Desconectar
                </button>
                <button
                  type="button"
                  disabled={loadingSheets}
                  onClick={() => refreshSheetsStatus()}
                  className="rounded-2xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Atualizar status
                </button>
              </div>
            </div>
            <div className="mt-4 rounded-2xl bg-white/80 px-4 py-3 text-sm text-slate-600">
              <b className="block text-xs uppercase tracking-[0.12em] text-slate-400">
                Ferramentas oficiais
              </b>
              <ul className="mt-2 grid gap-1 font-mono text-xs text-slate-700 sm:grid-cols-2">
                <li>google_sheets_list_spreadsheets</li>
                <li>google_sheets_read_sheet</li>
                <li>google_sheets_append_row</li>
                <li>google_sheets_update_row</li>
                <li>google_sheets_create_spreadsheet</li>
              </ul>
            </div>
            {sheetsMessage && (
              <p
                className={`mt-4 inline-flex items-center gap-2 rounded-2xl px-4 py-3 text-sm font-semibold ${isSheetsConnected ? "border border-emerald-200 bg-emerald-50 text-emerald-700" : "border border-slate-200 bg-white text-slate-600"}`}
              >
                <CheckCircle2 size={16} /> {sheetsMessage}
              </p>
            )}
            {sheetsError && (
              <p className="mt-4 inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm font-semibold text-red-700">
                <AlertCircle size={16} /> {sheetsError}
              </p>
            )}
          </div>
        ) : null}
      </div>
    </Card>
  );
}

function WhatsAppBusinessConsole() {
  const [tab, setTab] =
    useState<(typeof whatsappTabs)[number]["id"]>("overview");
  const [toast, setToast] = useState("");
  const [loading, setLoading] = useState(false);
  const [form, setForm] = useState<SystemSettingsPayload>(INITIAL_FORM);
  const [providers, setProviders] = useState<WhatsAppProvider[]>([]);
  const [templates, setTemplates] = useState<WhatsAppTemplate[]>([]);
  const [providerForm, setProviderForm] = useState(baseProviderForm);
  const [templateForm, setTemplateForm] = useState(baseTemplateForm);
  const [templateError, setTemplateError] = useState("");
  const refresh = async () => {
    setProviders(await listWhatsAppProviders());
    setTemplates(await listTemplates());
  };

  useEffect(() => {
    (async () => {
      const data = await getSystemSettings();
      setForm({ ...INITIAL_FORM, ...data });
      await refresh();
    })();
  }, []);

  const stats = useMemo(() => {
    const connectedProviders = providers.filter(
      (p) =>
        p.is_active ||
        p.connection_status === "connected" ||
        p.status === "connected" ||
        p.status === "active",
    );

    return {
      activeProviders: connectedProviders.length,
      approvedTemplates: templates.filter((t) => t.status === "approved")
        .length,
      pendingTemplates: templates.filter(
        (t) => t.status === "pending" || t.status === "submitted",
      ).length,
      status: connectedProviders.length > 0 ? "Operacional" : "Sem conexão",
      lastSyncAt:
        providers
          .map(
            (p) =>
              p.last_validation_at ||
              p?.metadata_json?.last_sync_at ||
              p.last_connection_check_at ||
              p.updated_at,
          )
          .filter(Boolean)
          .sort(
            (a, b) =>
              new Date(b as string).getTime() - new Date(a as string).getTime(),
          )[0] ?? null,
    };
  }, [providers, templates]);

  const validateTemplate = () => {
    if (!/^[a-z0-9_]+$/.test(templateForm.name))
      return "Nome do template deve ter lowercase e underscores.";
    const mapped = friendlyToMeta(
      templateForm.friendly_body_text || templateForm.body_text || "",
    );
    if (mapped.errors.length)
      return `${mapped.errors[0]}\nUse uma variável da lista ou remova o marcador.`;
    return validateMetaVariables(mapped.bodyText);
  };
  const parseFriendlyError = (error: unknown, fallback: string) => {
    if (!(error instanceof Error)) return fallback;
    const match = error.message.match(/HTTP \d+:\s*([\s\S]*)$/);
    if (!match?.[1]) return fallback;
    try {
      const parsed = JSON.parse(match[1]);
      const detailPayload = parsed?.detail;
      const detail =
        typeof detailPayload === "string"
          ? detailPayload
          : detailPayload?.detail;
      const metaError = detailPayload?.meta_error;
      if (detail && metaError)
        return `Erro ao enviar template: ${detail}\n${metaError}`;
      if (detail) return `Erro ao enviar template: ${detail}`;
    } catch {
      return fallback;
    }
    return fallback;
  };
  async function run(action: () => Promise<void>, ok: string, err: string) {
    setLoading(true);
    try {
      await action();
      setToast(ok);
    } catch (error) {
      setToast(parseFriendlyError(error, err));
    } finally {
      setLoading(false);
      setTimeout(() => setToast(""), 5000);
    }
  }

  const saveSettings = (e: FormEvent, ok: string) =>
    run(
      async () => {
        e.preventDefault();
        await updateSystemSettings({
          ...form,
          token: form.token || null,
          phone_number_id: form.phone_number_id || null,
          webhook_url: form.webhook_url || null,
        });
      },
      ok,
      "Falha ao salvar configurações",
    );
  const overviewItems = [
    { label: "Status", value: stats.status, icon: Layers3 },
    {
      label: "Providers",
      value: `${stats.activeProviders} ativos`,
      icon: Building2,
    },
    {
      label: "Templates",
      value: `${stats.approvedTemplates} aprovados`,
      icon: CheckCircle2,
    },
    { label: "Sync", value: stats.lastSyncAt, icon: MessageSquareText },
  ];

  return (
    <div className="w-full min-w-0 space-y-4">
      <div className="flex min-h-[52px] flex-col justify-center gap-2 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 px-4 py-3 shadow-[0_12px_30px_-28px_rgba(15,23,42,0.75)] sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight text-slate-950">
            WhatsApp
          </h1>
          <p className="mt-0.5 text-xs text-slate-500">
            Configurações operacionais do canal.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-600">
          <span
            className={`rounded-full px-2.5 py-1 ${stats.status === "Operacional" ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700"}`}
          >
            {stats.status}
          </span>
          <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-600">
            {providers.length} conexões
          </span>
        </div>
      </div>

      {toast && (
        <div className="rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-sm">
          {toast}
        </div>
      )}

      <div className="grid w-full min-w-0 grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
        {[
          ["Providers ativos", String(stats.activeProviders), Building2],
          [
            "Templates aprovados",
            String(stats.approvedTemplates),
            CheckCircle2,
          ],
          ["Templates pendentes", String(stats.pendingTemplates), Clock3],
          ["Status geral", stats.status, Layers3],
          ["Último sync", stats.lastSyncAt, MessageSquareText],
        ].map(([label, value, Icon]: any) => (
          <div
            key={label}
            className="group rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-3 shadow-[0_12px_30px_-28px_rgba(15,23,42,0.75)] transition-all duration-300 hover:-translate-y-0.5 hover:border-emerald-200 hover:shadow-[0_20px_36px_-26px_rgba(16,185,129,0.35)]"
          >
            <p className="inline-flex items-center gap-1 text-xs font-medium text-slate-500">
              <Icon size={12} />
              {label}
            </p>
            <p className="mt-1.5 truncate text-lg font-semibold tracking-tight text-slate-900">
              {label === "Último sync" ? (
                <ClientDateTime value={value} fallback="Nunca sincronizado" />
              ) : (
                value
              )}
            </p>
          </div>
        ))}
      </div>

      <div className="flex w-full min-w-0 flex-wrap gap-2 rounded-2xl border border-[color:var(--surface-border)] bg-white/90 p-2 shadow-[0_10px_24px_-24px_rgba(15,23,42,0.8)] backdrop-blur">
        {whatsappTabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium transition-all duration-200 ${tab === id ? "bg-slate-900 text-white shadow-md shadow-slate-900/20" : "text-slate-600 hover:bg-slate-100/90 hover:text-slate-900 active:scale-[0.99]"}`}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
          <Card className="overflow-hidden">
            <div className="border-b border-slate-100 px-5 py-4">
              <h2 className="text-base font-semibold text-slate-950">
                Visão Geral
              </h2>
              <p className="mt-1 text-sm text-slate-500">
                Resumo técnico do canal e atalhos de configuração.
              </p>
            </div>
            <div className="grid gap-3 p-5 sm:grid-cols-2">
              {overviewItems.map(({ label, value, icon: Icon }) => (
                <div
                  key={label}
                  className="rounded-2xl border border-slate-200 bg-slate-50 p-4"
                >
                  <p className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">
                    <Icon size={13} />
                    {label}
                  </p>
                  <p className="mt-2 text-sm font-semibold text-slate-950">
                    {label === "Sync" ? (
                      <ClientDateTime
                        value={value as string | null}
                        fallback="Nunca sincronizado"
                      />
                    ) : (
                      (value as string)
                    )}
                  </p>
                </div>
              ))}
            </div>
          </Card>
          <Card className="p-5">
            <h3 className="text-sm font-semibold text-slate-950">
              Ações rápidas
            </h3>
            <div className="mt-4 grid gap-2">
              <button
                type="button"
                onClick={() => setTab("connection")}
                className="rounded-xl border border-slate-200 px-4 py-3 text-left text-sm font-semibold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50/50"
              >
                Gerenciar conexões
              </button>
              <button
                type="button"
                onClick={() => setTab("templates")}
                className="rounded-xl border border-slate-200 px-4 py-3 text-left text-sm font-semibold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50/50"
              >
                Revisar templates
              </button>
              <button
                type="button"
                onClick={() => setTab("api-keys")}
                className="rounded-xl border border-slate-200 px-4 py-3 text-left text-sm font-semibold text-slate-700 transition hover:border-emerald-200 hover:bg-emerald-50/50"
              >
                Atualizar credenciais
              </button>
            </div>
          </Card>
        </div>
      )}
      {tab === "connection" && (
        <ProvidersTab
          providers={providers}
          form={providerForm}
          setForm={setProviderForm}
          loading={loading}
          onSubmit={(e: FormEvent) =>
            run(
              async () => {
                e.preventDefault();
                await createWhatsAppProvider(providerForm);
                setProviderForm(baseProviderForm);
                await refresh();
              },
              "Conexão salva com sucesso",
              "Falha ao salvar conexão",
            )
          }
          onTest={(id: string) =>
            run(
              async () => {
                await testWhatsAppProvider(id);
                await refresh();
              },
              "Conexão testada com sucesso",
              "Falha ao testar conexão",
            )
          }
          onActivate={(id: string) =>
            run(
              async () => {
                await activateWhatsAppProvider(id);
                await refresh();
              },
              "Conexão ativada com sucesso",
              "Falha ao ativar conexão",
            )
          }
          onDelete={(id: string) =>
            run(
              async () => {
                await deleteWhatsAppProvider(id);
                await refresh();
              },
              "Conexão removida com sucesso",
              "Falha ao remover conexão",
            )
          }
          onEdit={(id: string, payload: Record<string, unknown>) =>
            run(
              async () => {
                await updateWhatsAppProvider(id, payload);
                await testWhatsAppProvider(id);
                await refresh();
              },
              "Conexão atualizada",
              "Falha ao atualizar conexão",
            )
          }
          onMetaConnected={refresh}
        />
      )}
      {tab === "templates" && (
        <TemplatesTab
          templates={templates}
          providers={providers}
          form={templateForm}
          setForm={setTemplateForm}
          error={templateError}
          loading={loading}
          onSubmit={(e: FormEvent) =>
            run(
              async () => {
                e.preventDefault();
                const msg = validateTemplate();
                setTemplateError(msg);
                if (msg) throw new Error(msg);
                const mapped = friendlyToMeta(
                  templateForm.friendly_body_text ||
                    templateForm.body_text ||
                    "",
                );
                await createTemplate({
                  ...templateForm,
                  provider_id: templateForm.provider_id || null,
                  body_text: mapped.bodyText,
                  body_raw_meta: mapped.bodyText,
                  body_preview: renderExample(
                    mapped.bodyText,
                    mapped.variables,
                  ),
                  variables_json: mapped.variables,
                });
                setTemplateForm(baseTemplateForm);
                await refresh();
              },
              "Template criado com sucesso",
              "Falha ao criar template",
            )
          }
          onSync={() =>
            run(
              async () => {
                await syncTemplates();
                await refresh();
              },
              "Sincronização concluída",
              "Erro ao sincronizar templates",
            )
          }
          onSubmitTemplate={(id: string) =>
            run(
              async () => {
                await submitTemplate(id);
                await refresh();
              },
              "Template enviado para aprovação",
              "Falha ao enviar template",
            )
          }
        />
      )}
      {tab === "api-keys" && (
        <form
          onSubmit={(e: FormEvent) =>
            saveSettings(e, "Credenciais salvas com sucesso")
          }
          className="w-full min-w-0 space-y-4 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)]"
        >
          <div>
            <h2 className="text-base font-semibold text-slate-950">API Keys</h2>
            <p className="mt-1 text-sm text-slate-500">
              Token e identificador do número usados pelo runtime.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <input
              type="password"
              value={form.token ?? ""}
              onChange={(e) =>
                setForm((p) => ({ ...p, token: e.target.value }))
              }
              placeholder="Token atual (ENV fallback preservado)"
              className="premium-input w-full"
            />
            <input
              value={form.phone_number_id ?? ""}
              onChange={(e) =>
                setForm((p) => ({ ...p, phone_number_id: e.target.value }))
              }
              placeholder="Phone Number ID"
              className="premium-input w-full"
            />
          </div>
          <button disabled={loading} className="primary-button">
            Salvar credenciais
          </button>
        </form>
      )}
      {tab === "webhooks" && (
        <form
          onSubmit={(e: FormEvent) =>
            saveSettings(e, "Webhook salvo com sucesso")
          }
          className="w-full min-w-0 space-y-4 rounded-2xl border border-[color:var(--surface-border)] bg-white/95 p-5 shadow-[0_14px_34px_-30px_rgba(15,23,42,0.85)]"
        >
          <div>
            <h2 className="text-base font-semibold text-slate-950">Webhooks</h2>
            <p className="mt-1 text-sm text-slate-500">
              Endpoint de recebimento e status operacional.
            </p>
          </div>
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_220px]">
            <input
              value={form.webhook_url ?? ""}
              onChange={(e) =>
                setForm((p) => ({ ...p, webhook_url: e.target.value }))
              }
              placeholder="URL do webhook"
              className="premium-input w-full"
            />
            <select
              value={form.webhook_status ?? "inactive"}
              onChange={(e) =>
                setForm((p) => ({ ...p, webhook_status: e.target.value }))
              }
              className="premium-input w-full"
            >
              <option value="active">Ativo</option>
              <option value="inactive">Inativo</option>
              <option value="pending">Pendente</option>
            </select>
          </div>
          <button disabled={loading} className="primary-button">
            Salvar webhook
          </button>
        </form>
      )}
    </div>
  );
}
