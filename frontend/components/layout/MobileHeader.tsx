'use client';

import Link from 'next/link';
import { Bell, ChevronLeft } from 'lucide-react';

export function MobileHeader({ title, backHref }: { title: string; backHref?: string }) {
  return <header className="mobile-header pt-safe">
    <div className="mobile-header-inner">
      {backHref ? <Link className="mobile-icon-button" href={backHref} aria-label="Voltar"><ChevronLeft size={22} /></Link> : <Link className="mobile-brand" href="/dashboard" aria-label="Início Wazza"><img src="/Logo.svg" alt="" /><span>Wazza</span></Link>}
      <h1>{title}</h1>
      <button className="mobile-icon-button" type="button" aria-label="Notificações"><Bell size={19} /></button>
    </div>
  </header>;
}
