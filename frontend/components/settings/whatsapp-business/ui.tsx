'use client';

import { AlertCircle, CheckCircle2, Clock3, Link2Off, PauseCircle, ShieldAlert } from 'lucide-react';
import { useEffect, useState } from 'react';

const badgeStyles: Record<string, string> = {
  connected: 'bg-gradient-to-r from-emerald-500/10 to-emerald-100/80 text-emerald-700 border-emerald-600/20',
  disconnected: 'bg-slate-500/10 text-slate-700 border-slate-500/20',
  token_expired: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
  invalid_token: 'bg-rose-500/10 text-rose-700 border-rose-500/20',
  invalid_phone_number: 'bg-rose-500/10 text-rose-700 border-rose-500/20',
  meta_error: 'bg-orange-500/10 text-orange-700 border-orange-500/20',
  invalid_config: 'bg-rose-500/10 text-rose-700 border-rose-500/20',
  active: 'bg-gradient-to-r from-green-500/10 to-green-100/80 text-green-700 border-green-500/20',
  inactive: 'bg-zinc-500/10 text-zinc-700 border-zinc-500/20',
  draft: 'bg-zinc-500/10 text-zinc-700 border-zinc-500/20',
  submitted: 'bg-sky-500/10 text-sky-700 border-sky-500/20',
  pending: 'bg-amber-500/10 text-amber-700 border-amber-500/20',
  approved: 'bg-gradient-to-r from-emerald-500/10 to-emerald-100/80 text-emerald-700 border-emerald-500/20',
  rejected: 'bg-rose-500/10 text-rose-700 border-rose-500/20',
  paused: 'bg-violet-500/10 text-violet-700 border-violet-500/20'
};

const iconMap: Record<string, JSX.Element> = {
  connected: <>🟢</>, disconnected: <Link2Off size={12} />, token_expired: <>🟡</>, invalid_token: <ShieldAlert size={12} />, invalid_phone_number: <>🔴</>, meta_error: <>🟠</>, invalid_config: <ShieldAlert size={12} />,
  active: <CheckCircle2 size={12} />, inactive: <PauseCircle size={12} />, draft: <Clock3 size={12} />,
  submitted: <Clock3 size={12} />, pending: <Clock3 size={12} />, approved: <CheckCircle2 size={12} />,
  rejected: <AlertCircle size={12} />, paused: <PauseCircle size={12} />
};

export function StatusBadge({ value }: { value: string }) {
  const style = badgeStyles[value] ?? 'bg-slate-500/10 text-slate-700 border-slate-500/20';
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-semibold capitalize tracking-wide ${style}`}>{iconMap[value]}{value}</span>;
}

export function toLocalDate(date?: string | null) {
  if (!date) return '—';
  const parsed = new Date(date);
  return Number.isNaN(parsed.valueOf()) ? '—' : parsed.toLocaleString('pt-BR');
}

export function ClientDateTime({ value, fallback = '—' }: { value?: string | null; fallback?: string }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <>{fallback}</>;
  return <>{toLocalDate(value)}</>;
}
