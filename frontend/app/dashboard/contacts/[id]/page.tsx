'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

export default function ContactProfilePage({ params }: { params: { id: string } }) {
  const [profile, setProfile] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [note, setNote] = useState('');
  const [tag, setTag] = useState('');

  const load = async () => {
    const [p, e] = await Promise.all([
      apiFetch(`/api/contacts/${params.id}`).then((r) => r.json()),
      apiFetch(`/api/contacts/${params.id}/events`).then((r) => r.json())
    ]);
    setProfile(p.contact);
    setEvents(e.items || []);
  };

  useEffect(() => { void load(); }, [params.id]);
  if (!profile) return <div className='p-6'>Carregando perfil...</div>;

  return <div className='grid grid-cols-12 gap-4 p-6'>
    <aside className='col-span-3 rounded-xl border p-4 bg-white'>
      <h1 className='text-xl font-semibold'>{profile.name || 'Contato'}</h1>
      <p>{profile.phone}</p><p>Score: {profile.score}</p><p>Lifecycle: {profile.lifecycle_stage || '-'}</p>
      <p>Source: {profile.source || '-'}</p><p>Última interação: {profile.last_interaction_at || '-'}</p>
      <p>Tags: {(profile.tags_json || []).join(', ') || '-'}</p>
    </aside>
    <section className='col-span-6 rounded-xl border p-4 bg-white'>
      <h2 className='font-semibold mb-3'>Timeline</h2>
      <div className='space-y-2'>{events.map((e)=><div key={e.id} className='border rounded p-2'><p className='font-medium'>{e.title}</p><p className='text-sm'>{e.description}</p></div>)}</div>
    </section>
    <aside className='col-span-3 rounded-xl border p-4 bg-white space-y-2'>
      <p>Campanhas recebidas: {profile.campaigns_received}</p><p>Flows executados: {profile.flows_executed}</p>
      <textarea className='premium-input w-full' value={note} onChange={(e)=>setNote(e.target.value)} placeholder='Nova nota' />
      <button className='secondary-button' onClick={async()=>{await apiFetch(`/api/contacts/${params.id}/notes`,{method:'POST',body:JSON.stringify({note})}); setNote(''); await load();}}>Salvar nota</button>
      <input className='premium-input w-full' value={tag} onChange={(e)=>setTag(e.target.value)} placeholder='Nova tag' />
      <button className='secondary-button' onClick={async()=>{await apiFetch(`/api/contacts/${params.id}/tags`,{method:'POST',body:JSON.stringify({tag})}); setTag(''); await load();}}>Adicionar tag</button>
    </aside>
  </div>;
}
