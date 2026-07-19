'use client';

import { ReactNode, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { MobileBottomNavigation } from './MobileBottomNavigation';
import { MobileHeader } from './MobileHeader';
import { MobileMoreMenu } from './MobileMoreMenu';
import { MobilePageContainer } from './MobilePageContainer';

export function AppShell({ children, title, backHref }: { children: ReactNode; title: string; backHref?: string }) {
 const [moreOpen, setMoreOpen] = useState(false);
 const pathname = usePathname();
 const searchParams = useSearchParams();
  // Inbox owns its native chat chrome. Its existing conversation URL is the shared state.
 const isInbox = pathname.startsWith('/dashboard/inbox');
 const inboxConversation = isInbox && Boolean(searchParams.get('conversation') || searchParams.get('contact_id'));
 return <div className={`mobile-app-shell ${inboxConversation ? 'mobile-app-shell--inbox-conversation' : ''}`}><MobileHeader title={title} backHref={backHref} hidden={isInbox} /><MobilePageContainer bottomNavigation={!inboxConversation}>{children}</MobilePageContainer>{!inboxConversation ? <><MobileBottomNavigation onMore={() => setMoreOpen(true)} /><MobileMoreMenu open={moreOpen} onClose={() => setMoreOpen(false)} /></> : null}</div>;
}
