'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Bot, Box, Check, Ellipsis, LoaderCircle, Pencil, Plus, Sparkles, Trash2 } from 'lucide-react';

import { createProduct, deleteProduct, getProducts, updateProduct } from '../../lib/api';
import { Product, ProductPayload } from '../../lib/types';

const EMPTY_FORM: ProductPayload = {
  name: '',
  description: '',
  price: '',
  benefits: '',
  objections: '',
  target_customer: ''
};

export default function ProductsPage() {
  const [products, setProducts] = useState<Product[]>([]);
  const [form, setForm] = useState<ProductPayload>(EMPTY_FORM);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [isLoading, setIsLoading] = useState(true);

  async function loadProducts() {
    const data = await getProducts();
    setProducts(data);
  }

  useEffect(() => {
    setIsLoading(true);
    loadProducts()
      .catch(() => setError('Falha real ao sincronizar produtos. Tente novamente em alguns instantes.'))
      .finally(() => setIsLoading(false));
  }, []);

  const submitLabel = useMemo(() => (editingId ? 'Salvar alterações' : 'Adicionar produto'), [editingId]);

  const formatUpdatedAt = (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return 'Atualizado recentemente';

    return new Intl.DateTimeFormat('pt-BR', {
      day: '2-digit',
      month: 'short',
      year: 'numeric'
    }).format(date);
  };

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');

    if (!form.name?.trim()) {
      setError('O nome do produto é obrigatório.');
      return;
    }

    setSaving(true);

    try {
      const payload: ProductPayload = {
        name: form.name.trim(),
        description: form.description?.trim(),
        price: form.price?.trim(),
        benefits: form.benefits?.trim(),
        objections: form.objections?.trim(),
        target_customer: form.target_customer?.trim()
      };

      if (editingId) {
        await updateProduct(editingId, payload);
      } else {
        await createProduct(payload);
      }

      setForm(EMPTY_FORM);
      setEditingId(null);
      await loadProducts();
    } catch {
      setError('Falha ao salvar produto.');
    } finally {
      setSaving(false);
    }
  }

  function startEdit(product: Product) {
    setEditingId(product.id);
    setForm({
      name: product.name,
      description: product.description || '',
      price: product.price || '',
      benefits: product.benefits || '',
      objections: product.objections || '',
      target_customer: product.target_customer || ''
    });
  }

  async function handleDelete(productId: string) {
    setError('');
    try {
      await deleteProduct(productId);
      if (editingId === productId) {
        setEditingId(null);
        setForm(EMPTY_FORM);
      }
      await loadProducts();
    } catch {
      setError('Falha ao excluir produto.');
    }
  }

  return (
    <main className="dashboard-page products-page">
      <section className="dashboard-hero">
        <div>
          <h1>Produtos</h1>
          <p>Cadastre produtos e serviços para a IA vender automaticamente no WhatsApp.</p>
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
        <article className="products-list-card">
          <div className="products-panel-heading">
            <div>
              <span className="products-panel-kicker">Base de conhecimento</span>
              <h2>Produtos</h2>
            </div>
            {!isLoading && products.length ? <span className="products-count">{products.length}</span> : null}
          </div>
          <div className="products-list">
            {isLoading ? (
              <div className="products-skeleton-list" aria-label="Carregando produtos">
                <span /><span /><span />
              </div>
            ) : null}

            {!isLoading && products.map((product) => (
              <div className={`product-card ${editingId === product.id ? 'is-selected' : ''}`} key={product.id}>
                <button type="button" className="product-card-main" onClick={() => startEdit(product)}>
                  <span className="product-card-icon"><Box size={16} strokeWidth={2} /></span>
                  <span className="product-card-content">
                    <span className="product-card-title-row">
                      <strong>{product.name}</strong>
                      {product.price ? <span className="product-card-price">{product.price}</span> : null}
                    </span>
                    <span className="product-card-description">{product.description || 'Sem descrição comercial cadastrada.'}</span>
                    <span className="product-card-meta">
                      <span className="product-status"><Check size={12} strokeWidth={2.5} /> Pronto para IA</span>
                      <span>Atualizado {formatUpdatedAt(product.updated_at)}</span>
                    </span>
                  </span>
                </button>
                <details className="product-context-menu">
                  <summary aria-label={`Ações para ${product.name}`}><Ellipsis size={18} /></summary>
                  <div className="product-context-menu-content">
                    <button type="button" onClick={() => startEdit(product)}><Pencil size={14} /> Editar</button>
                    <button type="button" className="is-danger" onClick={() => handleDelete(product.id)}><Trash2 size={14} /> Excluir</button>
                  </div>
                </details>
              </div>
            ))}

            {!isLoading && !products.length ? (
              <div className="products-empty-state" role="status">
                <span className="products-empty-icon"><Sparkles size={20} /></span>
                <span className="products-empty-eyebrow">Treinamento da IA</span>
                <h3>A IA ainda não possui conhecimento sobre seus produtos.</h3>
                <p>O primeiro produto melhora significativamente as respostas automáticas.</p>
                <button type="button" className="products-empty-cta" onClick={() => document.getElementById('name')?.focus()}>
                  <Plus size={15} /> Cadastrar primeiro produto
                </button>
              </div>
            ) : null}
          </div>
        </article>

        <article className="products-form-card">
          <div className="products-editor-heading">
            <div>
              <span className="products-panel-kicker">{editingId ? 'Modo de edição' : 'Novo conhecimento'}</span>
              <h2>{editingId ? 'Editar produto' : 'Adicionar produto'}</h2>
              <p>Estruture as informações que ajudam a IA a vender com segurança.</p>
            </div>
            <span className="products-ai-badge"><Bot size={16} /> IA de vendas</span>
          </div>
          <div className="products-ai-note"><Sparkles size={16} /><span>Essas informações serão utilizadas pela IA para responder clientes automaticamente.</span></div>
          <form onSubmit={handleSubmit} className="products-form">
            <fieldset className="products-form-group">
              <legend>Informações básicas</legend>
              <div className="products-form-grid">
                <div className="products-field"><label htmlFor="name">Nome <span aria-hidden="true">*</span></label><input id="name" placeholder="Ex.: Consultoria Premium" value={form.name || ''} onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))} required /></div>
                <div className="products-field"><label htmlFor="price">Preço</label><input id="price" placeholder="Ex.: R$ 1.490,00" value={form.price || ''} onChange={(event) => setForm((current) => ({ ...current, price: event.target.value }))} /></div>
              </div>
            </fieldset>

            <fieldset className="products-form-group">
              <legend>Descrição comercial</legend>
              <div className="products-field"><label htmlFor="description">Descrição</label><textarea id="description" placeholder="Apresente o produto de forma clara e convincente." value={form.description || ''} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} /><small>Explique o produto como faria para um cliente.</small></div>
            </fieldset>

            <fieldset className="products-form-group products-form-group-insights">
              <legend>Inteligência de vendas</legend>
              <div className="products-field"><label htmlFor="benefits">Benefícios</label><textarea id="benefits" placeholder="Ex.: economiza tempo, reduz custos, inclui suporte." value={form.benefits || ''} onChange={(event) => setForm((current) => ({ ...current, benefits: event.target.value }))} /><small>Liste vantagens reais percebidas pelo cliente.</small></div>
              <div className="products-field"><label htmlFor="objections">Objeções comuns</label><textarea id="objections" placeholder="Ex.: prazo, investimento, adequação ao negócio." value={form.objections || ''} onChange={(event) => setForm((current) => ({ ...current, objections: event.target.value }))} /><small>Quais dúvidas ou resistências costumam surgir?</small></div>
              <div className="products-field"><label htmlFor="target_customer">Cliente ideal</label><textarea id="target_customer" placeholder="Ex.: empresas que precisam acelerar o atendimento." value={form.target_customer || ''} onChange={(event) => setForm((current) => ({ ...current, target_customer: event.target.value }))} /><small>Quem normalmente compra este produto?</small></div>
            </fieldset>

            <div className="products-form-actions">
              <button type="submit" className="primary-button products-save-button" disabled={saving}>
                {saving ? <><LoaderCircle size={16} className="products-spinner" /> Salvando...</> : <><Plus size={16} /> {submitLabel}</>}
              </button>

              {editingId ? (
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => {
                    setEditingId(null);
                    setForm(EMPTY_FORM);
                  }}
                >
                  Cancelar
                </button>
              ) : null}
            </div>
          </form>
        </article>
      </section>
    </main>
  );
}
