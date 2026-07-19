'use client';

import { ReactNode, useEffect, useRef } from 'react';
import { X } from 'lucide-react';

export function MobileBottomSheet({ open, onClose, title, children, closeOnBackdrop = true, footer }: { open: boolean; onClose: () => void; title: string; children: ReactNode; closeOnBackdrop?: boolean; footer?: ReactNode }) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    window.addEventListener('keydown', closeOnEscape);
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener('keydown', closeOnEscape); };
  }, [open, onClose]);
  if (!open) return null;
  return <div className="mobile-sheet-backdrop" role="presentation" onMouseDown={() => closeOnBackdrop && onClose()}>
    <section className="mobile-bottom-sheet pb-safe" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}>
      <div className="mobile-sheet-handle" aria-hidden="true" />
      <header className="mobile-sheet-header"><h2>{title}</h2><button ref={closeButtonRef} type="button" onClick={onClose} aria-label="Fechar menu"><X size={20} /></button></header>
      <div className="mobile-sheet-content">{children}</div>
      {footer ? <footer className="mobile-sheet-footer">{footer}</footer> : null}
    </section>
  </div>;
}
