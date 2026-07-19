'use client';

import { ReactNode, useState } from 'react';
import { Filter, Search, X } from 'lucide-react';
import { MobileBottomSheet } from './MobileBottomSheet';

export function ResponsiveFilterToolbar({ search, filters, activeCount = 0, onClear, primaryAction }: {
  search: ReactNode; filters: ReactNode; activeCount?: number; onClear?: () => void; primaryAction?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return <>
    <div className="responsive-filter-toolbar">
      <div className="responsive-filter-search"><Search size={18} aria-hidden="true" />{search}</div>
      <div className="responsive-filter-desktop">{filters}</div>
      <div className="responsive-filter-mobile-actions">
        <button type="button" className="responsive-filter-button" onClick={() => setOpen(true)} aria-label="Abrir filtros">
          <Filter size={17} />Filtros{activeCount ? <span aria-label={`${activeCount} filtros ativos`}>{activeCount}</span> : null}
        </button>{primaryAction}
      </div>
    </div>
    <MobileBottomSheet open={open} onClose={() => setOpen(false)} title="Filtros" footer={<div className="flex gap-2"><button type="button" className="secondary-button flex-1" onClick={onClear}><X size={16} />Limpar filtros</button><button type="button" className="primary-button flex-1" onClick={() => setOpen(false)}>Aplicar filtros</button></div>}>
      <div className="space-y-3">{filters}</div>
    </MobileBottomSheet>
  </>;
}
