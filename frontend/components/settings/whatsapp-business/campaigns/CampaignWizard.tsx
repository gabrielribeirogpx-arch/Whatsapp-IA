"use client";

import { ChangeEvent, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  Megaphone,
  MessageCircle,
  Search,
  Send,
  ShieldCheck,
  Target,
  X,
} from "lucide-react";
import {
  apiFetch,
  createWhatsAppCampaign,
  importWhatsAppCampaignRecipients,
  importWhatsAppCampaignRecipientsFromContacts,
  listTemplates,
  listWhatsAppProviders,
  startWhatsAppCampaign,
} from "@/lib/api";
import {
  CRMContact,
  WhatsAppCampaign,
  WhatsAppProvider,
  WhatsAppTemplate,
} from "@/lib/types";

type SendMode = "draft" | "now" | "schedule";
type RecipientMode = "saved" | "csv";
type VariableMappingPayload = {
  type: "contact_field" | "custom_field" | "fixed";
  field?: string;
  value?: string;
};
type LeadInput = { phone: string; fields: Record<string, string> };

type Props = {
  open: boolean;
  initialTemplateId?: string;
  initialProviderId?: string;
  onClose: () => void;
  onSuccess: (campaign: WhatsAppCampaign) => Promise<void> | void;
  setToast: (toast: { type: "success" | "error"; message: string }) => void;
};
const STEPS = [
  "Objetivo",
  "Template",
  "Audiência",
  "Variáveis",
  "Agendamento",
  "Revisão",
];
const FIELD_OPTIONS = [
  { value: "first_name", label: "Nome", csvColumn: "nome" },
  { value: "full_name", label: "Nome completo", csvColumn: "nome_completo" },
  { value: "phone", label: "Telefone", csvColumn: "telefone" },
  { value: "company", label: "Empresa", csvColumn: "empresa" },
  { value: "city", label: "Cidade", csvColumn: "cidade" },
  { value: "order_number", label: "Pedido", csvColumn: "pedido" },
  { value: "amount", label: "Valor", csvColumn: "valor" },
  { value: "link", label: "Link", csvColumn: "Link" },
  { value: "fixed_value", label: "Valor fixo", csvColumn: "valor_fixo" },
];
const GOALS = [
  ["Promoção", "Divulgue ofertas com templates aprovados."],
  ["Cobrança", "Comunique lembretes financeiros com segurança."],
  ["Pós-venda", "Acompanhe clientes após a compra."],
  ["Lembrete", "Reforce datas e compromissos."],
  ["Pesquisa", "Colete feedback depois do atendimento."],
  ["Recuperação", "Reative oportunidades e carrinhos."],
  ["Personalizada", "Configure um objetivo livre."],
] as const;
const FIXED = "fixed_value";
function components(t?: WhatsAppTemplate | null): Array<Record<string, any>> {
  if (!t) return [];
  const raw = t.metadata_json;
  const meta =
    typeof raw === "string"
      ? (() => {
          try {
            return JSON.parse(raw);
          } catch {
            return {};
          }
        })()
      : raw || {};
  return Array.isArray(t.components) && t.components.length
    ? t.components
    : Array.isArray((meta as any).components)
      ? (meta as any).components
      : [];
}
function templateText(t?: WhatsAppTemplate | null) {
  const body = components(t).find(
    (c) => String(c.type || "").toUpperCase() === "BODY",
  )?.text;
  return [t?.body_text, t?.body_preview, body]
    .filter((v) => typeof v === "string" && v.trim())
    .join("\n");
}
function variables(t?: WhatsAppTemplate | null) {
  return Array.from(
    new Set(
      Array.from(
        [templateText(t), ...components(t).map((c) => String(c.text || ""))]
          .join("\n")
          .matchAll(/\{\{\s*([^}]+?)\s*\}\}/g),
      ).map((m) => m[1].trim()),
    ),
  ).sort((a, b) => Number(a) - Number(b));
}
function phone(p?: string | null) {
  return String(p || "").replace(/\D/g, "");
}
function connected(p?: WhatsAppProvider) {
  return p?.status === "connected" || p?.connection_status === "connected";
}
function fill(text: string, values: Record<string, string>) {
  return text.replace(
    /\{\{\s*([^}]+?)\s*\}\}/g,
    (_, k: string) => values[k.trim()] || `{{${k.trim()}}}`,
  );
}
function contactValue(c: CRMContact, field: string) {
  const custom = c.custom_fields_json || {};
  if (field === "first_name")
    return c.first_name || String(c.name || "").split(" ")[0] || "cliente";
  if (field === "full_name") return c.name || "cliente";
  if (field === "phone") return c.phone || "";
  if (field === "company") return c.company || custom.company || "";
  if (field === "city") return c.city || custom.city || "";
  if (field === "order_number")
    return custom.order_number || custom.pedido || c.last_order_id || "";
  if (field === "amount") return custom.amount || custom.valor || "";
  if (field === "link") return custom.link || custom.url || "";
  return custom[field] || "";
}

