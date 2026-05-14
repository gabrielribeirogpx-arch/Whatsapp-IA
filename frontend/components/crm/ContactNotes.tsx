'use client';

import { memo } from 'react';

function ContactNotes({ notes, note, setNote, onSave }: { notes: any[]; note: string; setNote: (x: string) => void; onSave: () => void }) {
  return <div className='space-y-3'>
    <div className='space-y-2'>
      {notes.length === 0 ? <p className='text-sm text-slate-400'>Sem notas registradas.</p> : notes.map((n, idx) => <div key={n.id || idx} className='rounded-xl border border-slate-200 bg-white p-3 shadow-sm transition hover:shadow'>
        <p className='text-sm text-slate-800'>{n.note || n.description || '-'}</p>
        <p className='mt-1 text-xs text-slate-500'>{n.author || 'Equipe'} • {new Date(n.created_at || Date.now()).toLocaleString('pt-BR')}</p>
      </div>)}
    </div>
    <textarea className='premium-input min-h-24 w-full' value={note} onChange={(e) => setNote(e.target.value)} placeholder='Escreva uma nota interna...' />
    <button className='secondary-button' onClick={onSave}>Salvar nota</button>
  </div>;
}

export default memo(ContactNotes);
