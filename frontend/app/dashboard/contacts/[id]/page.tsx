'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch } from '@/lib/api';
import ContactHeader from '@/components/crm/ContactHeader';
import ContactMetrics from '@/components/crm/ContactMetrics';
import ContactNotes from '@/components/crm/ContactNotes';
import ContactSidebar from '@/components/crm/ContactSidebar';
import ContactTags from '@/components/crm/ContactTags';
import ContactTimeline from '@/components/crm/ContactTimeline';

export default function ContactProfilePage({ params }: { params: { id: string } }) {
  const [profile, setProfile] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [note, setNote] = useState('');
  const [tag, setTag] = useState('');
  const [highlightedId, setHighlightedId] = useState<string | null>(null);
  const timelineContainerRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [p, e] = await Promise.all([
      apiFetch(`/api/contacts/${params.id}`).then((r) => r.json()),
      apiFetch(`/api/contacts/${params.id}/events`).then((r) => r.json())
    ]);
    setProfile(p.contact);
    setEvents(e.items || []);
    setLoading(false);
  }, [params.id]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!profile?.id || typeof window === 'undefined') return;
    const tenantId = localStorage.getItem('tenant_id');
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!tenantId || !apiUrl) return;

    const baseUrl = apiUrl.endsWith('/') ? apiUrl.slice(0, -1) : apiUrl;
    let closed = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let eventSource: EventSource | null = null;

    const connect = () => {
      if (closed) return;
      eventSource = new EventSource(`${baseUrl}/api/crm/contacts/${profile.id}/events/stream?tenant_id=${encodeURIComponent(tenantId)}`);
      eventSource.onmessage = (msg) => {
        try {
          const incoming = JSON.parse(msg.data || '{}');
          if (!incoming?.id) return;

          setEvents((prev) => {
            if (prev.some((item) => item.id === incoming.id)) return prev;
            return [incoming, ...prev];
          });

          setProfile((prev: any) => prev ? {
            ...prev,
            last_interaction_at: incoming.created_at || prev.last_interaction_at,
            score: (Number(prev.score || 0) + (incoming.type === 'message_received' ? 6 : incoming.type === 'flow_completed' ? 15 : incoming.type === 'message_sent' ? 3 : 2)),
            messages_count: Number(prev.messages_count || 0) + ((incoming.type === 'message_received' || incoming.type === 'message_sent') ? 1 : 0),
            campaigns_received: Number(prev.campaigns_received || 0) + (incoming.type === 'campaign_sent' ? 1 : 0),
            flows_executed: Number(prev.flows_executed || 0) + ((incoming.type === 'flow_started' || incoming.type === 'flow_completed') ? 1 : 0),
          } : prev);

          setHighlightedId(incoming.id);
          setTimeout(() => setHighlightedId((current) => (current === incoming.id ? null : current)), 1800);
          timelineContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
        } catch {
          // ignore malformed payloads
        }
      };

      eventSource.onerror = () => {
        eventSource?.close();
        if (!closed) reconnectTimer = setTimeout(connect, 2000);
      };
    };

    connect();

    return () => {
      closed = true;
      eventSource?.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [profile?.id]);

  const scoreView = useMemo(() => {
    const score = Number(profile?.score || 0);
    if (score <= 20) return ['Frio', 'bg-sky-100 text-sky-700'];
    if (score <= 50) return ['Morno', 'bg-amber-100 text-amber-700'];
    if (score <= 80) return ['Quente', 'bg-orange-100 text-orange-700'];
    return ['VIP', 'bg-violet-100 text-violet-700'];
  }, [profile?.score]);

  const notes = useMemo(() => events.filter((e) => (e.type || '').includes('note')), [events]);
  const customFields = useMemo(() => Object.entries(profile?.custom_fields_json || {}), [profile?.custom_fields_json]);

  if (loading && !profile) return <div className='p-6'><div className='h-10 w-64 animate-pulse rounded-xl bg-slate-100'/></div>;

  return <div className='grid grid-cols-12 gap-4 p-6 bg-slate-50 min-h-screen'>
    <aside className='col-span-12 lg:col-span-3 space-y-4'>
      <ContactHeader profile={profile} />
      <ContactSidebar title='Perfil'>
        <p className='text-sm text-slate-700'>Etapa do cliente: <span className='rounded-full bg-slate-100 px-2 py-1 text-xs font-medium'>{profile?.lifecycle_stage || 'contato'}</span></p>
        <p className='mt-2 text-sm text-slate-700'>Temperatura: <span className={`rounded-full px-2 py-1 text-xs font-semibold ${scoreView[1]}`}>{profile?.score ?? 0} • {scoreView[0]}</span></p>
        <p className='mt-2 text-sm text-slate-700'>Origem: {profile?.source || '-'}</p>
        <p className='mt-2 text-sm text-slate-700'>Último contato: {profile?.last_interaction_at ? new Date(profile.last_interaction_at).toLocaleString('pt-BR') : '-'}</p>
      </ContactSidebar>
      <ContactSidebar title='Etiquetas'>
        <ContactTags tags={profile?.tags_json || []} />
        <div className='mt-3 flex gap-2'><input className='premium-input w-full' value={tag} onChange={(e) => setTag(e.target.value)} placeholder='Nova tag' /><button className='secondary-button' onClick={async () => { await apiFetch(`/api/contacts/${params.id}/tags`, { method: 'POST', body: JSON.stringify({ tag }) }); setTag(''); await load(); }}>+</button></div>
      </ContactSidebar>
      <div className='grid grid-cols-2 gap-2'>
        <a className='secondary-button text-center' href={`/dashboard/inbox?contact_id=${params.id}`}>Abrir no Inbox</a>
        <button className='secondary-button'>Enviar campanha</button>
      </div>
    </aside>
    <section className='col-span-12 lg:col-span-6 rounded-2xl border border-slate-200 bg-white/90 p-4 shadow-sm'>
      <h2 className='mb-3 text-lg font-semibold text-slate-900'>Histórico de atividades</h2>
      <ContactTimeline events={events} loading={loading} highlightedId={highlightedId} containerRef={timelineContainerRef} />
    </section>
    <aside className='col-span-12 lg:col-span-3 space-y-4'>
      <ContactSidebar title='Métricas'><ContactMetrics profile={profile} /></ContactSidebar>
      <ContactSidebar title='Observações internas'>
        <ContactNotes notes={notes} note={note} setNote={setNote} onSave={async () => { await apiFetch(`/api/contacts/${params.id}/notes`, { method: 'POST', body: JSON.stringify({ note }) }); setNote(''); await load(); }} />
      </ContactSidebar>
      <ContactSidebar title='Informações personalizadas'>
        {customFields.length === 0 ? <p className='text-sm text-slate-400'>Nenhum campo personalizado.</p> : <div className='space-y-2'>{customFields.map(([k, v]) => <div key={k} className='rounded-lg bg-slate-50 px-3 py-2 text-sm'><span className='font-medium text-slate-700'>{k}</span><span className='text-slate-500'> → {String(v)}</span></div>)}</div>}
      </ContactSidebar>
    </aside>
  </div>;
}
