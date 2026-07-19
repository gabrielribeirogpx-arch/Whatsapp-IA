'use client';

import type { ReactNode } from 'react';
import { MobileBottomSheet } from './MobileBottomSheet';

export function ResponsiveDialog({ open, onOpenChange, children, title = 'Diálogo', mobileVariant = 'fullscreen', closeOnBackdrop = true }: {
  open: boolean; onOpenChange: (open: boolean) => void; children: ReactNode; title?: string;
  mobileVariant?: 'fullscreen' | 'sheet'; closeOnBackdrop?: boolean;
}) {
  if (!open) return null;
  if (mobileVariant === 'sheet') return <MobileBottomSheet open={open} onClose={() => onOpenChange(false)} title={title} closeOnBackdrop={closeOnBackdrop}>{children}</MobileBottomSheet>;
  return <div className="responsive-dialog-backdrop" onMouseDown={() => closeOnBackdrop && onOpenChange(false)}><section className="responsive-dialog" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(event) => event.stopPropagation()}><header><h2>{title}</h2><button type="button" onClick={() => onOpenChange(false)} aria-label="Fechar">×</button></header><div>{children}</div></section></div>;
}
