'use client';

import Link from 'next/link';
import { MoreHorizontal } from 'lucide-react';
import { usePathname } from 'next/navigation';
import { matchesMobileNavigation, mobileNavigation } from './mobile-navigation';

export function MobileBottomNavigation({ onMore }: { onMore: () => void }) {
  const pathname = usePathname();
  const destinations = mobileNavigation.filter((item) => item.showInBottomNav);
  const hasPrimary = destinations.some((item) => matchesMobileNavigation(pathname, item));
  return <nav className="mobile-bottom-nav pb-safe" aria-label="Navegação principal">
    {destinations.map((item) => { const Icon = item.icon; const active = matchesMobileNavigation(pathname, item); return <Link key={item.href} href={item.href} className={`mobile-nav-item ${active ? 'is-active' : ''}`} aria-current={active ? 'page' : undefined}><Icon size={21} aria-hidden="true" /><span>{item.label}</span></Link>; })}
    <button type="button" className={`mobile-nav-item ${!hasPrimary ? 'is-active' : ''}`} onClick={onMore} aria-label="Abrir mais módulos"><MoreHorizontal size={22} aria-hidden="true" /><span>Mais</span></button>
  </nav>;
}
