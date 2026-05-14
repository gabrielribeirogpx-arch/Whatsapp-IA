'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { CRMContact } from '@/lib/types';
import { formatDateTimeBR } from '@/lib/date';

export default function ContactsPage() {
  const [contacts, setContacts] = useState<CRMContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');

  useEffect(() => {
    void (async () => {
      const response = await apiFetch('/api/contacts', { cache: 'no-store' });
      const data = await response.json();
      setContacts(Array.isArray(data?.items) ? data.items : []);
      setLoading(false);
    })();
  }, []);

  const filtered = contacts.filter((c) => `${c.name || ''} ${c.phone || ''}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className='space-y-4 p-6'>
      <h1 className='text-2xl font-semibold'>Contatos</h1>
      <input className='premium-input w-full max-w-sm' placeholder='Buscar por nome/telefone' value={search} onChange={(e) => setSearch(e.target.value)} />
      {loading ? <p>Carregando...</p> : null}
      <div className='overflow-auto rounded-xl border border-slate-200 bg-white'>
        <table className='min-w-full text-sm'>
          <thead className='bg-slate-50 text-left text-slate-700'><tr><th className='p-3 font-semibold'>Nome</th><th className='p-3 font-semibold'>Telefone</th><th className='p-3 font-semibold'>Etiquetas</th><th className='p-3 font-semibold'>Temperatura</th><th className='p-3 font-semibold'>Etapa do cliente</th><th className='p-3 font-semibold'>Último contato</th></tr></thead>
          <tbody>
            {filtered.map((contact) => (
              <tr key={contact.id} className='border-t text-slate-700'>
                <td className='p-3'><Link className='font-medium text-blue-600 hover:text-blue-700 hover:underline' href={`/dashboard/contacts/${contact.id}`}>{contact.name || '-'}</Link></td>
                <td className='p-3'>{contact.phone || '-'}</td>
                <td className='p-3'>{(contact.tags_json || []).join(', ') || '-'}</td>
                <td className='p-3'>{contact.score ?? 0}</td>
                <td className='p-3'>{contact.lifecycle_stage || '-'}</td>
                <td className='p-3'>{formatDateTimeBR(contact.last_interaction_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
