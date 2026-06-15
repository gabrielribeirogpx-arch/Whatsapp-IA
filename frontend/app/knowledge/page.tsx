'use client';

import { FormEvent, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

type KnowledgeSource = {
  id: string;
  name: string;
  type: string;
  status: 'pending' | 'processing' | 'ready' | 'failed' | string;
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
  const [error, setError] = useState('');

  async function loadSources() {
    setLoading(true);
    setError('');
    try {
      const response = await apiFetch('/api/knowledge/sources');
      if (!response.ok) throw new Error('Falha ao carregar fontes');
      setSources(await response.json());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao carregar fontes');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void loadSources(); }, []);

  async function upload(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setUploading(true);
    setError('');
    const formData = new FormData();
    formData.append('file', file);
    try {
      const response = await apiFetch('/api/knowledge/upload', { method: 'POST', body: formData });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || 'Falha ao enviar arquivo');
      }
      setFile(null);
      await loadSources();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao enviar arquivo');
    } finally {
      setUploading(false);
    }
  }

  async function remove(id: string) {
    if (!confirm('Excluir esta fonte e todos os chunks?')) return;
    const response = await apiFetch(`/api/knowledge/sources/${id}`, { method: 'DELETE' });
    if (response.ok) setSources((current) => current.filter((source) => source.id !== id));
  }

  return (
    <main className="min-h-screen bg-slate-50 p-6">
      <section className="mx-auto max-w-5xl space-y-6">
        <header>
          <p className="text-sm font-semibold uppercase tracking-wide text-indigo-600">RAG</p>
          <h1 className="text-3xl font-bold text-slate-900">Base de conhecimento</h1>
          <p className="text-slate-600">Envie PDFs pesquisáveis ou arquivos TXT para alimentar nodes IA / RAG dos fluxos.</p>
        </header>

        <form onSubmit={upload} className="rounded-2xl border bg-white p-5 shadow-sm">
          <label className="block text-sm font-medium text-slate-700">Upload PDF/TXT</label>
          <div className="mt-3 flex flex-col gap-3 sm:flex-row">
            <input className="flex-1 rounded-lg border px-3 py-2" type="file" accept="application/pdf,text/plain,.pdf,.txt" onChange={(event) => setFile(event.target.files?.[0] || null)} />
            <button disabled={!file || uploading} className="rounded-lg bg-indigo-600 px-5 py-2 font-semibold text-white disabled:opacity-50" type="submit">{uploading ? 'Processando...' : 'Enviar'}</button>
          </div>
          <p className="mt-2 text-sm text-slate-500">PDF escaneado sem texto pesquisável será recusado com mensagem amigável.</p>
        </form>

        {error ? <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-700">{error}</div> : null}

        <section className="rounded-2xl border bg-white shadow-sm">
          <div className="border-b p-5"><h2 className="text-lg font-semibold">Fontes cadastradas</h2></div>
          {loading ? <p className="p-5 text-slate-500">Carregando...</p> : sources.length === 0 ? <p className="p-8 text-center text-slate-500">Nenhuma base cadastrada ainda.</p> : (
            <div className="divide-y">
              {sources.map((source) => (
                <article key={source.id} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h3 className="font-semibold text-slate-900">{source.name}</h3>
                    <p className="text-sm text-slate-500">{source.type.toUpperCase()} • {source.chunks_count || 0} chunks • {(source.size_bytes || 0).toLocaleString('pt-BR')} bytes</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ${source.status === 'ready' ? 'bg-emerald-100 text-emerald-700' : source.status === 'failed' ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{source.status}</span>
                    <button onClick={() => void remove(source.id)} className="rounded-lg border px-3 py-1 text-sm text-slate-700" type="button">Deletar</button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </section>
    </main>
  );
}
