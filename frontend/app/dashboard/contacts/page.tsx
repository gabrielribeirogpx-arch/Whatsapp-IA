'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch, updateContact } from '@/lib/api';
import { CRMContact } from '@/lib/types';

type CustomFieldEntry = { key: string; value: string };

function formatDate(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('pt-BR');
}

export default function ContactsPage() {
  const [contacts, setContacts] = useState<CRMContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<CRMContact | null>(null);
  const [name, setName] = useState('');
  const [firstName, setFirstName] = useState('');
  const [lastName, setLastName] = useState('');
  const [email, setEmail] = useState('');
  const [tags, setTags] = useState('');
  const [customFields, setCustomFields] = useState<CustomFieldEntry[]>([]);
  const [saving, setSaving] = useState(false);

  const loadContacts = async () => {
    setLoading(true);
    setError(null);
    try {
      const url = '/api/contacts';
      const response = await apiFetch(url, { cache: 'no-store' });
      const data = await response.json();
      console.log('CONTACTS PAGE RAW RESPONSE', data);

      if (!response.ok) {
        throw new Error(data?.detail || 'Falha ao carregar contatos');
      }

      const contactsArray = Array.isArray(data)
        ? data
        : Array.isArray(data?.items)
          ? data.items
          : Array.isArray(data?.contacts)
            ? data.contacts
            : [];

      console.log('CONTACTS PAGE FINAL ARRAY', contactsArray);
      setContacts(contactsArray);
    } catch (err) {
      setContacts([]);
      setError((err as Error).message || 'Falha ao carregar contatos');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadContacts();
  }, []);

  const editContact = (contact: CRMContact) => {
    setEditing(contact);
    setName(contact.name || '');
    setFirstName(contact.first_name || '');
    setLastName(contact.last_name || '');
    setEmail(contact.email || '');
    setTags((contact.tags_json || []).join(', '));

    const entries = Object.entries(contact.custom_fields_json || {}).map(([key, value]) => ({
      key,
      value: String(value ?? '')
    }));

    if (!entries.length) {
      entries.push({ key: 'order_number', value: '#4821' });
    }

    setCustomFields(entries);
  };

  const customFieldsJson = useMemo(
    () =>
      customFields.reduce<Record<string, string>>((acc, item) => {
        const key = item.key.trim();
        if (key) acc[key] = item.value;
        return acc;
      }, {}),
    [customFields]
  );

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await updateContact(editing.id, {
        name: name.trim() || null,
        first_name: firstName.trim() || null,
        last_name: lastName.trim() || null,
        email: email.trim() || null,
        tags: tags
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean),
        custom_fields_json: customFieldsJson
      });
      setEditing(null);
      await loadContacts();
    } catch (err) {
      setError((err as Error).message || 'Falha ao salvar contato');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className='space-y-4 p-6'>
      <h1 className='text-2xl font-semibold'>Contatos</h1>
      <div className='flex items-center justify-between gap-2'>
        <p className='text-sm text-slate-600'>Gerencie contatos do WhatsApp usados em campanhas.</p>
        <button className='secondary-button' onClick={() => void loadContacts()} disabled={loading}>
          {loading ? 'Recarregando...' : 'Recarregar contatos'}
        </button>
      </div>

      {loading ? <p>Carregando contatos...</p> : null}
      {!loading && error ? <p className='text-sm text-rose-600'>{error}</p> : null}
      {!loading && !error && contacts.length === 0 ? <p className='text-sm text-slate-500'>Nenhum contato encontrado.</p> : null}

      {!loading && !error && contacts.length > 0 ? (
        <div className='overflow-auto rounded-xl border border-slate-200 bg-white'>
          <table className='min-w-full text-sm'>
            <thead className='bg-slate-50 text-left'>
              <tr>
                <th className='p-2'>Nome</th>
                <th className='p-2'>Telefone</th>
                <th className='p-2'>Source</th>
                <th className='p-2'>Tags</th>
                <th className='p-2'>Última interação</th>
                <th className='p-2'>Custom fields</th>
                <th className='p-2'>Ações</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((contact) => (
                <tr key={contact.id} className='border-t'>
                  <td className='p-2'>{contact.name || '-'}</td>
                  <td className='p-2'>{contact.phone || '-'}</td>
                  <td className='p-2'>{contact.source || '-'}</td>
                  <td className='p-2'>{(contact.tags_json || []).join(', ') || '-'}</td>
                  <td className='p-2'>{formatDate(contact.last_interaction_at)}</td>
                  <td className='p-2'>
                    <code>{JSON.stringify(contact.custom_fields_json || {})}</code>
                  </td>
                  <td className='p-2'>
                    <button className='secondary-button' onClick={() => editContact(contact)}>
                      Editar
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {editing ? (
        <div className='fixed inset-0 z-50 bg-black/40 p-4'>
          <div className='mx-auto max-w-2xl space-y-3 rounded-xl bg-white p-4'>
            <h2 className='text-lg font-semibold'>Editar contato</h2>
            <input className='premium-input w-full' placeholder='Nome' value={name} onChange={(e) => setName(e.target.value)} />
            <div className='grid grid-cols-2 gap-2'>
              <input className='premium-input' placeholder='Primeiro nome' value={firstName} onChange={(e) => setFirstName(e.target.value)} />
              <input className='premium-input' placeholder='Sobrenome' value={lastName} onChange={(e) => setLastName(e.target.value)} />
            </div>
            <input className='premium-input w-full' placeholder='E-mail' value={email} onChange={(e) => setEmail(e.target.value)} />
            <input className='premium-input w-full' placeholder='tags separadas por vírgula' value={tags} onChange={(e) => setTags(e.target.value)} />

            <div className='space-y-2'>
              <p className='text-sm font-medium'>Campos personalizados</p>
              {customFields.map((item, idx) => (
                <div key={`${item.key}-${idx}`} className='grid grid-cols-[1fr_1fr_auto] gap-2'>
                  <input
                    className='premium-input'
                    placeholder='chave'
                    value={item.key}
                    onChange={(e) => setCustomFields((prev) => prev.map((row, i) => (i === idx ? { ...row, key: e.target.value } : row)))}
                  />
                  <input
                    className='premium-input'
                    placeholder='valor'
                    value={item.value}
                    onChange={(e) => setCustomFields((prev) => prev.map((row, i) => (i === idx ? { ...row, value: e.target.value } : row)))}
                  />
                  <button className='secondary-button' onClick={() => setCustomFields((prev) => prev.filter((_, i) => i !== idx))}>
                    Remover
                  </button>
                </div>
              ))}
              <button className='secondary-button' onClick={() => setCustomFields((prev) => [...prev, { key: 'order_number', value: '#4821' }])}>
                + Adicionar campo personalizado
              </button>
            </div>

            <div className='flex justify-end gap-2'>
              <button className='secondary-button' onClick={() => setEditing(null)}>
                Cancelar
              </button>
              <button className='primary-button' onClick={() => void save()} disabled={saving}>
                {saving ? 'Salvando...' : 'Salvar'}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
