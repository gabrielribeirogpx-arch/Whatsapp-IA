'use client';

import { ReactNode, useEffect } from 'react';
import { X } from 'lucide-react';

export function MobileBottomSheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', closeOnEscape);
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener('keydown', closeOnEscape); };
  }, [open, onClose]);
  if (!open) return null;
  return <div className="mobile-sheet-backdrop" role="presentation" onMouseDown={onClose}>
    <section className="mobile-bottom-sheet pb-safe" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
      <div className="mobile-sheet-handle" aria-hidden="true" />
      <header className="mobile-sheet-header"><h2>{title}</h2><button type="button" onClick={onClose} aria-label="Fechar menu"><X size={20} /></button></header>
      <div className="mobile-sheet-content">{children}</div>
    </section>
  </div>;
}
