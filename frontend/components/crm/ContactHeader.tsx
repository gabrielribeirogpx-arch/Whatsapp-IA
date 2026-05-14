'use client';

import { memo, useMemo } from 'react';

type Props = { profile: any };

const COLORS = ['bg-blue-500', 'bg-violet-500', 'bg-emerald-500', 'bg-amber-500', 'bg-rose-500'];

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return (parts[0]?.[0] || 'C') + (parts[1]?.[0] || '');
}

function stableColor(seed: string) {
  const hash = seed
    .split("")
    .reduce((acc, char) => acc + char.charCodeAt(0), 0);
  return COLORS[hash % COLORS.length];
}

function ContactHeader({ profile }: Props) {
  const fullName = profile?.name || 'Contato';
  const color = useMemo(() => stableColor(String(profile?.id || fullName)), [profile?.id, fullName]);
  const online = useMemo(() => Number(String(profile?.id || 1).slice(-1)) % 2 === 0, [profile?.id]);

  return <div className='rounded-2xl border border-slate-200 bg-white/90 p-5 shadow-sm'>
    <div className='flex items-center gap-4'>
      <div className={`flex h-16 w-16 items-center justify-center rounded-full text-xl font-bold text-white ${color}`}>{initials(fullName).toUpperCase()}</div>
      <div>
        <h1 className='text-2xl font-semibold text-slate-900'>{fullName}</h1>
        <p className='text-sm text-slate-500'>{profile?.phone || '-'}</p>
        <p className='text-xs mt-1'><span className={`inline-block h-2 w-2 rounded-full ${online ? 'bg-emerald-500' : 'bg-slate-400'}`}/> {online ? 'online' : 'offline'}</p>
      </div>
    </div>
    <div className='mt-4 flex flex-wrap gap-2'>
      {['WhatsApp', 'Contato', 'Cliente', 'VIP'].map((badge) => <span key={badge} className='rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700'>{badge}</span>)}
    </div>
  </div>;
}

export default memo(ContactHeader);
