'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { MobileBottomSheet } from './MobileBottomSheet';

export function ResponsiveDialog({ open, onOpenChange, children, title = 'Diálogo', mobileVariant = 'fullscreen', closeOnBackdrop = true }: {
  open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode; title?: string;
  mobileVariant?: 'fullscreen' | 'sheet'; closeOnBackdrop?: boolean;
}) {
  const [isMobile, setIsMobile] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    const media = window.matchMedia('(max-width: 1023px)');
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    if (!open || isMobile) return;
    const onKeyDown = (event: KeyboardEvent) => event.key === 'Escape' && onOpenChange(false);
    closeButtonRef.current?.focus();
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isMobile, onOpenChange, open]);

  if (!open) return null;
  if (isMobile && mobileVariant === 'sheet') return <MobileBottomSheet open={open} onClose={() => onOpenChange(false)} title={title} closeOnBackdrop={closeOnBackdrop}>{children}</MobileBottomSheet>;
  return <div className="responsive-dialog-backdrop" onMouseDown={() => closeOnBackdrop && onOpenChange(false)}><section className="responsive-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} onMouseDown={(event) => event.stopPropagation()}><header><h2 id={titleId}>{title}</h2><button ref={closeButtonRef} type="button" onClick={() => onOpenChange(false)} aria-label={`Fechar ${title}`}>×</button></header><div>{children}</div></section></div>;
}
