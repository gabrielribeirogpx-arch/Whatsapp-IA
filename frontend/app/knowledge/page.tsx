"use client";

import { FormEvent, useEffect, useState } from "react";
import { Database, FileText, UploadCloud } from "lucide-react";
import { apiFetch } from "@/lib/api";

type KnowledgeSource = {
  id: string;
  name: string;
  type: string;
  status: "pending" | "processing" | "ready" | "failed" | string;
  original_filename?: string | null;
  size_bytes?: number | null;
  chunks_count?: number;
  created_at: string;
};

export default function KnowledgePage() {
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");

  async function loadSources() {
    setLoading(true);
    setError("");
    try {
      const response = await apiFetch("/api/knowledge/sources");
      if (!response.ok) throw new Error("Falha ao carregar fontes");
      setSources(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao carregar fontes");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadSources();
  }, []);

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setError("");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const response = await apiFetch("/api/knowledge/upload", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Falha ao enviar arquivo");
      }
      setFile(null);
      await loadSources();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao enviar arquivo");
    } finally {
      setUploading(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Excluir esta fonte e todos os chunks?")) return;
    const response = await apiFetch(`/api/knowledge/sources/${id}`, {
      method: "DELETE",
    });
    if (response.ok)
      setSources((current) => current.filter((source) => source.id !== id));
  }

  return (
    <section className="w-full min-w-0 px-5 py-6 lg:px-6">
      <div className="w-full min-w-0 space-y-5">
        <header className="flex flex-col gap-4 rounded-3xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.05)] md:flex-row md:items-end md:justify-between">
          <div className="min-w-0">
            <nav
              className="mb-3 flex flex-wrap items-center gap-2 text-xs font-medium text-slate-500"
              aria-label="Breadcrumb"
            >
              <span>Dashboard</span>
              <span className="text-slate-300">&gt;</span>
              <span>Ferramentas</span>
              <span className="text-slate-300">&gt;</span>
              <span className="text-slate-700">Base de conhecimento</span>
            </nav>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-2xl font-semibold leading-tight text-slate-900 md:text-3xl">
                Base de conhecimento
              </h1>
              <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-bold uppercase tracking-wide text-emerald-700">
                RAG
              </span>
            </div>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500 md:text-base">
              Envie PDFs pesquisáveis ou arquivos TXT para alimentar nodes
              IA/RAG dos fluxos.
            </p>
          </div>
        </header>

        <div className="grid w-full grid-cols-1 gap-4 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.45fr)]">
          <form
            onSubmit={upload}
            className="rounded-3xl border border-slate-100 bg-white p-5 shadow-[0_12px_30px_rgba(15,23,42,0.05)]"
          >
            <div className="flex items-start gap-3">
              <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-600 ring-1 ring-emerald-100">
                <UploadCloud className="h-6 w-6" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900">
                  Upload PDF/TXT
                </h2>
                <p className="mt-1 text-sm leading-5 text-slate-500">
                  Selecione um documento para treinar as respostas com contexto
                  da sua operação.
                </p>
              </div>
            </div>

            <div className="mt-5 rounded-2xl border border-dashed border-emerald-200 bg-gradient-to-b from-emerald-50/60 to-white p-4">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                <label className="sr-only" htmlFor="knowledge-file">
                  Arquivo PDF ou TXT
                </label>
                <input
                  id="knowledge-file"
                  className="min-w-0 flex-1 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700 outline-none transition file:mr-3 file:rounded-lg file:border-0 file:bg-slate-100 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-slate-700 hover:border-emerald-200 focus:border-emerald-300 focus:ring-2 focus:ring-emerald-100"
                  type="file"
                  accept="application/pdf,text/plain,.pdf,.txt"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                />
                <button
                  disabled={!file || uploading}
                  className="inline-flex h-11 items-center justify-center rounded-xl bg-emerald-600 px-5 text-sm font-semibold text-white shadow-[0_12px_24px_rgba(16,185,129,0.22)] transition hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-200 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                  type="submit"
                >
                  {uploading ? "Processando..." : "Enviar"}
                </button>
              </div>
              <p className="mt-3 flex items-start gap-2 text-xs leading-5 text-slate-500">
                <FileText
                  className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600"
                  aria-hidden="true"
                />
                PDF escaneado sem texto pesquisável será recusado com mensagem
                amigável.
              </p>
            </div>
          </form>

          <section className="rounded-3xl border border-slate-100 bg-white shadow-[0_12px_30px_rgba(15,23,42,0.05)]">
            <div className="flex items-center justify-between gap-3 border-b border-slate-100 p-5">
              <div>
                <h2 className="text-lg font-semibold text-slate-900">
                  Fontes cadastradas
                </h2>
                <p className="mt-1 text-sm text-slate-500">
                  Arquivos disponíveis para consulta nos nodes IA/RAG.
                </p>
              </div>
              <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
                {sources.length} fonte{sources.length === 1 ? "" : "s"}
              </span>
            </div>
            {loading ? (
              <p className="p-5 text-slate-500">Carregando...</p>
            ) : sources.length === 0 ? (
              <div className="grid min-h-[260px] place-items-center p-6 text-center">
                <div className="max-w-sm space-y-3">
                  <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl border border-emerald-100 bg-emerald-50 text-emerald-600 shadow-sm">
                    <Database className="h-7 w-7" aria-hidden="true" />
                  </span>
                  <div>
                    <h3 className="text-base font-semibold text-slate-900">
                      Nenhuma base cadastrada ainda
                    </h3>
                    <p className="mt-1 text-sm leading-6 text-slate-500">
                      Envie seu primeiro PDF ou TXT para começar a responder com
                      IA.
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {sources.map((source) => (
                  <article
                    key={source.id}
                    className="flex flex-col gap-3 p-5 transition hover:bg-emerald-50/30 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <h3 className="truncate font-semibold text-slate-900">
                        {source.name}
                      </h3>
                      <p className="mt-1 text-sm text-slate-500">
                        {source.type.toUpperCase()} • {source.chunks_count || 0}{" "}
                        chunks •{" "}
                        {(source.size_bytes || 0).toLocaleString("pt-BR")} bytes
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-3">
                      <span
                        className={`rounded-full px-3 py-1 text-xs font-semibold ${source.status === "ready" ? "bg-emerald-100 text-emerald-700" : source.status === "failed" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-700"}`}
                      >
                        {source.status}
                      </span>
                      <button
                        onClick={() => void remove(source.id)}
                        className="rounded-lg border border-slate-200 bg-white px-3 py-1 text-sm font-medium text-slate-700 transition hover:border-red-200 hover:bg-red-50 hover:text-red-700 focus:outline-none focus:ring-2 focus:ring-slate-200"
                        type="button"
                      >
                        Deletar
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>

        {error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-700">
            {error}
          </div>
        ) : null}
      </div>
    </section>
  );
}
