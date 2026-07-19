'use client';

import { ReactNode, useEffect, useId, useRef } from 'react';
import { X } from 'lucide-react';

export function MobileBottomSheet({ open, onClose, title, children, closeOnBackdrop = true, footer, fullScreen = false }: { open: boolean; onClose: () => void; title: string; children: ReactNode; closeOnBackdrop?: boolean; footer?: ReactNode; fullScreen?: boolean }) {
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => event.key === 'Escape' && onClose();
    const previousOverflow = document.body.style.overflow;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    window.addEventListener('keydown', closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', closeOnEscape);
      returnFocusRef.current?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return <div className="mobile-sheet-backdrop" role="presentation" onMouseDown={() => closeOnBackdrop && onClose()}>
    <section className={`mobile-bottom-sheet pb-safe${fullScreen ? ' mobile-bottom-sheet-fullscreen' : ''}`} role="dialog" aria-modal="true" aria-labelledby={titleId} onMouseDown={(event) => event.stopPropagation()}>
      <div className="mobile-sheet-handle" aria-hidden="true" />
      <header className="mobile-sheet-header"><h2 id={titleId}>{title}</h2><button ref={closeButtonRef} type="button" onClick={onClose} aria-label={`Fechar ${title}`}><X size={20} /></button></header>
      <div className="mobile-sheet-content">{children}</div>
      {footer ? <footer className="mobile-sheet-footer">{footer}</footer> : null}
    </section>
  </div>;
}
