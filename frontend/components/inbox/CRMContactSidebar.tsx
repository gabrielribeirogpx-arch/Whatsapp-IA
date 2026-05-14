'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Avatar from '@/components/Avatar';
import { apiFetch } from '@/lib/api';
import { formatDateTimeBR } from '@/lib/date';
import { Contact } from '@/lib/types';

type Props = { contact?: Contact; open: boolean; onClose: () => void };

const stageLabel: Record<string, string> = { lead: 'contato' };
const tempLabel: Record<string, string> = { cold: 'frio', warm: 'morno', hot: 'quente' };

const getEventTone = (type: string) => {
  const t = type.toLowerCase();
  if (t.includes('message') || t.includes('mensag')) return 'message';
  if (t.includes('flow') || t.includes('autom')) return 'flow';
  if (t.includes('campaign') || t.includes('campanha')) return 'campaign';
  if (t.includes('tag') || t.includes('etiqueta')) return 'tag';
  return 'default';
};

export default function CRMContactSidebar({ contact, open, onClose }: Props) {
  const [profile, setProfile] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [tag, setTag] = useState('');
  const [note, setNote] = useState('');
  const timelineRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async (id: string) => {
    setLoading(true);
    try {
      const [p, e] = await Promise.all([
        apiFetch(`/api/contacts/${id}`).then((r) => r.json()),
        apiFetch(`/api/contacts/${id}/events`).then((r) => r.json())
      ]);
      setProfile(p.contact || null);
      setEvents(e.items || []);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (contact?.id) void load(contact.id);
    else {
      setProfile(null);
      setEvents([]);
    }
  }, [contact?.id, load]);

  useEffect(() => {
    if (!contact?.id || typeof window === 'undefined') return;
    const tenantId = localStorage.getItem('tenant_id');
    const apiUrl = process.env.NEXT_PUBLIC_API_URL;
    if (!tenantId || !apiUrl) return;

    const baseUrl = apiUrl.endsWith('/') ? apiUrl.slice(0, -1) : apiUrl;
    const es = new EventSource(`${baseUrl}/api/crm/contacts/${contact.id}/events/stream?tenant_id=${encodeURIComponent(tenantId)}`);

    es.onmessage = (msg) => {
      try {
        const incoming = JSON.parse(msg.data || '{}');
        if (!incoming?.id) return;
        setEvents((prev) => (prev.some((i) => i.id === incoming.id) ? prev : [incoming, ...prev]));
        setProfile((prev: any) => (prev ? { ...prev, last_interaction_at: incoming.created_at || prev.last_interaction_at } : prev));
        timelineRef.current?.scrollTo({ top: 0, behavior: 'smooth' });
      } catch {}
    };

    es.onerror = () => es.close();
    return () => es.close();
  }, [contact?.id]);

  const metrics = useMemo(
    () => [
      ['Mensagens', profile?.messages_count ?? 0],
      ['Campanhas', profile?.campaigns_received ?? 0],
      ['Automações', profile?.flows_executed ?? 0],
      ['Última campanha', profile?.last_campaign_at ? formatDateTimeBR(profile.last_campaign_at) : '-'],
      ['Taxa resposta', `${profile?.response_rate ?? 0}%`]
    ],
    [profile]
  );

  const customFields = Object.entries(profile?.custom_fields_json || {});
  const temperature = (profile?.temperature || 'warm').toLowerCase();

  return (
    <aside className={`wa-crm-sidebar ${open ? 'open' : ''}`}>
      <div className='wa-crm-mobile-header'>
        <strong>CRM do contato</strong>
        <button className='ghost-button' onClick={onClose}>Fechar</button>
      </div>

      {!contact ? (
        <div className='wa-crm-empty'><p>Selecione uma conversa para visualizar o CRM do contato.</p></div>
      ) : (
        <div className='wa-crm-content'>
          <section className='wa-crm-card wa-crm-hero'>
            <div className='wa-crm-contact-head'>
              <div className={`wa-crm-avatar-glow ${contact.isOnline ? 'is-online' : ''}`}>
                <Avatar name={profile?.name || contact.name} avatarUrl={profile?.avatar_url || contact.avatarUrl} phone={contact.phone} />
              </div>
              <div>
                <h3>{profile?.name || contact.name || contact.phone}</h3>
                <p className='wa-crm-phone'>{contact.phone}</p>
                <p className={`wa-crm-online ${contact.isOnline ? 'is-online' : ''}`}>{contact.isOnline ? 'Online agora' : 'Offline'} • Último contato: {formatDateTimeBR(profile?.last_interaction_at || contact.lastMessageAt)}</p>
              </div>
            </div>
            <div className='wa-crm-badges'>
              <span>WhatsApp</span><span>Lead</span><span>Cliente</span><span>VIP</span>
              <span className={`temp-badge temp-${temperature}`}>{tempLabel[temperature] || 'morno'}</span>
            </div>
          </section>

          <section className='wa-crm-card'><h4>Perfil</h4><p>Etapa do cliente: {stageLabel[(profile?.lifecycle_stage || profile?.stage || '').toLowerCase()] || profile?.lifecycle_stage || 'contato'}</p><p>Origem: {profile?.source || '-'}</p><p>Último contato: {formatDateTimeBR(profile?.last_interaction_at || contact.lastMessageAt)}</p></section>

          <section className='wa-crm-card'><h4>Etiquetas</h4><div className='wa-crm-tags'>{(profile?.tags_json || []).map((t: string) => <span key={t}>{t}</span>)}</div><div className='wa-crm-inline'><input className='premium-input' value={tag} onChange={(e) => setTag(e.target.value)} placeholder='Adicionar etiqueta' /><button className='secondary-button' onClick={async () => { if (!contact?.id || !tag.trim()) return; const v = tag.trim(); setProfile((p: any) => p ? { ...p, tags_json: [...(p.tags_json || []), v] } : p); setTag(''); await apiFetch(`/api/contacts/${contact.id}/tags`, { method: 'POST', body: JSON.stringify({ tag: v }) }); }}>+</button></div></section>

          <section className='wa-crm-card'><h4>Histórico de atividades</h4><div className='wa-crm-timeline' ref={timelineRef}>{loading ? <div className='wa-crm-skeleton' /> : events.length === 0 ? <p className='wa-crm-muted'>Sem atividades registradas.</p> : events.slice(0, 12).map((e) => { const tone = getEventTone(e.type || e.title || ''); return <article key={e.id} className={`wa-crm-event tone-${tone}`}><span className='wa-crm-event-dot' aria-hidden='true' /><div><strong>{e.title || e.type || 'atividade'}</strong><p>{e.description || 'Atualização do contato.'}</p><time>{formatDateTimeBR(e.created_at)}</time></div></article>; })}</div></section>

          <section className='wa-crm-card'><h4>Métricas</h4><div className='wa-crm-metrics'>{metrics.map(([l, v]) => <div key={String(l)}><small>{l}</small><strong>{String(v)}</strong></div>)}</div></section>

          <section className='wa-crm-card'><h4>Observações internas</h4><textarea className='premium-input min-h-24 w-full' value={note} onChange={(e) => setNote(e.target.value)} placeholder='Escreva uma nota interna…' /><button className='secondary-button mt-2' onClick={async () => { if (!contact?.id || !note.trim()) return; const v = note.trim(); setEvents((prev) => [{ id: `local-${Date.now()}`, type: 'note_added', description: v, created_at: new Date().toISOString() }, ...prev]); setNote(''); await apiFetch(`/api/contacts/${contact.id}/notes`, { method: 'POST', body: JSON.stringify({ note: v }) }); }}>Salvar nota</button></section>

          <section className='wa-crm-card'><h4>Informações personalizadas</h4>{customFields.length === 0 ? <p className='wa-crm-muted'>Nenhum campo personalizado.</p> : customFields.map(([k, v]) => <p key={k}><strong>{k}:</strong> {String(v)}</p>)}</section>
        </div>
      )}
    </aside>
  );
}
