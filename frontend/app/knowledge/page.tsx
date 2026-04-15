'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';

import { createKnowledge, deleteKnowledge, getKnowledge } from '../../lib/api';
import { KnowledgeItem } from '../../lib/types';

export default function KnowledgePage() {
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);

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

      <section className="products-layout">
        <article className="products-form-card">
          <h2>Adicionar conteúdo</h2>
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
