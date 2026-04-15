'use client';

import Link from 'next/link';
import { DragEvent, FormEvent, useEffect, useState } from 'react';

import { crawlKnowledgeSite, createKnowledge, deleteKnowledge, getKnowledge, uploadKnowledgePdf } from '../../lib/api';
import { KnowledgeItem } from '../../lib/types';

export default function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [crawlUrl, setCrawlUrl] = useState('');
  const [error, setError] = useState('');
  const [info, setInfo] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploadingPdf, setUploadingPdf] = useState(false);
  const [crawlLoading, setCrawlLoading] = useState(false);
  const [crawlStage, setCrawlStage] = useState('');
  const [dragActive, setDragActive] = useState(false);

  async function loadKnowledge() {
    const data = await getKnowledge();
    setItems(data);
  }

  useEffect(() => {
    loadKnowledge().catch(() => setError('Não foi possível carregar a base de conhecimento.'));
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');

    if (!title.trim() || !content.trim()) {
      setError('Título e conteúdo são obrigatórios.');
      return;
    }

    setSaving(true);
    try {
      await createKnowledge({
        title: title.trim(),
        content: content.trim()
      });
      setTitle('');
      setContent('');
      await loadKnowledge();
    } catch {
      setError('Falha ao salvar conteúdo.');
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(itemId: string) {
    setError('');
    try {
      await deleteKnowledge(itemId);
      await loadKnowledge();
    } catch {
      setError('Falha ao excluir conteúdo.');
    }
  }

  async function processPdf(file: File) {
    setError('');
    setInfo('');
    setUploadingPdf(true);
    try {
      const result = await uploadKnowledgePdf(file);
      setInfo(`PDF "${result.source}" processado com ${result.chunks_created} chunks.`);
      await loadKnowledge();
    } catch {
      setError('Falha ao processar PDF.');
    } finally {
      setUploadingPdf(false);
    }
  }

  async function handleCrawlSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setInfo('');

    if (!crawlUrl.trim()) {
      setError('Informe uma URL para iniciar o treinamento por site.');
      return;
    }

    setCrawlLoading(true);
    setCrawlStage('Coletando páginas...');

    try {
      const crawlPromise = crawlKnowledgeSite({ url: crawlUrl.trim(), depth: 2 });
      setCrawlStage('Processando conteúdo...');
      const result = await crawlPromise;
      setInfo(
        `Treinamento concluído. ${result.pages_collected} páginas coletadas e ${result.chunks_created} chunks criados.`
      );
      setCrawlUrl('');
      await loadKnowledge();
    } catch {
      setError('Falha ao treinar com site. Verifique se a URL é pública e válida.');
    } finally {
      setCrawlLoading(false);
      setCrawlStage('');
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    const file = event.dataTransfer.files?.[0];
    if (file) {
      processPdf(file).catch(() => setError('Falha ao processar PDF.'));
    }
  }

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero">
        <div>
          <h1>Knowledge Base</h1>
          <p>Alimente a IA com conteúdos próprios do seu tenant para respostas mais precisas.</p>
        </div>
        <div className="dashboard-actions">
          <Link href="/dashboard" className="secondary-button">
            Dashboard
          </Link>
          <Link href="/chat" className="primary-button">
            Abrir chat
          </Link>
        </div>
      </section>

      {error ? <p className="error-text">{error}</p> : null}
      {info ? <p>{info}</p> : null}

      <section className="products-layout">
        <article className="products-form-card">
          <h2>Adicionar conteúdo</h2>

          <form className="products-form" onSubmit={handleCrawlSubmit} style={{ marginBottom: 16 }}>
            <label htmlFor="knowledge-url">URL do site</label>
            <input
              id="knowledge-url"
              type="url"
              placeholder="https://site.com"
              value={crawlUrl}
              onChange={(event) => setCrawlUrl(event.target.value)}
            />
            <div className="products-form-actions">
              <button type="submit" className="primary-button" disabled={crawlLoading}>
                {crawlLoading ? 'Treinando...' : 'Treinar com site'}
              </button>
            </div>
            {crawlLoading && crawlStage ? <p>{crawlStage}</p> : null}
          </form>

          <div
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            style={{
              border: '1px dashed #6b7280',
              borderRadius: 12,
              padding: 16,
              marginBottom: 16,
              backgroundColor: dragActive ? 'rgba(59, 130, 246, 0.1)' : 'transparent'
            }}
          >
            <strong>Upload PDF</strong>
            <p>Arraste e solte um PDF aqui para processar automaticamente no RAG.</p>
            <label htmlFor="pdf-upload" className="secondary-button" style={{ display: 'inline-block', cursor: 'pointer' }}>
              Upload PDF
            </label>
            <input
              id="pdf-upload"
              type="file"
              accept="application/pdf"
              style={{ display: 'none' }}
              onChange={(event) => {
                const selected = event.target.files?.[0];
                if (selected) {
                  processPdf(selected).catch(() => setError('Falha ao processar PDF.'));
                }
              }}
            />
            {uploadingPdf ? <p>Processando documento...</p> : null}
          </div>

          <form className="products-form" onSubmit={handleSubmit}>
            <label htmlFor="knowledge-title">Título</label>
            <input id="knowledge-title" value={title} onChange={(event) => setTitle(event.target.value)} required />

            <label htmlFor="knowledge-content">Conteúdo</label>
            <textarea
              id="knowledge-content"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              required
              rows={8}
            />

            <div className="products-form-actions">
              <button type="submit" className="primary-button" disabled={saving}>
                {saving ? 'Salvando...' : 'Salvar'}
              </button>
            </div>
          </form>
        </article>

        <article className="products-list-card">
          <h2>Conteúdos cadastrados</h2>
          <div className="products-list">
            {items.map((item) => (
              <div className="product-card" key={item.id}>
                <strong>{item.title}</strong>
                <p>{item.content}</p>
                <div className="product-actions">
                  <button type="button" className="ghost-button" onClick={() => handleDelete(item.id)}>
                    Excluir
                  </button>
                </div>
              </div>
            ))}

            {!items.length ? <p className="empty-state">Nenhum conteúdo cadastrado para este tenant.</p> : null}
          </div>
        </article>
      </section>
    </main>
  );
}
