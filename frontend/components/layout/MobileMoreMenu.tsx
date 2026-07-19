'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MobileBottomSheet } from './MobileBottomSheet';
import { matchesMobileNavigation, mobileNavigation } from './mobile-navigation';

export function MobileMoreMenu({ open, onClose }: { open: boolean; onClose: () => void }) {
 const pathname = usePathname();
 const items = mobileNavigation.filter((item) => item.showInMoreMenu);
 return <MobileBottomSheet open={open} onClose={onClose} title="Mais">
   <nav className="mobile-more-menu" aria-label="Outros módulos">{items.map((item) => { const Icon = item.icon; const active = matchesMobileNavigation(pathname, item); return <Link key={item.href} href={item.href} onClick={onClose} className={active ? 'is-active' : ''} aria-current={active ? 'page' : undefined}><Icon size={20} aria-hidden="true" /><span>{item.label}</span></Link>; })}</nav>
 </MobileBottomSheet>;
}
