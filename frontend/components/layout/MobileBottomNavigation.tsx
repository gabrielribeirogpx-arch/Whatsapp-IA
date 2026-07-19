'use client';

import Link from 'next/link';
import { Bot, LayoutDashboard, MessageCircle, MoreHorizontal, PanelsTopLeft } from 'lucide-react';
import { usePathname } from 'next/navigation';

const destinations = [
  { label: 'Início', href: '/dashboard', icon: LayoutDashboard, matches: (p: string) => p === '/dashboard' },
  { label: 'Conversas', href: '/dashboard/inbox', icon: MessageCircle, matches: (p: string) => p.startsWith('/dashboard/inbox') },
  { label: 'CRM', href: '/dashboard/pipeline', icon: PanelsTopLeft, matches: (p: string) => p.startsWith('/dashboard/pipeline') || p.startsWith('/dashboard/contacts') || p.startsWith('/dashboard/clients') },
  { label: 'Fluxos', href: '/dashboard/flows', icon: Bot, matches: (p: string) => p.startsWith('/dashboard/flows') || p.startsWith('/dashboard/flow-builder') },
] as const;

export function MobileBottomNavigation({ onMore }: { onMore: () => void }) {
  const pathname = usePathname();
  const hasPrimary = destinations.some((item) => item.matches(pathname));
  return <nav className="mobile-bottom-nav pb-safe" aria-label="Navegação principal">
    {destinations.map((item) => { const Icon = item.icon; const active = item.matches(pathname); return <Link key={item.href} href={item.href} className={`mobile-nav-item ${active ? 'is-active' : ''}`} aria-current={active ? 'page' : undefined}><Icon size={21} aria-hidden="true" /><span>{item.label}</span></Link>; })}
    <button type="button" className={`mobile-nav-item ${!hasPrimary ? 'is-active' : ''}`} onClick={onMore} aria-label="Abrir mais módulos"><MoreHorizontal size={22} aria-hidden="true" /><span>Mais</span></button>
  </nav>;
}
