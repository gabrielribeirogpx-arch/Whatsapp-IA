'use client';

import { useEffect, useMemo, useState } from 'react';
import { CRMContact } from '@/lib/types';
import { getContacts, updateContact } from '@/lib/api';

type CustomFieldEntry = { key: string; value: string };

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
    try {
      setContacts(await getContacts());
      setError(null);
    } catch (err) {
      setError((err as Error).message || 'Falha ao carregar contatos');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void loadContacts(); }, []);

  const editContact = (contact: CRMContact) => {
    setEditing(contact);
    setName(contact.name || '');
    setFirstName(contact.first_name || '');
    setLastName(contact.last_name || '');
    setEmail(contact.email || '');
    setTags((contact.tags_json || []).join(', '));
    const entries = Object.entries(contact.custom_fields_json || {}).map(([key, value]) => ({ key, value: String(value ?? '') }));
    setCustomFields(entries.length ? entries : [{ key: 'order_number', value: '' }]);
  };

  const customFieldsJson = useMemo(() => customFields.reduce<Record<string, string>>((acc, item) => {
    const key = item.key.trim();
    if (key) acc[key] = item.value;
    return acc;
  }, {}), [customFields]);

  const save = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      await updateContact(editing.id, {
        name: name.trim() || null,
        first_name: firstName.trim() || null,
        last_name: lastName.trim() || null,
        email: email.trim() || null,
        tags: tags.split(',').map((item) => item.trim()).filter(Boolean),
        custom_fields_json: customFieldsJson
      });
      setEditing(null);
      await loadContacts();
    } finally {
      setSaving(false);
    }
  };

  return <div className='p-6 space-y-4'>
    <h1 className='text-2xl font-semibold'>Contatos</h1>
    <p className='text-sm text-slate-600'>Gerencie contatos do WhatsApp usados em campanhas.</p>
    {error ? <p className='text-sm text-rose-600'>{error}</p> : null}
    {loading ? <p>Carregando...</p> : (
      <div className='overflow-auto rounded-xl border border-slate-200 bg-white'>
        <table className='min-w-full text-sm'>
          <thead className='bg-slate-50 text-left'>
            <tr>
              <th className='p-2'>Nome</th><th className='p-2'>Telefone</th><th className='p-2'>Source</th><th className='p-2'>Tags</th><th className='p-2'>Última interação</th><th className='p-2'>Custom fields</th><th className='p-2'></th>
            </tr>
          </thead>
          <tbody>
            {contacts.map((c) => <tr key={c.id} className='border-t'>
              <td className='p-2'>{c.name || '-'}</td>
              <td className='p-2'>{c.phone}</td>
              <td className='p-2'>{c.source || 'whatsapp'}</td>
              <td className='p-2'>{(c.tags_json || []).join(', ') || '-'}</td>
              <td className='p-2'>{c.last_interaction_at || '-'}</td>
              <td className='p-2'><code>{JSON.stringify(c.custom_fields_json || {})}</code></td>
              <td className='p-2'><button className='secondary-button' onClick={() => editContact(c)}>Editar</button></td>
            </tr>)}
          </tbody>
        </table>
      </div>
    )}

    {editing && <div className='fixed inset-0 z-50 bg-black/40 p-4'>
      <div className='mx-auto max-w-2xl rounded-xl bg-white p-4 space-y-3'>
        <h2 className='text-lg font-semibold'>Editar contato</h2>
        <input className='premium-input w-full' placeholder='Nome' value={name} onChange={(e)=>setName(e.target.value)} />
        <div className='grid grid-cols-2 gap-2'>
          <input className='premium-input' placeholder='Primeiro nome' value={firstName} onChange={(e)=>setFirstName(e.target.value)} />
          <input className='premium-input' placeholder='Sobrenome' value={lastName} onChange={(e)=>setLastName(e.target.value)} />
        </div>
        <input className='premium-input w-full' placeholder='E-mail' value={email} onChange={(e)=>setEmail(e.target.value)} />
        <input className='premium-input w-full' placeholder='tags separadas por vírgula' value={tags} onChange={(e)=>setTags(e.target.value)} />
        <div className='space-y-2'>
          <p className='text-sm font-medium'>Campos personalizados</p>
          {customFields.map((item, idx) => <div key={idx} className='grid grid-cols-[1fr_1fr_auto] gap-2'>
            <input className='premium-input' placeholder='chave' value={item.key} onChange={(e)=>setCustomFields(prev=>prev.map((v,i)=>i===idx?{...v,key:e.target.value}:v))} />
            <input className='premium-input' placeholder='valor' value={item.value} onChange={(e)=>setCustomFields(prev=>prev.map((v,i)=>i===idx?{...v,value:e.target.value}:v))} />
            <button className='secondary-button' onClick={()=>setCustomFields(prev=>prev.filter((_,i)=>i!==idx))}>Remover</button>
          </div>)}
          <button className='secondary-button' onClick={()=>setCustomFields(prev=>[...prev,{key:'',value:''}])}>+ Adicionar</button>
        </div>
        <div className='flex justify-end gap-2'>
          <button className='secondary-button' onClick={()=>setEditing(null)}>Cancelar</button>
          <button className='primary-button' onClick={()=>void save()} disabled={saving}>{saving ? 'Salvando...' : 'Salvar'}</button>
        </div>
      </div>
    </div>}
  </div>;
}