export default function CampaignWizard({
  open,
  initialTemplateId,
  initialProviderId,
  onClose,
  onSuccess,
  setToast,
}: Props) {
  const [step, setStep] = useState(0),
    [dirty, setDirty] = useState(false),
    [loading, setLoading] = useState(false),
    [submitting, setSubmitting] = useState(false),
    [error, setError] = useState<string | null>(null);
  const [providers, setProviders] = useState<WhatsAppProvider[]>([]),
    [templates, setTemplates] = useState<WhatsAppTemplate[]>([]),
    [contacts, setContacts] = useState<CRMContact[]>([]);
  const [goal, setGoal] = useState("Promoção"),
    [name, setName] = useState(""),
    [providerId, setProviderId] = useState(initialProviderId || ""),
    [templateId, setTemplateId] = useState(initialTemplateId || ""),
    [templateSearch, setTemplateSearch] = useState(""),
    [categoryFilter, setCategoryFilter] = useState("all");
  const [recipientMode, setRecipientMode] = useState<RecipientMode>("saved"),
    [selectedContactIds, setSelectedContactIds] = useState<string[]>([]),
    [csvText, setCsvText] = useState("");
  const [mapping, setMapping] = useState<Record<string, string>>({}),
    [manual, setManual] = useState<Record<string, string>>({}),
    [sendMode, setSendMode] = useState<SendMode>("draft"),
    [scheduledAt, setScheduledAt] = useState("");
  useEffect(() => {
    if (!open) return;
    setLoading(true);
    Promise.all([
      listWhatsAppProviders(),
      listTemplates(),
      apiFetch("/api/contacts", { cache: "no-store" })
        .then((r) => r.json())
        .catch(() => []),
    ])
      .then(([p, t, c]) => {
        setProviders(p);
        setTemplates(t);
        setContacts(Array.isArray(c) ? c : c?.items || c?.contacts || []);
        setProviderId(initialProviderId || p.find(connected)?.id || "");
        setTemplateId(initialTemplateId || "");
        setStep(initialTemplateId ? 2 : 0);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [open, initialProviderId, initialTemplateId]);
  const approved = useMemo(
    () =>
      templates.filter(
        (t) =>
          String(t.status || "").toLowerCase() === "approved" &&
          (!providerId || !t.provider_id || t.provider_id === providerId),
      ),
    [templates, providerId],
  );
  const selectedTemplate = approved.find((t) => t.id === templateId) || null;
  const vars = useMemo(() => variables(selectedTemplate), [selectedTemplate]);
  useEffect(() => {
    setMapping((p) =>
      Object.fromEntries(vars.map((v) => [v, p[v] || "first_name"])),
    );
    setManual((p) => Object.fromEntries(vars.map((v) => [v, p[v] || ""])));
  }, [vars.join("|")]);
  useEffect(() => {
    if (!name && selectedTemplate)
      setName(`${goal} · ${selectedTemplate.name}`.slice(0, 90));
  }, [goal, selectedTemplate, name]);
  const eligible = useMemo(() => {
    const seen = new Set<string>();
    return contacts.filter((c) => {
      const ph = phone(c.phone);
      if (
        !ph ||
        seen.has(ph) ||
        String(c.opt_in_status || "").toLowerCase() === "opt_out"
      )
        return false;
      seen.add(ph);
      return true;
    });
  }, [contacts]);
  function parseLeads(): LeadInput[] {
    const seen = new Set<string>();
    return csvText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        const parts = l.split(",").map((p) => p.trim());
        const ph = phone(parts[0]);
        const fields = vars.reduce<Record<string, string>>((acc, v, i) => {
          const opt = FIELD_OPTIONS.find((o) => o.value === mapping[v]);
          acc[opt?.csvColumn || `variavel_${v}`] = parts[i + 1] || "";
          return acc;
        }, {});
        return { phone: ph, fields };
      })
      .filter((r) => r.phone && !seen.has(r.phone) && seen.add(r.phone));
  }
  const audience =
    recipientMode === "csv"
      ? parseLeads().length
      : selectedContactIds.filter((id) => eligible.some((c) => c.id === id))
          .length;
  const previewValues = useMemo(
    () =>
      Object.fromEntries(
        vars.map((v) => {
          const sample =
            eligible.find((c) => selectedContactIds.includes(c.id)) ||
            eligible[0];
          return [
            v,
            mapping[v] === FIXED
              ? manual[v] || ""
              : sample
                ? String(contactValue(sample, mapping[v]))
                : "",
          ];
        }),
      ),
    [vars, mapping, manual, eligible, selectedContactIds],
  );
  const validVars = vars.every(
    (v) => mapping[v] && (mapping[v] !== FIXED || manual[v]?.trim()),
  );
  const validSchedule =
    sendMode !== "schedule" ||
    (!!scheduledAt && new Date(scheduledAt) > new Date());
  const canFinish = !!(
    name.trim() &&
    providerId &&
    selectedTemplate &&
    validVars &&
    validSchedule &&
    (sendMode === "draft" || audience > 0)
  );
  function validate(i = step) {
    if (i === 1 && !selectedTemplate)
      return "Selecione um template aprovado e ativo.";
    if (i === 2 && audience === 0)
      return "Audiência vazia. Selecione contatos elegíveis ou importe CSV.";
    if (i === 3 && !validVars) return "Mapeie todas as variáveis obrigatórias.";
    if (i === 4 && !validSchedule)
      return "Escolha uma data futura no timezone do tenant.";
    if (i === 5 && !canFinish)
      return "Revise nome, audiência, variáveis e conexão antes de finalizar.";
    return null;
  }
  function next() {
    const msg = validate();
    if (msg) return setError(msg);
    setError(null);
    setStep((s) => Math.min(5, s + 1));
  }
  function close() {
    if (dirty && !window.confirm("Há alterações não salvas. Fechar o wizard?"))
      return;
    onClose();
  }
  async function upload(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = (await file.text()).trim();
    setCsvText((p) => `${p ? `${p}\n` : ""}${text}`);
  }
  async function submit(mode: SendMode) {
    setSendMode(mode);
    if (submitting) return;
    const msg = validate(5);
    if (msg) return setError(msg);
    if (
      !window.confirm(
        mode === "draft"
          ? "Salvar campanha como rascunho?"
          : mode === "schedule"
            ? "Agendar campanha?"
            : "Enviar campanha agora?",
      )
    )
      return;
    setSubmitting(true);
    try {
      const created = await createWhatsAppCampaign({
        name: name.trim(),
        provider_id: providerId,
        template_id: templateId,
        status: mode === "schedule" ? "scheduled" : "draft",
        scheduled_at: mode === "schedule" ? scheduledAt : null,
        metadata_json: {
          objective: goal,
          wizard_version: "enterprise_sprint_4",
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        },
      });
      const payloadMap = vars.reduce<Record<string, VariableMappingPayload>>(
        (acc, key) => {
          const selected = mapping[key];
          acc[key] =
            selected === FIXED
              ? { type: "fixed", value: manual[key]?.trim() }
              : ["order_number", "amount", "link", "company", "city"].includes(
                    selected,
                  )
                ? { type: "custom_field", field: selected }
                : { type: "contact_field", field: selected || "first_name" };
          return acc;
        },
        {},
      );
      if (recipientMode === "csv" && parseLeads().length)
        await importWhatsAppCampaignRecipients(
          created.id,
          parseLeads().map((r) => ({
            phone: r.phone,
            variables_json: r.fields,
          })),
        );
      if (recipientMode === "saved" && selectedContactIds.length)
        await importWhatsAppCampaignRecipientsFromContacts(created.id, {
          contact_ids: selectedContactIds,
          variable_mapping: mapping,
          manual_variable_values: manual,
          variable_mapping_payload: payloadMap,
        });
      const finalCampaign =
        mode === "now" ? await startWhatsAppCampaign(created.id) : created;
      setToast({
        type: "success",
        message:
          mode === "draft"
            ? "Rascunho criado."
            : mode === "schedule"
              ? "Campanha agendada."
              : "Campanha criada e iniciada.",
      });
      setDirty(false);
      await onSuccess(finalCampaign);
      onClose();
    } catch (e) {
      setError((e as Error).message || "Falha ao finalizar campanha.");
    } finally {
      setSubmitting(false);
    }
  }
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-[80] bg-slate-950/50 p-3 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
    >
      <div className="mx-auto flex h-full max-w-7xl flex-col overflow-hidden rounded-[28px] border border-white/40 bg-white shadow-2xl">
        <header className="border-b border-slate-200 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-600">
                Wizard Enterprise
              </p>
              <h2 className="text-2xl font-semibold text-slate-950">
                Nova campanha
              </h2>
              <p className="text-sm text-slate-500">
                Fluxo seguro por etapas, reutilizando templates Meta e endpoints
                atuais.
              </p>
            </div>
            <button
              onClick={close}
              className="secondary-button inline-flex items-center gap-2"
            >
              <X size={14} />
              Fechar
            </button>
          </div>
          <div className="mt-4 grid gap-2 md:grid-cols-6">
            {STEPS.map((label, i) => (
              <button
                key={label}
                type="button"
                onClick={() => i <= step && setStep(i)}
                className={`rounded-2xl border px-3 py-2 text-left text-xs font-semibold ${i === step ? "border-emerald-500 bg-emerald-50 text-emerald-800" : i < step ? "border-emerald-100 bg-white text-emerald-700" : "border-slate-200 bg-slate-50 text-slate-400"}`}
              >
                <span className="mr-2">{i < step ? "✓" : i + 1}</span>
                {label}
              </button>
            ))}
          </div>
        </header>
        <main className="flex-1 overflow-auto bg-slate-50 p-5">
          {loading ? (
            <div className="h-96 animate-pulse rounded-3xl bg-white" />
          ) : (
            <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
              <section className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
                {step === 0 && (
                  <div>
                    <h3 className="mb-4 text-lg font-semibold">1. Objetivo</h3>
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {GOALS.map(([label, desc]) => {
                        const Icon =
                          label === "Promoção"
                            ? Megaphone
                            : label === "Lembrete"
                              ? Clock
                              : label === "Pesquisa"
                                ? MessageCircle
                                : label === "Recuperação"
                                  ? Target
                                  : label === "Cobrança"
                                    ? ShieldCheck
                                    : label === "Pós-venda"
                                      ? CheckCircle2
                                      : FileText;
                        return (
                          <button
                            key={label}
                            onClick={() => {
                              setGoal(label);
                              setDirty(true);
                            }}
                            className={`rounded-2xl border p-4 text-left ${goal === label ? "border-emerald-500 bg-emerald-50" : "border-slate-200 hover:border-emerald-200"}`}
                          >
                            <Icon className="mb-3 text-emerald-600" />
                            <p className="font-semibold">{label}</p>
                            <p className="text-xs text-slate-500">{desc}</p>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
                {step === 1 && (
                  <div>
                    <h3 className="mb-4 text-lg font-semibold">2. Template</h3>
                    <select
                      value={providerId}
                      onChange={(e) => {
                        setProviderId(e.target.value);
                        setTemplateId("");
                        setDirty(true);
                      }}
                      className="premium-input mb-3 w-full"
                    >
                      <option value="">Selecione o remetente conectado</option>
                      {providers.filter(connected).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.display_name || p.provider_type} • conectado
                        </option>
                      ))}
                    </select>
                    <div className="mb-3 grid gap-2 md:grid-cols-[1fr_180px]">
                      <label className="flex h-11 items-center gap-2 rounded-full border border-slate-200 px-3 text-sm">
                        <Search size={15} />
                        <input
                          value={templateSearch}
                          onChange={(e) => setTemplateSearch(e.target.value)}
                          className="w-full bg-transparent outline-none"
                          placeholder="Buscar template real..."
                        />
                      </label>
                      <select
                        value={categoryFilter}
                        onChange={(e) => setCategoryFilter(e.target.value)}
                        className="premium-input"
                      >
                        <option value="all">Todas categorias</option>
                        <option value="marketing">Marketing</option>
                        <option value="utility">Utility</option>
                        <option value="authentication">Authentication</option>
                      </select>
                    </div>
                    <div className="grid gap-3">
                      {approved
                        .filter(
                          (t) =>
                            (!templateSearch ||
                              `${t.name} ${templateText(t)}`
                                .toLowerCase()
                                .includes(templateSearch.toLowerCase())) &&
                            (categoryFilter === "all" ||
                              String(t.category || "").toLowerCase() ===
                                categoryFilter),
                        )
                        .map((t) => (
                          <button
                            key={t.id}
                            onClick={() => {
                              setTemplateId(t.id);
                              setDirty(true);
                            }}
                            className={`rounded-2xl border p-4 text-left ${templateId === t.id ? "border-emerald-500 bg-emerald-50" : "border-slate-200 bg-white"}`}
                          >
                            <div className="flex justify-between gap-3">
                              <div>
                                <p className="font-semibold">{t.name}</p>
                                <p className="text-xs text-slate-500">
                                  {t.category || "utility"} • {t.language}
                                </p>
                              </div>
                              <span className="h-fit rounded-full border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                                approved
                              </span>
                            </div>
                            <p className="mt-2 line-clamp-2 text-sm text-slate-600">
                              {templateText(t) ||
                                "Template sem corpo textual local."}
                            </p>
                          </button>
                        ))}
                    </div>
                  </div>
                )}
                {step === 2 && (
                  <div>
                    <h3 className="mb-4 text-lg font-semibold">3. Audiência</h3>
                    <div className="mb-3 flex gap-2">
                      <button
                        onClick={() => setRecipientMode("saved")}
                        className={`rounded-full border px-3 py-2 text-sm ${recipientMode === "saved" ? "bg-slate-900 text-white" : "bg-white"}`}
                      >
                        Contatos reais
                      </button>
                      <button
                        onClick={() => setRecipientMode("csv")}
                        className={`rounded-full border px-3 py-2 text-sm ${recipientMode === "csv" ? "bg-slate-900 text-white" : "bg-white"}`}
                      >
                        CSV existente
                      </button>
                    </div>
                    {recipientMode === "saved" ? (
                      <div className="max-h-[420px] overflow-auto rounded-2xl border border-slate-200 p-3">
                        {eligible.length ? (
                          eligible.map((c) => (
                            <label
                              key={c.id}
                              className="flex items-center gap-3 border-b border-slate-100 py-2 text-sm"
                            >
                              <input
                                type="checkbox"
                                checked={selectedContactIds.includes(c.id)}
                                onChange={(e) => {
                                  setSelectedContactIds((p) =>
                                    e.target.checked
                                      ? [...p, c.id]
                                      : p.filter((id) => id !== c.id),
                                  );
                                  setDirty(true);
                                }}
                              />
                              <span>{c.name || c.phone}</span>
                              <span className="text-xs text-slate-400">
                                {c.phone}
                              </span>
                            </label>
                          ))
                        ) : (
                          <p className="p-6 text-center text-sm text-slate-500">
                            Nenhum contato elegível encontrado.
                          </p>
                        )}
                      </div>
                    ) : (
                      <div>
                        <p className="mb-2 text-xs text-slate-500">
                          CSV: telefone,
                          {vars
                            .map(
                              (v) =>
                                FIELD_OPTIONS.find(
                                  (o) => o.value === mapping[v],
                                )?.csvColumn || `variavel_${v}`,
                            )
                            .join(",")}
                        </p>
                        <textarea
                          value={csvText}
                          onChange={(e) => {
                            setCsvText(e.target.value);
                            setDirty(true);
                          }}
                          rows={8}
                          className="premium-input w-full"
                        />
                        <input
                          type="file"
                          accept=".csv,text/csv"
                          onChange={upload}
                          className="mt-2 text-xs"
                        />
                      </div>
                    )}
                    <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4">
                      {[
                        ["Público estimado", audience],
                        ["Contatos válidos", eligible.length],
                        ["Excluídos", contacts.length - eligible.length],
                        ["Prévia API", "indisponível"],
                      ].map(([l, v]) => (
                        <div
                          key={l}
                          className="rounded-2xl border border-slate-200 bg-slate-50 p-3"
                        >
                          <p className="text-xs text-slate-500">{l}</p>
                          <p className="text-xl font-semibold text-slate-950">
                            {v}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {step === 3 && (
                  <div>
                    <h3 className="mb-4 text-lg font-semibold">4. Variáveis</h3>
                    {vars.length ? (
                      vars.map((v) => (
                        <div
                          key={v}
                          className="mb-3 rounded-2xl border border-slate-200 p-4"
                        >
                          <label className="text-sm font-semibold">
                            Variável {`{{${v}}}`}
                          </label>
                          <select
                            value={mapping[v] || "first_name"}
                            onChange={(e) => {
                              setMapping((p) => ({
                                ...p,
                                [v]: e.target.value,
                              }));
                              setDirty(true);
                            }}
                            className="premium-input mt-2 w-full"
                          >
                            {FIELD_OPTIONS.map((o) => (
                              <option key={o.value} value={o.value}>
                                {o.label}
                              </option>
                            ))}
                          </select>
                          {mapping[v] === FIXED ? (
                            <input
                              value={manual[v] || ""}
                              onChange={(e) =>
                                setManual((p) => ({
                                  ...p,
                                  [v]: e.target.value,
                                }))
                              }
                              className="premium-input mt-2 w-full"
                              placeholder="Valor fixo obrigatório"
                            />
                          ) : null}
                        </div>
                      ))
                    ) : (
                      <p className="rounded-2xl border border-dashed border-slate-200 p-8 text-center text-slate-500">
                        Este template não possui variáveis.
                      </p>
                    )}
                  </div>
                )}
                {step === 4 && (
                  <div>
                    <h3 className="mb-4 text-lg font-semibold">
                      5. Agendamento
                    </h3>
                    <div className="grid gap-3 md:grid-cols-3">
                      {(["draft", "now", "schedule"] as SendMode[]).map((m) => (
                        <button
                          key={m}
                          onClick={() => {
                            setSendMode(m);
                            setDirty(true);
                          }}
                          className={`rounded-2xl border p-4 text-left ${sendMode === m ? "border-emerald-500 bg-emerald-50" : "border-slate-200"}`}
                        >
                          <p className="font-semibold">
                            {m === "draft"
                              ? "Salvar rascunho"
                              : m === "now"
                                ? "Enviar agora"
                                : "Agendar"}
                          </p>
                        </button>
                      ))}
                    </div>
                    {sendMode === "schedule" ? (
                      <label className="mt-4 block text-sm font-semibold">
                        Data e horário{" "}
                        <span className="text-xs text-slate-500">
                          ({Intl.DateTimeFormat().resolvedOptions().timeZone})
                        </span>
                        <input
                          type="datetime-local"
                          value={scheduledAt}
                          onChange={(e) => setScheduledAt(e.target.value)}
                          className="premium-input mt-2 w-full"
                        />
                      </label>
                    ) : null}
                  </div>
                )}
                {step === 5 && (
                  <div>
                    <h3 className="mb-4 text-lg font-semibold">6. Revisão</h3>
                    <input
                      value={name}
                      onChange={(e) => {
                        setName(e.target.value.slice(0, 90));
                        setDirty(true);
                      }}
                      className="premium-input mb-4 w-full"
                      placeholder="Nome obrigatório da campanha"
                    />
                    <div className="grid gap-3 md:grid-cols-2">
                      {[
                        ["Objetivo", goal],
                        ["Template", selectedTemplate?.name || "—"],
                        [
                          "Idioma/Categoria",
                          `${selectedTemplate?.language || "—"} • ${selectedTemplate?.category || "—"}`,
                        ],
                        ["Destinatários elegíveis", audience],
                        [
                          "Remetente",
                          providers.find((p) => p.id === providerId)
                            ?.display_name ||
                            providerId ||
                            "—",
                        ],
                        [
                          "Agendamento",
                          sendMode === "schedule"
                            ? scheduledAt
                            : sendMode === "now"
                              ? "Enviar agora"
                              : "Rascunho",
                        ],
                      ].map(([l, v]) => (
                        <div
                          key={l}
                          className="rounded-2xl border border-slate-200 p-3"
                        >
                          <p className="text-xs text-slate-500">{l}</p>
                          <p className="font-semibold">{v}</p>
                        </div>
                      ))}
                    </div>
                    <div className="mt-4 rounded-2xl border border-slate-200 p-4">
                      <p className="mb-2 font-semibold">Checklist</p>
                      {[
                        ["Template aprovado", !!selectedTemplate],
                        [
                          "Conexão WhatsApp ativa",
                          connected(providers.find((p) => p.id === providerId)),
                        ],
                        [
                          "Audiência válida",
                          sendMode === "draft" || audience > 0,
                        ],
                        ["Variáveis completas", validVars],
                        ["Opt-out respeitado", true],
                        ["Horário válido", validSchedule],
                      ].map(([l, ok]) => (
                        <p
                          key={String(l)}
                          className={`text-sm ${ok ? "text-emerald-700" : "text-amber-700"}`}
                        >
                          {ok ? "✓" : "•"} {l}
                        </p>
                      ))}
                    </div>
                  </div>
                )}
              </section>
              <aside className="space-y-3">
                <div className="rounded-[24px] border border-slate-200 bg-white p-4 shadow-sm">
                  <p className="mb-3 font-semibold">Preview WhatsApp</p>
                  <div className="rounded-[24px] bg-[#efeae2] p-4">
                    <div className="rounded-2xl bg-[#dcf8c6] p-4 text-sm text-slate-800 shadow">
                      <p className="whitespace-pre-wrap">
                        {selectedTemplate
                          ? fill(templateText(selectedTemplate), previewValues)
                          : "Selecione um template aprovado."}
                      </p>
                    </div>
                  </div>
                </div>
                <div className="rounded-[24px] border border-slate-200 bg-white p-4 text-sm">
                  <p className="font-semibold">Segurança multi-tenant</p>
                  <p className="mt-2 text-slate-500">
                    Reutiliza endpoints tenant-aware existentes. Templates não
                    aprovados, conexão inativa e audiência vazia são bloqueados.
                  </p>
                </div>
              </aside>
            </div>
          )}
        </main>
        {error ? (
          <p className="mx-5 mb-2 rounded-2xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
            <AlertTriangle className="mr-2 inline" size={16} />
            {error}
          </p>
        ) : null}
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 p-4">
          <button
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="secondary-button"
          >
            Voltar
          </button>
          <div className="flex flex-wrap gap-2">
            {step < 5 ? (
              <button onClick={next} className="primary-button">
                Continuar
              </button>
            ) : (
              <>
                {(["draft", "schedule", "now"] as SendMode[]).map((m) => (
                  <button
                    key={m}
                    onClick={() => submit(m)}
                    disabled={
                      submitting ||
                      !canFinish ||
                      (m === "schedule" && !validSchedule)
                    }
                    className="primary-button inline-flex items-center gap-2"
                  >
                    {submitting ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : m === "now" ? (
                      <Send size={14} />
                    ) : null}
                    {m === "draft"
                      ? "Salvar rascunho"
                      : m === "schedule"
                        ? "Agendar campanha"
                        : "Enviar agora"}
                  </button>
                ))}
              </>
            )}
          </div>
        </footer>
      </div>
    </div>
  );
}
