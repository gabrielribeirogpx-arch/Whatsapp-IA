'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { CRMContact } from '@/lib/types';
import { formatDateTimeBR } from '@/lib/date';
import { ListSkeleton } from '@/components/ui/loading';
import { ResponsiveDataView } from '@/components/layout/ResponsiveDataView';
import { MobileListCard } from '@/components/layout/MobileListCard';
import { MobilePageContainer } from '@/components/layout/MobilePageContainer';
import { ResponsiveFilterToolbar } from '@/components/layout/ResponsiveFilterToolbar';
import { ResponsivePageHeader } from '@/components/layout/ResponsivePageHeader';

export default function ContactsPage() {
  const [contacts, setContacts] = useState<CRMContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [error, setError] = useState<string | null>(null);

  const loadContacts = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiFetch('/api/contacts', { cache: 'no-store' });
      if (!response.ok) throw new Error('Não foi possível carregar os contatos.');
      const data = await response.json();
      setContacts(Array.isArray(data?.items) ? data.items : []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Não foi possível carregar os contatos.');
    } finally { setLoading(false); }
  };

  useEffect(() => {
    void loadContacts();
  }, []);

  const filtered = useMemo(() => contacts.filter((c) => `${c.name || ''} ${c.phone || ''}`.toLowerCase().includes(search.toLowerCase())), [contacts, search]);

  return (
    <MobilePageContainer className='contacts-page'>
      <div className='space-y-4'>
      <ResponsivePageHeader title='Contatos' description='Consulte e gerencie seus contatos.' />
      <ResponsiveFilterToolbar
        activeCount={search ? 1 : 0}
        onClear={() => setSearch('')}
        search={<input className='min-w-0 flex-1 bg-transparent text-base outline-none' aria-label='Buscar contatos por nome ou telefone' placeholder='Buscar por nome ou telefone' value={search} onChange={(e) => setSearch(e.target.value)} />}
        filters={<label className='text-sm text-slate-600'>Busca atual <input className='premium-input mt-1 w-full' value={search} onChange={(e) => setSearch(e.target.value)} placeholder='Nome ou telefone' /></label>}
      />
      <ResponsiveDataView data={filtered} loading={loading}
        loadingState={<ListSkeleton items={6} />}
        error={<div role='alert' className='rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700'>{error}<button className='ml-3 underline' onClick={() => void loadContacts()}>Tentar novamente</button></div>}
        className='overflow-auto rounded-xl border border-slate-200 bg-white'
        desktopView={<table className='min-w-full text-sm'><thead className='bg-slate-50 text-left text-slate-700'><tr><th className='p-3 font-semibold'>Nome</th><th className='p-3 font-semibold'>Telefone</th><th className='p-3 font-semibold'>Etiquetas</th><th className='p-3 font-semibold'>Temperatura</th><th className='p-3 font-semibold'>Etapa do cliente</th><th className='p-3 font-semibold'>Último contato</th></tr></thead><tbody>{filtered.map((contact) => <tr key={contact.id} className='border-t text-slate-700'><td className='p-3'><Link className='font-medium text-blue-600 hover:text-blue-700 hover:underline' href={`/dashboard/contacts/${contact.id}`}>{contact.name || '-'}</Link></td><td className='p-3'>{contact.phone || '-'}</td><td className='p-3'>{(contact.tags_json || []).join(', ') || '-'}</td><td className='p-3'>{contact.score ?? 0}</td><td className='p-3'>{contact.lifecycle_stage || '-'}</td><td className='p-3'>{formatDateTimeBR(contact.last_interaction_at)}</td></tr>)}</tbody></table>}
        mobileView={(contact) => <MobileListCard key={contact.id} title={<Link href={`/dashboard/contacts/${contact.id}`}>{contact.name || 'Sem nome'}</Link>} subtitle={contact.phone || 'Sem telefone'} status={<span className='responsive-data-status'>{contact.lifecycle_stage || 'Sem etapa'}</span>} meta={<span>Último contato: {formatDateTimeBR(contact.last_interaction_at)}</span>}><div className='flex flex-wrap gap-1'>{(contact.tags_json || []).slice(0, 3).map((tag) => <span key={tag} className='responsive-data-tag'>{tag}</span>)}</div></MobileListCard>}
        emptyState={<div className='rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500'>{search ? 'Nenhum contato corresponde aos filtros aplicados.' : 'Ainda não há contatos.'}</div>}
      />
      </div>
    </MobilePageContainer>
  );
}
