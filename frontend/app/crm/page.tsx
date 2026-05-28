'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';

import { getContacts, updateContactCustomFields } from '../../lib/api';
import { CRMContact } from '../../lib/types';

export default function CRMPage() {
  const [contacts, setContacts] = useState<CRMContact[]>([]);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<CRMContact | null>(null);
  const [name, setName] = useState('');
  const [tags, setTags] = useState('');
  const [customFields, setCustomFields] = useState('');

  const load = async () => {
    const data = await getContacts();
    setContacts(data);
  };

  useEffect(() => {
    load().catch(() => setError('Falha real ao sincronizar contatos. Tente novamente em alguns instantes.'));
  }, []);

  const parsedCustomFields = useMemo(() => {
    try { return JSON.parse(customFields || '{}'); } catch { return {}; }
  }, [customFields]);

  return (
    <main className="dashboard-page">
      <section className="dashboard-hero">
        <div>
          <h1>CRM de Vendas</h1>
          <p>Visão de contatos por etapa do cliente e temperatura para priorização comercial.</p>
        </div>
        <Link href="/chat" className="primary-button">Abrir chat</Link>
      </section>
      {error ? <p className="error-text">{error}</p> : null}
      {!contacts.length && !error ? (
        <div className="products-empty-state" role="status">
          <span className="products-empty-eyebrow">CRM pronto para crescer</span>
          <h3>Nenhum item criado ainda</h3>
          <p>Os contatos serão criados a partir das conversas e campanhas. Comece abrindo o chat ou importando uma audiência em campanhas.</p>
          <Link href="/chat" className="primary-button">Abrir chat</Link>
        </div>
      ) : null}

      {contacts.length ? <section className="crm-table-wrap">
        <table className="crm-table"><thead><tr><th>Contato</th><th>Telefone</th><th>Plano</th><th>Cidade</th><th>Última mensagem</th></tr></thead>
          <tbody>
            {contacts.map((contact) => (
              <tr key={contact.id} onClick={() => { setEditing(contact); setName(contact.name || ''); setTags((contact.tags_json || []).join(',')); setCustomFields(JSON.stringify(contact.custom_fields_json || {}, null, 2)); }}>
                <td>{contact.name || 'Sem nome'}</td><td>{contact.phone}</td><td>{contact.plan || '-'}</td><td>{contact.city || '-'}</td><td>{contact.last_message || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section> : null}
      {editing ? <div className='fixed inset-0 bg-black/30 flex items-center justify-center z-50' onClick={() => setEditing(null)}><div className='bg-white p-4 rounded-lg w-[640px]' onClick={(e) => e.stopPropagation()}>
        <h3>Editar contato</h3>
        <label>Nome<input value={name} onChange={(e) => setName(e.target.value)} className='w-full border p-2' /></label>
        <label>Etiquetas (csv)<input value={tags} onChange={(e) => setTags(e.target.value)} className='w-full border p-2' /></label>
        <label>Informações personalizadas (JSON)<textarea value={customFields} onChange={(e) => setCustomFields(e.target.value)} className='w-full border p-2 h-40' /></label>
        <button className='primary-button mt-3' onClick={async () => { await updateContactCustomFields(editing.id, { ...parsedCustomFields, name, tags_json: tags.split(',').map((t) => t.trim()).filter(Boolean) }); setEditing(null); await load(); }}>Salvar</button>
      </div></div> : null}
    </main>
  );
}
