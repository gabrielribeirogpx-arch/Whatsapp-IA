'use client';

import { ReactNode, useState } from 'react';
import { MobileBottomNavigation } from './MobileBottomNavigation';
import { MobileHeader } from './MobileHeader';
import { MobileMoreMenu } from './MobileMoreMenu';

export function AppShell({ children, title, backHref }: { children: ReactNode; title: string; backHref?: string }) {
 const [moreOpen, setMoreOpen] = useState(false);
 return <><MobileHeader title={title} backHref={backHref} /><div className="mobile-page-container">{children}</div><MobileBottomNavigation onMore={() => setMoreOpen(true)} /><MobileMoreMenu open={moreOpen} onClose={() => setMoreOpen(false)} /></>;
}
