'use client';

import Link from 'next/link';
import { FormEvent, useEffect, useMemo, useState } from 'react';

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

  async function loadProducts() {
    const data = await getProducts();
    setProducts(data);
  }

  useEffect(() => {
    loadProducts().catch(() => setError('Não foi possível carregar os produtos.'));
  }, []);

  const submitLabel = useMemo(() => (editingId ? 'Salvar alterações' : 'Adicionar produto'), [editingId]);

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
    <main className="dashboard-page">
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
          <h2>Lista de produtos</h2>
          <div className="products-list">
            {products.map((product) => (
              <div className="product-card" key={product.id}>
                <strong>{product.name}</strong>
                <p>{product.description || 'Sem descrição.'}</p>
                <small>Preço: {product.price || '-'}</small>
                <div className="product-actions">
                  <button type="button" className="secondary-button" onClick={() => startEdit(product)}>
                    Editar
                  </button>
                  <button type="button" className="ghost-button" onClick={() => handleDelete(product.id)}>
                    Excluir
                  </button>
                </div>
              </div>
            ))}

            {!products.length ? <p className="empty-state">Nenhum produto cadastrado para este tenant.</p> : null}
          </div>
        </article>

        <article className="products-form-card">
          <h2>{editingId ? 'Editar produto' : 'Adicionar produto'}</h2>
          <form onSubmit={handleSubmit} className="products-form">
            <label htmlFor="name">Nome</label>
            <input
              id="name"
              value={form.name || ''}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              required
            />

            <label htmlFor="description">Descrição</label>
            <textarea
              id="description"
              value={form.description || ''}
              onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
            />

            <label htmlFor="price">Preço</label>
            <input
              id="price"
              value={form.price || ''}
              onChange={(event) => setForm((current) => ({ ...current, price: event.target.value }))}
            />

            <label htmlFor="benefits">Benefícios</label>
            <textarea
              id="benefits"
              value={form.benefits || ''}
              onChange={(event) => setForm((current) => ({ ...current, benefits: event.target.value }))}
            />

            <label htmlFor="objections">Objeções comuns</label>
            <textarea
              id="objections"
              value={form.objections || ''}
              onChange={(event) => setForm((current) => ({ ...current, objections: event.target.value }))}
            />

            <label htmlFor="target_customer">Cliente ideal</label>
            <textarea
              id="target_customer"
              value={form.target_customer || ''}
              onChange={(event) => setForm((current) => ({ ...current, target_customer: event.target.value }))}
            />

            <div className="products-form-actions">
              <button type="submit" className="primary-button" disabled={saving}>
                {saving ? 'Salvando...' : submitLabel}
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
