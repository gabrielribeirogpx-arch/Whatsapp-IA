'use client';

import Link from 'next/link';
import { Bell, ChevronLeft } from 'lucide-react';
import type { ReactNode } from 'react';

export function MobileHeader({ title, backHref, action, showLogo = true, hidden = false }: { title: string; backHref?: string; action?: ReactNode; showLogo?: boolean; hidden?: boolean }) {
  if (hidden) return null;
  return <header className="mobile-header pt-safe">
    <div className="mobile-header-inner">
      {backHref ? <Link className="mobile-icon-button" href={backHref} aria-label="Voltar"><ChevronLeft size={22} /></Link> : showLogo ? <Link className="mobile-brand" href="/dashboard" aria-label="Início Wazza"><img src="/Logo.svg" alt="" /><span>Wazza</span></Link> : <span />}
      <h1>{title}</h1>
      {action ?? <button className="mobile-icon-button" type="button" aria-label="Notificações"><Bell size={19} /></button>}
    </div>
  </header>;
}
